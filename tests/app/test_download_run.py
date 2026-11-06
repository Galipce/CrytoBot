"""Spec 0023 AC-1 (özet), AC-7 (durma nedeni adıyla, tip adı, sır yok): `run_download`'un çıktısı.

İndirme işlevi sahtedir: `app` indirmeyi yalnız `DownloadParts` ile verilen işlevle yapar. Bu dosya
`tests/tooling` kopyasına girer: yalnız `tests/app`'ten import eder.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from crytobot.app import (
    DownloadConfig,
    DownloadParts,
    ForcedStop,
    StopRequest,
    load_download_config,
    run_download,
)
from crytobot.market_data import (
    HistoryRequest,
    HistoryResult,
    HistoryStop,
    HistoryStopReason,
    PairSummary,
)
from tests.app.test_download_config import END, NOW, START, download_document

SECRET = "AKIAKEY0123456789 s3cr3t"
BTC_SUMMARY = PairSummary(
    "BTC/USDT", START - timedelta(hours=200), END - timedelta(hours=1), 944, 2
)
ETH_SUMMARY = PairSummary("ETH/USDT", START + timedelta(hours=5), END - timedelta(hours=1), 739, 0)


def config() -> DownloadConfig:
    result = load_download_config(download_document(), NOW)
    assert result.config is not None
    return result.config


@dataclass
class Parts:
    answer: HistoryResult | BaseException
    lines: list[str] = field(default_factory=list)
    requests: list[HistoryRequest] = field(default_factory=list)
    stop: StopRequest = field(default_factory=StopRequest)
    asked_stop: list[bool] = field(default_factory=list)

    def download(
        self,
        request: HistoryRequest,
        clock: Callable[[], datetime],
        stop_requested: Callable[[], bool],
    ) -> HistoryResult:
        self.requests.append(request)
        assert clock() == NOW
        self.asked_stop.append(stop_requested())
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer

    def parts(self, clock: Callable[[], datetime] = lambda: NOW) -> DownloadParts:
        return DownloadParts(clock, self.download, self.lines.append, self.stop)


def done(*summaries: PairSummary) -> HistoryResult:
    return HistoryResult(summaries, None, NOW)


def stopped(stop: HistoryStop) -> HistoryResult:
    return HistoryResult((), stop, NOW)


def test_completed_download_prints_a_summary_per_pair() -> None:
    """AC-1: özet çift başına ilk ve son mum, sayı ve boşluk; sonra tamam satırı."""
    fake = Parts(done(BTC_SUMMARY, ETH_SUMMARY))
    exit_ = run_download(config(), fake.parts())
    assert exit_.completed
    assert fake.lines == [
        "2026-11-06T12:00:00+00:00 indirme başladı: çiftler=BTC/USDT,ETH/USDT aralık=1h"
        " dönem=2026-01-01T00:00:00+00:00..2026-02-01T00:00:00+00:00 ısınma=200"
        " dosya=history.jsonl",
        "2026-11-06T12:00:00+00:00 özet BTC/USDT ilk=2025-12-23T16:00:00+00:00"
        " son=2026-01-31T23:00:00+00:00 mum=944 boşluk=2",
        "2026-11-06T12:00:00+00:00 özet ETH/USDT ilk=2026-01-01T05:00:00+00:00"
        " son=2026-01-31T23:00:00+00:00 mum=739 boşluk=0",
        "2026-11-06T12:00:00+00:00 indirme tamam: dosya=history.jsonl çift=2",
    ]
    (request,) = fake.requests
    assert request == config().request()
    assert fake.asked_stop == [False]


def test_stop_request_reaches_the_download() -> None:
    fake = Parts(stopped(HistoryStop(HistoryStopReason.STOP_REQUESTED)))
    fake.stop.request("SIGINT")
    exit_ = run_download(config(), fake.parts())
    assert not exit_.completed and fake.asked_stop == [True]
    assert fake.lines[-1].endswith(
        "indirme durdu: durdurma isteği; tamamlanmış veri dosyası yazılmadı"
    )


BAN_END = datetime(2026, 11, 6, 12, 2, tzinfo=UTC)
STOP_TEXTS = [
    (HistoryStop(HistoryStopReason.NETWORK), "ağ hatası"),
    (HistoryStop(HistoryStopReason.STOP_REQUESTED), "durdurma isteği"),
    (HistoryStop(HistoryStopReason.CALL_TIMED_OUT), "çağrı süresi aşıldı"),
    (
        HistoryStop(HistoryStopReason.RATE_LIMITED),
        "istek sınırı uyarısı (HTTP 429); yeniden istek atılmadı",
    ),
    (
        HistoryStop(HistoryStopReason.BANNED, ban_until=BAN_END),
        "borsa yasağı (HTTP 418), bitiş 2026-11-06T12:02:00+00:00; yeniden istek atılmadı",
    ),
    (
        HistoryStop(HistoryStopReason.BANNED),
        "borsa yasağı (HTTP 418), bitiş bildirilmedi; yeniden istek atılmadı",
    ),
    (
        HistoryStop(HistoryStopReason.EXCHANGE_ERROR, detail="bad_symbol"),
        "borsa hatası (bad_symbol)",
    ),
    (
        HistoryStop(HistoryStopReason.UNTRUSTED_DATA, "ETH/USDT", "duplicate_time"),
        "güvenilmeyen veri: ETH/USDT (duplicate_time)",
    ),
    (
        HistoryStop(HistoryStopReason.MISSING_RULES, "ETH/USDT", "tick_not_reported"),
        "çiftin kuralları eksik: ETH/USDT (tick_not_reported)",
    ),
    (
        HistoryStop(HistoryStopReason.PAIR_UNAVAILABLE, "XYZ/USDT", "not_listed"),
        "çift borsada yok ya da kullanılamaz: XYZ/USDT (not_listed)",
    ),
    (HistoryStop(HistoryStopReason.NO_CANDLES, "ETH/USDT"), "dönemde hiç mum yok: ETH/USDT"),
    (
        HistoryStop(HistoryStopReason.DATA_FILE_EXISTS),
        "veri dosyası zaten var: history.jsonl; üzerine yazılmaz",
    ),
    (
        HistoryStop(HistoryStopReason.PART_FILE_EXISTS),
        "yarım kalmış indirme dosyası var: history.jsonl.part; silinmeden indirme yapılmaz",
    ),
    (HistoryStop(HistoryStopReason.WRITE_FAILED), "veri dosyası yazılamıyor: history.jsonl"),
    (HistoryStop(HistoryStopReason.INPUT, detail="end"), "indirme girdisi geçersiz (end)"),
    (HistoryStop(HistoryStopReason.INPUT), "indirme girdisi geçersiz (-)"),
    (
        HistoryStop(HistoryStopReason.UNEXPECTED, error_type="KeyError"),
        "beklenmeyen hata: KeyError",
    ),
]


def test_every_stop_reason_has_a_text() -> None:
    assert {stop.reason for stop, _ in STOP_TEXTS} == set(HistoryStopReason)


@pytest.mark.parametrize(("stop", "text"), STOP_TEXTS, ids=[s.reason.value for s, _ in STOP_TEXTS])
def test_stop_is_named(stop: HistoryStop, text: str) -> None:
    """AC-7: nedeni adıyla; yasağın bitişi biliniyorsa söylenir."""
    fake = Parts(stopped(stop))
    exit_ = run_download(config(), fake.parts())
    assert not exit_.completed and exit_.result == stopped(stop)
    assert len(fake.lines) == 2
    assert fake.lines[-1] == (
        f"2026-11-06T12:00:00+00:00 indirme durdu: {text}; tamamlanmış veri dosyası yazılmadı"
    )


def test_unexpected_error_of_the_download_is_named_by_type_only() -> None:
    """AC-7: istisna metni ve sır biçimli metin çıktıda yoktur."""
    fake = Parts(RuntimeError(SECRET))
    exit_ = run_download(config(), fake.parts())
    assert not exit_.completed and exit_.result is None
    assert fake.lines[-1].endswith(
        "indirme durdu: beklenmeyen hata: RuntimeError; tamamlanmış veri dosyası yazılmadı"
    )
    output = "\n".join(fake.lines)
    assert "s3cr3t" not in output and "AKIA" not in output


def test_forced_stop_is_written_and_raised_again() -> None:
    fake = Parts(ForcedStop("SIGINT"))
    with pytest.raises(ForcedStop):
        run_download(config(), fake.parts())
    assert fake.lines[-1].endswith(
        "indirme durdu: zorla durdurma; tamamlanmış veri dosyası yazılmadı"
    )


def test_broken_clock_still_writes_the_lines() -> None:
    def broken() -> datetime:
        raise RuntimeError(SECRET)

    fake = Parts(done(BTC_SUMMARY))

    def download(
        request: HistoryRequest, clock: Callable[[], datetime], stop: Callable[[], bool]
    ) -> HistoryResult:
        return done(BTC_SUMMARY)

    parts = DownloadParts(broken, download, fake.lines.append, fake.stop)
    assert run_download(config(), parts).completed
    assert all(line.startswith("- ") for line in fake.lines)
    assert "s3cr3t" not in "\n".join(fake.lines)
