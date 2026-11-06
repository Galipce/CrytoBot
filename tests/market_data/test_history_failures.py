"""Spec 0023 AC-7, R-7, R-8: ağ hatası, süre aşımı, 429, 418 (± `Retry-After`) indirmeyi durdurur ve
sonra istek gitmez; durdurma isteği, zorla durdurma ve beklenmeyen hata yarım dosya bırakmaz.

`call_once` (plan Risk 3) ayrıca tek başına sınanır: yeniden deneme yoktur, tek istek gider.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from crytobot.market_data import HistoryResult, HistoryStop, HistoryStopReason, download_history
from crytobot.market_data._calls import OnceFailed, call_once
from crytobot.market_data._client import CallFailure, ExchangeCallError
from crytobot.market_data._types import IssueReason
from tests.market_data.history_helpers import (
    DOWNLOADED_AT,
    FakeHistoryExchange,
    full_history,
    leftovers,
    make_request,
    run_download,
)

SECRET = "AKIAKEY0123456789 s3cr3t"


class Forced(BaseException):
    """`ForcedStop` gibi: `except Exception` onu yutmaz."""


def stopped(tmp_path: Path, result: HistoryResult, reason: HistoryStopReason) -> HistoryStop:
    assert result.stop is not None and result.stop.reason is reason, result.stop
    assert result.summaries == ()
    assert leftovers(tmp_path) == []
    return result.stop


# --- call_once ------------------------------------------------------------------------------


def test_call_once_returns_the_value() -> None:
    seen: list[float] = []

    def request(timeout: float) -> str:
        seen.append(timeout)
        return "value"

    assert call_once(request, 5) == "value"
    assert seen == [5]


@pytest.mark.parametrize(
    ("failure", "retry_after", "reason", "banned"),
    [
        (CallFailure.TRANSIENT, None, IssueReason.NETWORK, False),
        (CallFailure.RATE_LIMITED, 30.0, IssueReason.RATE_LIMITED, False),
        (CallFailure.BANNED, 120.0, IssueReason.RATE_LIMITED, True),
        (CallFailure.BANNED, None, IssueReason.RATE_LIMITED, True),
        (CallFailure.BAD_SYMBOL, None, IssueReason.BAD_SYMBOL, False),
        (CallFailure.BAD_RESPONSE, None, IssueReason.MALFORMED_RESPONSE, False),
        (CallFailure.OTHER, None, IssueReason.EXCHANGE_ERROR, False),
    ],
)
def test_call_once_names_the_failure_and_never_retries(
    failure: CallFailure, retry_after: float | None, reason: IssueReason, banned: bool
) -> None:
    attempts: list[float] = []

    def request(timeout: float) -> object:
        attempts.append(timeout)
        raise ExchangeCallError(failure, retry_after)

    with pytest.raises(OnceFailed) as caught:
        call_once(request, 5)
    assert caught.value.reason is reason
    assert caught.value.banned is banned
    assert caught.value.retry_after == retry_after
    assert len(attempts) == 1


def test_call_once_times_out_after_its_own_limit() -> None:
    def hang(timeout: float) -> object:
        time.sleep(1)
        return "late"

    began = time.monotonic()
    with pytest.raises(OnceFailed) as caught:
        call_once(hang, 0.05)
    assert caught.value.reason is IssueReason.CALL_TIMED_OUT
    assert time.monotonic() - began < 0.9


def test_call_once_lets_an_unexpected_error_through() -> None:
    def broken(timeout: float) -> object:
        raise KeyError("x")

    with pytest.raises(KeyError):
        call_once(broken, 5)


# --- the download ---------------------------------------------------------------------------


@pytest.mark.parametrize("at_call", [1, 2, 3])
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ExchangeCallError(CallFailure.TRANSIENT), HistoryStopReason.NETWORK),
        (ExchangeCallError(CallFailure.RATE_LIMITED, 30.0), HistoryStopReason.RATE_LIMITED),
        (ExchangeCallError(CallFailure.BANNED, None), HistoryStopReason.BANNED),
        (ExchangeCallError(CallFailure.OTHER), HistoryStopReason.EXCHANGE_ERROR),
    ],
    ids=["network", "429", "418", "other"],
)
def test_failure_stops_and_nothing_is_asked_after_it(
    tmp_path: Path, at_call: int, error: ExchangeCallError, reason: HistoryStopReason
) -> None:
    """AC-7: piyasalarda, ilk ve ikinci çiftin mumunda; sonra borsaya yeni istek gitmez."""
    exchange = FakeHistoryExchange(full_history(), fail={at_call: error})
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped(tmp_path, result, reason)
    assert len(exchange.calls) == at_call
    assert stop.ban_until is None


def test_ban_with_retry_after_names_its_end(tmp_path: Path) -> None:
    """AC-7: `Retry-After`'lı 418: bitiş anı yasağın görüldüğü andan sonradır."""
    exchange = FakeHistoryExchange(
        full_history(), fail={2: ExchangeCallError(CallFailure.BANNED, 120.0)}
    )
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped(tmp_path, result, HistoryStopReason.BANNED)
    assert stop.ban_until == DOWNLOADED_AT + timedelta(seconds=120)
    assert exchange.calls == ["markets", "klines BTCUSDT"]


