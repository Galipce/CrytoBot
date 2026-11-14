"""Spec 0025 AC-1, AC-5, AC-6, AC-8, AC-9, AC-10: koşu, gerçek okuyucu ve rapor yazıcısıyla.
Spec 0034 B-51: satış slippage ve komisyonu eklenmiş yeni boyutlama (49.115).

Mutlu yol (tek çift BTC, 1h, `candle_count` 4, açılış 10000, ayrım 2. saat), el hesabı:
- Tur 0: kapanmış 10, 8, 9, 10 → öneri giriş 10, stop 8, hedef 14; fiyat 10, dolum 10.01, miktar
  49.115 (helpers.FIRST_AMOUNT). Komisyon 49.115 * 10.01 * 0.001 = 0.49164115; bedel
  492.13279115; bakiye 9507.86720885; kasa 9507.86720885 + 49.115 * 10 = 9999.01720885.
- Tur 1: fiyat 12 (pozisyon açık: `position_open`); kasa 9507.86720885 + 589.38 = 10097.24720885.
- Tur 2 (ayrım): fiyat 15 ≥ hedef 14 → kapanış, dolum 14.985; satış 735.988275, komisyon
  0.735988275, gelir 735.252286725, gerçekleşen 243.119495575; kasa 10243.119495575. Seri 9, 10,
  10, 12: kesişme yok (`no_crossover`).
- Tur 3: fiyat 15; seri 10, 10, 12, 15: kesişme yok; kasa aynı.
Slippage: alımda 49.115 * 0.01 = 0.49115, kapanışta 49.115 * 0.015 = 0.736725.

Spec 0042 R-1 (plan Risk 3): varsayılan koşu yalnız örneklem içidir (turlar 0, 1); örneklem dışı ve
tüm koşu assert'leri aynen son değerlendirmeye (`Run.final`, `force_pass`) taşındı. Son
değerlendirmede saklı dönem 4. saatte başlar: mutlu yolun verisi bir mum (15) uzar ki örneklem dışı
(turlar 2, 3) ve tüm koşu el hesabı değişmesin; 4. turda seri 10, 12, 15, 15: kesişme yok.
"""

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.app import BacktestOutcome
from crytobot.backtest import CONDITIONS, PART_SUFFIX
from crytobot.market_data import HistoryRead
from crytobot.persistence import StoreOutcome, load_store
from crytobot.risk import DEFAULT_LIMITS
from tests.app.backtest_helpers import (
    COUNT,
    GENERATED_AT,
    Run,
    at,
    candle,
    candles,
    config,
    force_pass,
    history,
    report_lines,
    settings,
    write_history,
)
from tests.app.helpers import BTC, ETH, HOUR, limits, refuse_saves

IN, OUT, WHOLE = "örneklem içi", "örneklem dışı — BR-10 kanıtı adayı", "tüm koşu"
HAPPY = {BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15, 15])}
HAPPY_FINAL = {BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 15, 15, 15])}  # one turn of holdout


def btc_only(root: Path, **changes: Any) -> Any:
    return config(root, turn=settings((BTC,)), **changes)


def prepared(root: Path, series: dict[str, Any] = HAPPY, hours: int = 4, **changes: Any) -> Any:
    chosen = config(root, **changes) if "turn" in changes else btc_only(root, **changes)
    write_history(Path(chosen.data_path), history(series, hours=hours))
    return chosen


def leftovers(run: Run) -> list[str]:
    return sorted(path.name for path in run.root.iterdir() if path.name != "work")


def test_happy_path_matches_hand_computation(tmp_path: Path) -> None:
    """AC-1: örneklem içi her metrik el hesabıyla. Spec 0042 R-1: varsayılan koşu yalnız örneklem
    içi turları (0, 1) koşar; konsol örneklem içi dönemi ve tur sayısını yazar."""
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    assert exit_.turns == 2
    assert run.lines[0] == (
        "backtest başladı: dönem=2026-01-01T00:00:00+00:00..2026-01-01T02:00:00+00:00"
        " (örneklem içi) çift=1 tur=2"
    )
    stored = load_store(run.work / "backtest.db", "paper").state
    assert stored is not None
    assert stored.ledger.closures == {}  # the target close is at hour 2: not in this run
    report = run.report(chosen)
    assert_in_sample_by_hand(report_lines(report, IN))
    assert report_lines(report, IN)["fiyatı ya da verisi eksik tur (çift başına)"] == "BTC/USDT 0"
    assert run.lines[-1] == f"backtest tamam: rapor dosyası {chosen.report_path}"


