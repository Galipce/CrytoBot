"""Spec 0017 AC-4: süre, bütçe, yeniden deneme, istek sınırı (R-4; plan Risk 6, 7)."""

import threading
import time
from collections.abc import Iterator

import pytest
import requests

from crytobot.market_data._calls import Caller, CallFailed
from crytobot.market_data._client import CallFailure, ExchangeCallError
from crytobot.market_data._types import IssueReason
from tests.market_data.helpers import Steps, fixture, http_response, recorded_client


@pytest.fixture
def release() -> Iterator[threading.Event]:
    """Takılan çağrılar test sonunda serbest kalır, geride iş parçacığı kalmaz."""
    event = threading.Event()
    yield event
    event.set()


def _counting(*answers: object) -> tuple[list[float], object]:
    steps = Steps(*answers)
    times: list[float] = []

    def request(timeout: float) -> object:
        times.append(time.monotonic())
        answer = steps.next()
        if isinstance(answer, Exception):
            raise answer
        return answer

    return times, request


TRANSIENT = ExchangeCallError(CallFailure.TRANSIENT)


def test_hung_call_is_cut_at_its_limit(release: threading.Event) -> None:
    attempts: list[float] = []

    def hang(timeout: float) -> None:
        attempts.append(timeout)
        release.wait(30)

    started = time.monotonic()
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=0.05, read_budget=20).call(hang)
    assert failed.value.reason is IssueReason.CALL_TIMED_OUT
    assert len(attempts) == 3
    # three 0.05 s attempts and the 0.25 + 0.5 s waits; far below the hung call's 30 s
    assert time.monotonic() - started < 5


def test_call_limit_shrinks_to_the_remaining_budget(release: threading.Event) -> None:
    limits: list[float] = []

    def hang(timeout: float) -> None:
        limits.append(timeout)
        release.wait(30)

    started = time.monotonic()
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=10, read_budget=0.1).call(hang)
    assert failed.value.reason is IssueReason.BUDGET_ENDED
    assert limits[0] <= 0.1 + 1e-6
    assert time.monotonic() - started < 2


def test_spent_budget_sends_nothing() -> None:
    times, request = _counting("value")
    caller = Caller(call_timeout=1, read_budget=0.01)
    time.sleep(0.02)
    with pytest.raises(CallFailed) as failed:
        caller.call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.BUDGET_ENDED
    assert times == []


def test_transient_error_retries_then_succeeds() -> None:
    times, request = _counting(TRANSIENT, TRANSIENT, "value")
    assert Caller(call_timeout=5, read_budget=20).call(request) == "value"  # type: ignore[arg-type]
    assert len(times) == 3
    assert times[1] - times[0] >= 0.24
    assert times[2] - times[1] >= 0.49


def test_transient_error_stops_after_three_attempts() -> None:
    times, request = _counting(TRANSIENT)
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=20).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.NETWORK
    assert len(times) == 3


def test_waiting_past_the_budget_is_not_attempted() -> None:
    times, request = _counting(TRANSIENT)
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=0.1).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.BUDGET_ENDED
    assert len(times) == 1


def test_bad_symbol_gets_one_call() -> None:
    times, request = _counting(ExchangeCallError(CallFailure.BAD_SYMBOL))
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=20).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.BAD_SYMBOL
    assert len(times) == 1


def test_bad_response_gets_one_call() -> None:
    times, request = _counting(ExchangeCallError(CallFailure.BAD_RESPONSE))
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=20).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.MALFORMED_RESPONSE
    assert len(times) == 1


def test_unknown_exception_is_named_without_retry() -> None:
    times, request = _counting(RuntimeError("secret text"))
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=20).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.UNEXPECTED
    assert "secret" not in str(failed.value)
    assert len(times) == 1


def test_retry_after_is_respected() -> None:
    times, request = _counting(ExchangeCallError(CallFailure.RATE_LIMITED, 0.6), "value")
    assert Caller(call_timeout=5, read_budget=20).call(request) == "value"  # type: ignore[arg-type]
    assert times[1] - times[0] >= 0.59