def test_ban_end_past_the_calendar_is_unknown(tmp_path: Path) -> None:
    exchange = FakeHistoryExchange(
        full_history(), fail={1: ExchangeCallError(CallFailure.BANNED, 1e18)}
    )
    stop = stopped(
        tmp_path,
        run_download(make_request(tmp_path / "h.jsonl"), exchange),
        HistoryStopReason.BANNED,
    )
    assert stop.ban_until is None


def test_ban_end_with_a_broken_clock_is_unknown(tmp_path: Path) -> None:
    moments = iter([DOWNLOADED_AT])

    def clock() -> object:
        return next(moments)  # the second reading raises StopIteration

    exchange = FakeHistoryExchange(
        full_history(), fail={1: ExchangeCallError(CallFailure.BANNED, 60.0)}
    )
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange, clock=clock)  # type: ignore[arg-type]
    assert stopped(tmp_path, result, HistoryStopReason.BANNED).ban_until is None


def test_call_over_its_time_stops_the_download(tmp_path: Path) -> None:
    """AC-7: okuma ayarındaki çağrı süresi aşılırsa durur; yeni istek gitmez."""

    def slow(rows: list[list[object]]) -> object:
        time.sleep(0.5)
        return rows

    exchange = FakeHistoryExchange(full_history(), tamper={1: slow})
    request = make_request(tmp_path / "h.jsonl", call_timeout=timedelta(milliseconds=50))
    result = run_download(request, exchange)
    stopped(tmp_path, result, HistoryStopReason.CALL_TIMED_OUT)
    time.sleep(0.6)  # the abandoned call ends; it sends nothing more
    assert exchange.calls == ["markets", "klines BTCUSDT"]


def test_connect_failure_stops_before_any_call(tmp_path: Path) -> None:
    def connect() -> object:
        raise ExchangeCallError(CallFailure.TRANSIENT)

    result = download_history(
        make_request(tmp_path / "h.jsonl"),
        lambda: DOWNLOADED_AT,
        lambda: False,
        connect=connect,  # type: ignore[arg-type]
    )
    stopped(tmp_path, result, HistoryStopReason.NETWORK)


def test_stop_request_mid_download_leaves_no_file(tmp_path: Path) -> None:
    """AC-7, R-8: durdurma isteğinden sonra istek gitmez, ne dosya ne `.part` kalır."""
    requested = False

    def ask(call: int) -> None:
        nonlocal requested
        requested = requested or call == 2

    exchange = FakeHistoryExchange(full_history(), on_call=ask)
    path = tmp_path / "h.jsonl"
    result = run_download(make_request(path), exchange, stop_requested=lambda: requested)
    stopped(tmp_path, result, HistoryStopReason.STOP_REQUESTED)
    assert len(exchange.calls) == 2


def test_forced_stop_mid_download_leaves_no_file(tmp_path: Path) -> None:
    """R-8: ikinci istek (`BaseException`) ana iş parçacığında, sinyal işleyicisinden fırlar ve
    indirmeden geçer; `.part` yine silinir."""
    checks = 0

    def second_signal() -> bool:
        nonlocal checks
        checks += 1
        if checks == 3:
            raise Forced
        return False

    exchange = FakeHistoryExchange(full_history())
    path = tmp_path / "h.jsonl"
    with pytest.raises(Forced):
        run_download(make_request(path), exchange, stop_requested=second_signal)
    assert len(exchange.calls) == 1  # connect and markets passed; the header is on disk
    assert leftovers(tmp_path) == []


def test_unexpected_error_is_named_by_type_only(tmp_path: Path) -> None:
    """AC-7, R-8: beklenmeyen hata tip adıyla döner; metni hiçbir alanda yoktur."""
    exchange = FakeHistoryExchange(full_history(), fail={3: RuntimeError(SECRET)})
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange)
    stop = stopped(tmp_path, result, HistoryStopReason.UNEXPECTED)
    assert stop.error_type == "RuntimeError"
    assert "s3cr3t" not in repr(result) and "AKIA" not in repr(result)


def broken_clock() -> object:
    raise RuntimeError(SECRET)


@pytest.mark.parametrize(
    "clock",
    [broken_clock, lambda: datetime(2026, 6, 1), lambda: "2026-06-01"],
    ids=["raises", "naive", "text"],
)
def test_unreadable_clock_is_an_input_problem(tmp_path: Path, clock: Callable[[], object]) -> None:
    exchange = FakeHistoryExchange(full_history())
    result = run_download(make_request(tmp_path / "h.jsonl"), exchange, clock=clock)  # type: ignore[arg-type]
    stop = stopped(tmp_path, result, HistoryStopReason.INPUT)
    assert stop.detail == "clock" and exchange.calls == []