def assert_in_sample_by_hand(inside: dict[str, str]) -> None:
    assert inside["turlar"] == "2 (ilk 2026-01-01T00:00:00+00:00, son 2026-01-01T01:00:00+00:00)"
    assert inside["başlangıç kasası"] == "10000.00000000 USDT"
    assert inside["bitiş kasası"] == "10097.24720885 USDT"
    assert inside["net kâr/zarar"] == "97.24720885 USDT (getiri %0.9725)"
    assert inside["gerçekleşen kâr/zarar"] == "0.00000000 USDT"
    assert inside["gerçekleşmemiş kâr/zarar"] == "97.24720885 USDT"
    assert inside["işlem"] == "0 (kazanan 0, zararlı 0)"
    assert inside["kazanma oranı"] == "tanımsız"
    assert inside["kâr faktörü"] == "tanımsız"
    assert inside["en büyük drawdown"] == "%0.0098"  # 0.98279115 / 10000
    assert inside["ortalama günlük getiri"] == "%0.9725"
    assert inside["ödenen komisyon"] == "0.49164115 USDT"
    assert inside["ödenen slippage"] == "0.49115000 USDT"
    assert inside["öneri yok (nedene göre)"] == "position_open 1"
    assert inside["ret (nedene göre)"] == "yok"


def test_final_happy_path_matches_hand_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1: alım, hedef kapanışı aynı turda ve fiyatta; her parçanın her metriği el hesabıyla
    (son değerlendirme, spec 0042; assert'ler 0025'teki gibi)."""
    force_pass(monkeypatch)
    chosen = prepared(tmp_path, HAPPY_FINAL, hours=5, holdout_at=at(4))
    run = Run(tmp_path)
    exit_ = run.final(chosen)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    assert exit_.turns == 2 + 5  # the in-sample run, then the selected one's whole run
    assert (
        "backtest başladı: dönem=2026-01-01T00:00:00+00:00..2026-01-01T05:00:00+00:00 çift=1 tur=5"
    ) in run.lines
    stored = load_store(run.work / "backtest.db-1", "paper").state  # the whole run's store
    assert stored is not None
    (closure,) = stored.ledger.closures.values()
    assert (closure.position.opened_at, closure.position.cost_price) == (at(0), Decimal("10.01"))
    assert (closure.closed_at, closure.price) == (at(2), Decimal("14.985"))

    report = run.report(chosen)
    inside = report_lines(report, IN)
    assert_in_sample_by_hand(inside)

    outside = report_lines(report, OUT)
    assert outside["başlangıç kasası"] == "10097.24720885 USDT"
    assert outside["bitiş kasası"] == "10243.11949558 USDT"
    assert outside["net kâr/zarar"] == "145.87228672 USDT (getiri %1.4447)"
    assert outside["gerçekleşen kâr/zarar"] == "243.11949558 USDT"
    assert outside["gerçekleşmemiş kâr/zarar"] == "-97.24720885 USDT"
    assert outside["işlem"] == "1 (kazanan 1, zararlı 0)"
    assert outside["kazanma oranı"] == "%100.0000"
    assert outside["en büyük drawdown"] == "%0.0000"
    assert outside["ödenen komisyon"] == "0.73598828 USDT"
    assert outside["ödenen slippage"] == "0.73672500 USDT"
    assert outside["öneri yok (nedene göre)"] == "no_crossover 2"

    whole = report_lines(report, WHOLE)
    assert whole["bitiş kasası"] == "10243.11949558 USDT"
    assert whole["net kâr/zarar"] == "243.11949558 USDT (getiri %2.4312)"
    assert whole["gerçekleşmemiş kâr/zarar"] == "0.00000000 USDT"
    assert whole["ödenen komisyon"] == "1.22762942 USDT"
    assert whole["ödenen slippage"] == "1.22787500 USDT"
    for part in (inside, outside, whole):
        assert part["fiyatı ya da verisi eksik tur (çift başına)"] == "BTC/USDT 0"
        assert part["günlük zarar durdurmalı gün"] == "0"
        assert part["drawdown durdurması"] == "yok"
    assert run.lines[-1] == f"backtest tamam: rapor dosyası {chosen.report_path}"


def test_console_and_file_reports_are_identical(tmp_path: Path) -> None:
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.report is not None
    file_bytes = Path(chosen.report_path).read_bytes()
    assert file_bytes == exit_.report.encode("utf-8")
    assert run.console.encode("utf-8").count(file_bytes) == 1


def test_fingerprint_line_matches_file_bytes(tmp_path: Path) -> None:
    """Spec 0040 CB-1, G-7: dosya yazılınca önceki satır, yazılan baytların SHA-256'sı."""
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.COMPLETED
    digest = hashlib.sha256(Path(chosen.report_path).read_bytes()).hexdigest()
    assert run.lines[-2:] == [
        f"rapor parmak izi: {digest}",
        f"backtest tamam: rapor dosyası {chosen.report_path}",
    ]
    assert digest not in run.report(chosen)  # the fingerprint is never inside the report