def test_retry_after_past_the_budget_is_not_waited() -> None:
    times, request = _counting(ExchangeCallError(CallFailure.RATE_LIMITED, 500))
    started = time.monotonic()
    with pytest.raises(CallFailed) as failed:
        Caller(call_timeout=5, read_budget=2).call(request)  # type: ignore[arg-type]
    assert failed.value.reason is IssueReason.BUDGET_ENDED
    assert len(times) == 1
    assert time.monotonic() - started < 1


def test_ban_stops_further_calls() -> None:
    times, request = _counting(ExchangeCallError(CallFailure.BANNED, 100))
    caller = Caller(call_timeout=5, read_budget=20)
    for _ in range(2):
        with pytest.raises(CallFailed) as failed:
            caller.call(request)  # type: ignore[arg-type]
        assert failed.value.reason is IssueReason.RATE_LIMITED
    assert len(times) == 1


# Real ccxt, only the HTTP session is fake: what each status becomes.
@pytest.mark.parametrize(
    ("status", "body", "headers", "failure", "retry_after"),
    [
        (400, '{"code":-1121,"msg":"Invalid symbol."}', {}, CallFailure.BAD_SYMBOL, None),
        (418, '{"code":-1003,"msg":"banned"}', {"Retry-After": "120"}, CallFailure.BANNED, 120.0),
        (429, '{"code":-1003,"msg":"slow"}', {"Retry-After": "7"}, CallFailure.RATE_LIMITED, 7.0),
        (429, "<html>", {"Retry-After": "soon"}, CallFailure.RATE_LIMITED, None),
        (503, "maintenance", {}, CallFailure.TRANSIENT, None),
        (504, "gateway", {}, CallFailure.TRANSIENT, None),
        (401, '{"code":-2015,"msg":"key"}', {}, CallFailure.OTHER, None),
    ],
)
def test_http_status_maps_to_failure(
    status: int, body: str, headers: dict[str, str], failure: CallFailure, retry_after: float | None
) -> None:
    client, _ = recorded_client({"ticker/24hr": http_response(status, body, headers)})
    with pytest.raises(ExchangeCallError) as raised:
        client.ticker("BTCUSDT", 5.0)
    assert raised.value.failure is failure
    assert raised.value.retry_after == retry_after
    assert body not in str(raised.value)


def test_recorded_bad_symbol_answer_maps_to_bad_symbol() -> None:
    body = str(fixture("error_bad_symbol")).replace("'", '"')
    client, _ = recorded_client({"ticker/24hr": http_response(400, body)})
    with pytest.raises(ExchangeCallError) as raised:
        client.ticker("NOPEUSDT", 5.0)
    assert raised.value.failure is CallFailure.BAD_SYMBOL


@pytest.mark.parametrize(
    "error", [requests.exceptions.ConnectTimeout(), requests.exceptions.ConnectionError()]
)
def test_network_errors_are_transient(error: Exception) -> None:
    client, _ = recorded_client({"ticker/24hr": error})
    with pytest.raises(ExchangeCallError) as raised:
        client.ticker("BTCUSDT", 5.0)
    assert raised.value.failure is CallFailure.TRANSIENT


def test_ccxt_socket_timeout_follows_the_call_limit() -> None:
    client, session = recorded_client()
    client.ticker("BTCUSDT", 1.5)
    assert session.requests[0]["timeout"] == 1.5


@pytest.mark.parametrize("body", ["{}", "[]", "not json", "", '{"symbols":"x"}'])
def test_unreadable_markets_answer_is_a_bad_response(body: str) -> None:
    """`ccxt` bunları boş piyasa listesi yapar; "çift listede yok" diye raporlanmamalı."""
    client, _ = recorded_client({"exchangeInfo": http_response(200, body)})
    with pytest.raises(ExchangeCallError) as raised:
        client.markets(5.0)
    assert raised.value.failure is CallFailure.BAD_RESPONSE


def test_market_ccxt_cannot_parse_is_an_exchange_error() -> None:
    client, _ = recorded_client({"exchangeInfo": http_response(200, '{"symbols":[{"a":1}]}')})
    with pytest.raises(ExchangeCallError) as raised:
        client.markets(5.0)
    assert raised.value.failure is CallFailure.OTHER