def test_no_fingerprint_line_when_the_file_is_not_written(tmp_path: Path) -> None:
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen, write_report=lambda _path, _text: False)
    assert exit_.outcome is BacktestOutcome.REPORT_NOT_WRITTEN
    assert not any(row.startswith("rapor parmak izi") for row in run.lines)


def _header(report: str) -> dict[str, str]:
    rows = report.partition("\n\nvarsayımlar:")[0].splitlines()[1:]
    return dict(row.split(": ", 1) for row in rows)


def test_header_uses_effective_defaults(tmp_path: Path) -> None:
    """Spec 0040 CB-2, CB-3, G-5: başlık botun fiilen kullandığı değerleri ve üretim anını yazar;
    saat bir kez, yalnız rapor için okunur."""
    chosen = prepared(tmp_path, balance=Decimal("12345.5"))
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.COMPLETED
    header = _header(run.report(chosen))
    bot = chosen.bot
    assert header["üretim anı"] == GENERATED_AT.isoformat()
    limits_ = bot.turn.limits
    running = {
        "fee": bot.turn.fee,
        "slippage": bot.turn.slippage,
        "per_trade_risk": limits_.per_trade_risk,
        "daily_loss_limit": limits_.daily_loss_limit,
        "max_drawdown": limits_.max_drawdown,
        "max_open_positions": limits_.max_open_positions,
        "profit_cost_multiple": limits_.profit_cost_multiple,
        "opening_balance": bot.opening_balance,
    }
    assert list(running) == list(CONDITIONS)
    assert {name: Decimal(header[name]) for name in CONDITIONS} == running
    assert header["per_trade_risk"] == format(DEFAULT_LIMITS.per_trade_risk, "f")
    assert header["opening_balance"] == "12345.5"
    assert header["max_open_positions"] == str(DEFAULT_LIMITS.max_open_positions)
    assert run.clock_reads == 1


def test_header_follows_changed_limits(tmp_path: Path) -> None:
    changed = settings((BTC,), limits=limits(per_trade_risk=Decimal("0.005"), max_open_positions=3))
    chosen = prepared(tmp_path, turn=changed)
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.COMPLETED
    header = _header(run.report(chosen))
    assert (header["per_trade_risk"], header["max_open_positions"]) == ("0.005", "3")


def test_refused_run_reads_no_clock(tmp_path: Path) -> None:
    chosen = config(tmp_path)  # no data file
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.REFUSED
    assert run.clock_reads == 0


def test_trade_spanning_split_counts_where_it_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-8: ayrım anının iki yanına uzanan işlem kapandığı parçadadır; örneklem dışı ayrım anındaki
    kasa ve pozisyonla başlar (spec 0042: son değerlendirmede, saklı dönem 3. saatte)."""
    force_pass(monkeypatch)
    chosen = prepared(tmp_path, holdout_at=at(3))
    run = Run(tmp_path)
    run.final(chosen)
    report = run.report(chosen)
    assert report_lines(report, IN)["işlem"].startswith("0 ")
    assert report_lines(report, OUT)["işlem"].startswith("1 ")
    assert report_lines(report, IN)["bitiş kasası"] == report_lines(report, OUT)["başlangıç kasası"]


def test_end_equity_uses_last_known_price(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-8, R-10: açık pozisyon, son turda mumu olmayan çift son bilinen fiyatla değerlenir."""
    force_pass(monkeypatch)
    # spec 0044 R-3 (plan A-1): the holdout holds a candle (hour 2), the last turn (hour 3) none
    series = {BTC: candles(-COUNT, [10, 8, 9, 10, 10, 12, 12, None])}
    chosen = prepared(tmp_path, series, hours=4, split_at=at(1), holdout_at=at(2))
    run = Run(tmp_path)
    exit_ = run.final(chosen)
    assert exit_.outcome is BacktestOutcome.COMPLETED, exit_.message
    report = run.report(chosen)
    whole = report_lines(report, WHOLE)
    assert whole["bitiş kasası"] == "10097.24720885 USDT"  # 9507.86720885 + 49.115 * 12
    assert whole["gerçekleşmemiş kâr/zarar"] == "97.24720885 USDT"
    assert whole["fiyatı ya da verisi eksik tur (çift başına)"] == "BTC/USDT 1"


def test_late_listed_pair_counts_missing_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-6: geç listelenen çiftin önceki turları eksik sayılır, çift başına; koşu sürer.
    Spec 0044 R-3 (plan A-2): çift örneklem içinde listelenir; her dönemde mumu vardır."""
    force_pass(monkeypatch)
    series = {
        BTC: candles(-COUNT, [10, 10, 10, 10, 10, 10, 10, 10]),
        ETH: candles(1, [10, 10, 10]),
    }
    chosen = prepared(tmp_path, series, turn=settings((BTC, ETH)), holdout_at=at(3))
    run = Run(tmp_path)
    assert run.final(chosen).outcome is BacktestOutcome.COMPLETED
    report = run.report(chosen)
    # ETH: no candle before hour 1, at hour 1 a price but no closed candle; at 2 its first closed
    assert report_lines(report, IN)["fiyatı ya da verisi eksik tur (çift başına)"] == (
        "BTC/USDT 0, ETH/USDT 2"
    )
    assert report_lines(report, OUT)["fiyatı ya da verisi eksik tur (çift başına)"] == (
        "BTC/USDT 0, ETH/USDT 0"
    )
    assert report_lines(report, WHOLE)["fiyatı ya da verisi eksik tur (çift başına)"] == (
        "BTC/USDT 0, ETH/USDT 2"
    )


def test_pair_listed_after_the_in_sample_period_refused(tmp_path: Path) -> None:
    """Spec 0044 R-3, AC-2 (plan A-2): örneklem içinde hiç mumu olmayan çift (2. saatte
    listelenen ETH) son değerlendirmede reddedilir; tur atılmaz, rapor yazılmaz."""
    series = {
        BTC: candles(-COUNT, [10, 10, 10, 10, 10, 10, 10, 10]),
        ETH: candles(2, [10, 10]),
    }
    chosen = prepared(tmp_path, series, turn=settings((BTC, ETH)), holdout_at=at(3))
    run = Run(tmp_path)
    exit_ = run.final(chosen)
    assert exit_.outcome is BacktestOutcome.REFUSED
    assert exit_.message == "veri eksik: ETH/USDT 1h örneklem içi"
    assert exit_.turns == 0 and not Path(chosen.report_path).exists()


def _corrupt(path: Path) -> None:
    rows = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(rows[:-2] + rows[-1:]) + "\n", encoding="utf-8")


def _incomplete(path: Path) -> None:
    rows = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")


REFUSALS: dict[str, tuple[dict[str, Any], str]] = {
    "missing file": ({"data": "none"}, "veri dosyası yok"),
    "corrupt": ({"data": "corrupt"}, "veri dosyası bozuk (counts)"),
    "incomplete": ({"data": "incomplete"}, "veri dosyası tamamlanmamış"),
    "whitelist differs": ({"turn": settings((BTC, ETH))}, "çift kümesi beyaz listeden farklı"),
    "candle interval differs": ({"interval": 2}, "mum aralığı farklı (market.candle_interval)"),
    "period off turn boundary": ({"turn_interval": 2 * HOUR, "shift": 1}, "tur aralığı sınırında"),
    "split at start": ({"split_at": at(0)}, "backtest.split_at"),
    "split at end": ({"split_at": at(4)}, "backtest.split_at"),
    "split outside": ({"split_at": at(10)}, "backtest.split_at"),
    "report exists": ({"existing": "rapor.txt"}, "rapor dosyası var"),
    "report part exists": ({"existing": "rapor.txt" + PART_SUFFIX}, "rapor dosyası var"),
}


@pytest.mark.parametrize("case", sorted(REFUSALS))
def test_refusals_run_no_turn_and_write_no_report(tmp_path: Path, case: str) -> None:
    """AC-5: tur atılmaz, rapor dosyası yazılmaz ya da değişmez, neden adıyla söylenir."""
    changes, reason = REFUSALS[case]
    data_kind = changes.pop("data", "ok")
    existing = changes.pop("existing", None)
    interval = changes.pop("interval", 1) * HOUR
    shift = changes.pop("shift", 0)
    chosen = config(tmp_path, **({"turn": settings((BTC,))} | changes))
    series = HAPPY
    if interval != HOUR:  # a 2h file: candles every two hours
        series = {BTC: tuple(candle(at(hour), 10) for hour in range(-8, 4, 2))}
    data = history(series, hours=4, interval=interval)
    if shift:
        data = replace(data, start=at(shift), end=at(4 + shift))
    if data_kind != "none":
        write_history(Path(chosen.data_path), data)
    if data_kind == "corrupt":
        _corrupt(Path(chosen.data_path))
    if data_kind == "incomplete":
        _incomplete(Path(chosen.data_path))
    if existing is not None:
        (tmp_path / existing).write_text("eski", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.REFUSED, exit_.message
    assert reason in exit_.message
    assert exit_.turns == 0 and exit_.report is None
    assert list(run.work.iterdir()) == []  # no store: no turn
    after = {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.is_file()}
    assert after == before
    assert run.lines == [f"backtest reddedildi: {exit_.message}; tur atılmadı"]
    if existing is not None:
        assert run.reads == []  # refused before the data file is read


def test_untrusted_candle_stops_without_report(tmp_path: Path) -> None:
    """AC-5, R-3, R-13: güvenilmez mumlu dosyada koşu durur, rapor kalmaz, neden adıyla."""
    chosen = prepared(tmp_path)
    path = Path(chosen.data_path)
    rows = [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]
    rows[3] = [*rows[3][:3], "1", "2", rows[3][5]]  # high below low
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert exit_.message == "güvenilmeyen veri: BTC/USDT (high_below_low)"
    assert leftovers(run) == ["history.jsonl"]
    assert run.lines == [f"backtest durdu: {exit_.message}; rapor yazılmadı"]


def test_two_runs_give_same_bytes(tmp_path: Path) -> None:
    """AC-9, R-12: aynı dosya, ayar ve üretim anıyla iki koşu bayt bayt aynı rapor (spec 0040)."""
    reports = []
    for name in ("bir", "iki"):
        root = tmp_path / name
        root.mkdir()
        chosen = prepared(root)
        Run(root)(chosen)
        reports.append(Path(chosen.report_path).read_bytes())
    assert reports[0] == reports[1]


def test_stop_request_leaves_no_report(tmp_path: Path) -> None:
    """AC-10, R-13: koşu ortasındaki durdurma isteğinde rapor ne dosyada ne konsolda."""
    chosen = prepared(tmp_path)
    run = Run(tmp_path)

    def write(text: str) -> None:
        run.lines.append(text)
        if "başladı" in text:
            run.stop.request("SIGINT")

    exit_ = run(chosen, write=write)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert exit_.message == "durdurma isteği"
    assert leftovers(run) == ["history.jsonl"]
    assert "CrytoBot backtest raporu" not in run.console
    assert run.lines[-1] == "backtest durdu: durdurma isteği; rapor yazılmadı"


def test_stop_requested_before_the_first_turn(tmp_path: Path) -> None:
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    calls: list[str] = []

    def write_report(path: str, _text: str) -> bool:
        calls.append(path)
        return True

    run.stop.request()
    exit_ = run(chosen, write_report=write_report)
    assert exit_.outcome is BacktestOutcome.STOPPED and calls == []


def test_store_refusal_stops_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-10, R-1: turun depo hatası sonucu koşuyu durdurur, neden adıyla; rapor kalmaz."""
    refuse_saves(monkeypatch, StoreOutcome.WRITE_FAILED, lambda ledger, *_: bool(ledger.positions))
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert exit_.message.startswith("tur sonucu save_refused")
    assert leftovers(run) == ["history.jsonl"]
    assert "CrytoBot backtest raporu" not in run.console


def test_unexpected_error_named_by_type_only(tmp_path: Path) -> None:
    """AC-10, R-13: tip adı, istisna metni ve sır biçimli metin yok."""
    chosen = prepared(tmp_path)
    run = Run(tmp_path)

    def read(_path: str) -> HistoryRead:
        raise ValueError("BINANCE_API_KEY=AKIAKEY0123456789")

    exit_ = run(chosen, read=read)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert exit_.message == "beklenmeyen hata: ValueError"
    assert "AKIA" not in run.console and "BINANCE" not in run.console
    assert leftovers(run) == ["history.jsonl"]


def test_unexpected_error_inside_the_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from crytobot.app import _backtest

    def broken(*_args: Any) -> Any:
        raise RuntimeError("sır: s3cr3t")

    monkeypatch.setattr(_backtest, "run_metrics", broken)
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen)
    assert exit_.message == "beklenmeyen hata: RuntimeError"
    assert "s3cr3t" not in run.console
    assert leftovers(run) == ["history.jsonl"]


def test_report_file_failure_prints_console(tmp_path: Path) -> None:
    """AC-10, R-13: rapor konsolda, "rapor dosyası yazılamadı", tamamlanmış görünen dosya yok."""
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    exit_ = run(chosen, write_report=lambda _path, _text: False)
    assert exit_.outcome is BacktestOutcome.REPORT_NOT_WRITTEN
    assert exit_.report is not None and exit_.report in run.console
    assert run.lines[-1] == (
        f"backtest rapor dosyası yazılamadı: {chosen.report_path}; rapor yalnız konsolda"
    )
    assert leftovers(run) == ["history.jsonl"]


def test_report_directory_missing_with_real_writer(tmp_path: Path) -> None:
    chosen = replace(prepared(tmp_path), report_path=str(tmp_path / "yok" / "rapor.txt"))
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.REPORT_NOT_WRITTEN
    assert leftovers(run) == ["history.jsonl"]


def test_temporary_store_that_exists_stops(tmp_path: Path) -> None:
    chosen = prepared(tmp_path)
    run = Run(tmp_path)
    (run.work / "backtest.db").write_text("eski", encoding="utf-8")
    exit_ = run(chosen)
    assert exit_.outcome is BacktestOutcome.STOPPED
    assert exit_.message.startswith("geçici depo hazırlanamadı")


def test_report_counts_refusals_by_source(tmp_path: Path) -> None:
    """R-10: `risk` retleri nedenine göre (tek açık pozisyon sınırı)."""
    from tests.app.helpers import limits

    series = {
        BTC: candles(-COUNT, [10, 8, 9, 10, 10, 10, 10, 10]),
        ETH: candles(-COUNT, [10, 8, 9, 10, 10, 10, 10, 10]),
    }
    chosen = prepared(
        tmp_path, series, turn=settings((BTC, ETH), limits=limits(max_open_positions=1))
    )
    run = Run(tmp_path)
    assert run(chosen).outcome is BacktestOutcome.COMPLETED
    assert report_lines(run.report(chosen), IN)["ret (nedene göre)"] == "risk.position_limit 1"


def test_never_touches_the_bot_store_or_log(tmp_path: Path) -> None:
    chosen = prepared(tmp_path)
    Run(tmp_path)(chosen)
    assert not Path(chosen.bot.store_path).exists()
    assert not Path(chosen.bot.log_path).exists()
