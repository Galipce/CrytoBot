"""Spec 0028 AC-1, AC-2, AC-3, AC-8: BR-10 aşama kapısı CLI ve fail-closed başlatma testleri.

Spec 0042 (plan Risk 8): geçerli rapor son değerlendirme biçimindedir (tek aday, paper adayı S0);
AC-8: strateji adı farklı ya da rapor son değerlendirme değilse ret, depo yok, çıkış 1."""

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED
from crytobot.app import TRIAL_MARK
from crytobot.app import _start as start_module
from crytobot.backtest import (
    CANDIDATE_MARK,
    PASSED,
    CandidateResult,
    ReportFacts,
    final_report_text,
    run_metrics,
)
from crytobot.persistence import StoreOutcome, StoreResult, load_start_records
from tests.backtest.test_metrics import BTC, DAY1, DAY2
from tests.backtest.test_report import CONDITION_FACTS
from tests.main.test_entry import Bot, config_text, event_lines

SHA = "0123456789abcdef" * 4  # a syntactically valid fingerprint for the setting-error cases
APPROVED_AT = "2026-11-02T12:00:00Z"  # spec 0040 CB-2: after the generation, before the clock
BACKTEST_SPREAD = '\n[backtest]\nspread = "0.0005"\n'  # spec 0040 CB-4: the running spread


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_valid_report_text() -> str:
    """AC-1 için geçerli, tüm eşikleri karşılayan ve adayı olan backtest raporu."""
    facts = ReportFacts(
        start=DAY1,
        end=DAY1 + timedelta(days=10),
        candle_interval="1h",
        turn_interval="1h",
        split_at=DAY2,
        pairs=(BTC, "ETH/USDT"),
        downloaded_at=datetime(2026, 11, 1, tzinfo=UTC),
        candle_count=200,
        spread=Decimal("0.0005"),
        strategy={
            "fast_period": 12,
            "slow_period": 26,
            "rsi_period": 14,
            "rsi_threshold": Decimal("70"),
            "atr_period": 14,
            "k": Decimal("2"),
            "r": Decimal("2"),
        },
        **CONDITION_FACTS,
        strategy_name="S0",
        holdout_at=DAY2 + timedelta(days=5),
    )
    metrics = run_metrics(Decimal(10000), (), DAY2, (BTC, "ETH/USDT"), facts.holdout_at)
    assert facts.strategy is not None
    result = CandidateResult(
        "S0",
        "1h",
        facts.strategy,
        metrics.in_sample,
        metrics.out_of_sample,
        metrics.holdout,
        PASSED,
    )
    text = final_report_text(facts, 1, [result], 0, metrics)
    old_part = f"== örneklem dışı — {CANDIDATE_MARK} =="
    new_part = f"""{old_part}
turlar: 120 (ilk 2026-01-02T00:00:00+00:00, son 2026-01-07T00:00:00+00:00)
başlangıç kasası: 10000.00000000 USDT
bitiş kasası: 10500.00000000 USDT
net kâr/zarar: 500.00000000 USDT (getiri %5.0000)
gerçekleşen kâr/zarar: 500.00000000 USDT
gerçekleşmemiş kâr/zarar: 0.00000000 USDT
işlem: 15 (kazanan 10, zararlı 5)
kazanma oranı: %66.6667
kâr faktörü: 2.0000
en büyük drawdown: %4.0000
ortalama günlük getiri: %1.0000
ödenen komisyon: 10.00000000 USDT
ödenen slippage: 10.00000000 USDT
günlük zarar durdurmalı gün: 0
drawdown durdurması: yok
fiyatı ya da verisi eksik tur (çift başına): yok
öneri yok (nedene göre): yok
ret (nedene göre): yok
gönderilmeyen durum bildirimi (türe göre): yok"""
    return text.replace(
        text.partition(old_part)[2].partition("\n== ")[0],
        new_part.partition(old_part)[2],
    )


def test_confirmed_start_happy_path(tmp_path: Path) -> None:
    """AC-1: Mutlu yol — geçerli [stage] ve backtest raporuyla kanıtlı başlatma."""
    report_file = tmp_path / "backtest-report.txt"
    report_file.write_text(make_valid_report_text(), encoding="utf-8")

    stage_toml = f"""
[stage]
report_path = "{report_file.as_posix()}"
report_sha256 = "{fingerprint(report_file)}"
approved_by = "Galip Badem"
approved_at = "{APPROVED_AT}"
min_trades = 10
min_profit_factor = "1.5"
"""
    bot = Bot(tmp_path)
    base_text = config_text(tmp_path) + BACKTEST_SPREAD
    (tmp_path / "crytobot.toml").write_text(base_text + stage_toml, encoding="utf-8")

    # Önce hazırlık
    assert bot.run("prepare")[0] == EXIT_OK

    # Kanıtlı başlatma (start, --trial yok)
    code, console = bot.run("start", trial=False)
    assert code == EXIT_OK
    log = bot.log_lines()

    # Başlatma çıktısı onaylayan adını ve rapor yolunu taşır
    (start_line,) = event_lines(console, "başlatma")
    assert "onaylı: onaylayan=Galip Badem" in start_line
    assert f"rapor={report_file.as_posix()}" in start_line
    assert TRIAL_MARK not in start_line

    # Tur özetlerinde TRIAL_MARK yer almaz
    summaries = event_lines(console, "tur")
    assert len(summaries) >= 1
    assert all(TRIAL_MARK not in row for row in summaries)

    # Kayıt dosyasında da TRIAL_MARK yer almaz
    log_text = "\n".join(log)
    assert TRIAL_MARK not in log_text
    assert "onaylı: onaylayan=Galip Badem" in log_text


def test_start_without_stage_refused(tmp_path: Path) -> None:
    """AC-2: Varsayılan başlatmada [stage] veya zorunlu alanlar eksikken ret."""
    bot = Bot(tmp_path)

    # 1. [stage] bölümü hiç yokken varsayılan start
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: ayar eksik: stage" in console

    # 2. report_path eksik
    stage_no_rp = """
[stage]
approved_by = "Galip"
approved_at = "2026-11-08T12:00:00Z"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_rp, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.report_path" in console

    # 3. approved_by eksik
    stage_no_ab = f"""
[stage]
report_path = "rep.txt"
report_sha256 = "{SHA}"
approved_at = "2026-11-08T12:00:00Z"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_ab, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.approved_by" in console

    # 4. approved_at eksik
    stage_no_at = f"""
[stage]
report_path = "rep.txt"
report_sha256 = "{SHA}"
approved_by = "Galip"
"""
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path) + stage_no_at, encoding="utf-8")
    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "stage.approved_at" in console


def test_start_trial_mode_skips_gate(tmp_path: Path) -> None:
    """AC-3: crytobot start --trial kapıyı atlar ve TRIAL_MARK taşır."""
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK

    code, console = bot.run("start", "--trial")
    assert code == EXIT_OK

    (start_line,) = event_lines(console, "başlatma")
    assert TRIAL_MARK in start_line
    summaries = event_lines(console, "tur")
    assert summaries and all(TRIAL_MARK in row for row in summaries)


def test_fail_closed_touches_no_store_or_network(tmp_path: Path) -> None:
    """AC-8: Reddedilen başlatmada depo açılmaz, kilit alınmaz, ağa çıkılmaz."""
    bot = Bot(tmp_path)
    store = tmp_path / "bot.db"
    lock = tmp_path / "bot.db.lock"

    code, console = bot.run("start", trial=False)
    assert code == EXIT_REFUSED
    assert "başlatma reddedildi:" in console

    # Depo ve kilit dosyası oluşturulmaz / dokunulmaz
    assert not store.exists()
    assert not lock.exists()

    # Borsaya hiçbir çağrı gitmez
    assert bot.exchange.touched == []


# --- spec 0038 CB-1, PB-1: the paper start record --------------------------------------------


def _proven_config(tmp_path: Path) -> Path:
    report_file = tmp_path / "backtest-report.txt"
    report_file.write_text(make_valid_report_text(), encoding="utf-8")
    stage_toml = f"""
[stage]
report_path = "{report_file.as_posix()}"
report_sha256 = "{fingerprint(report_file)}"
approved_by = "Galip Badem"
approved_at = "{APPROVED_AT}"
min_trades = 10
"""
    text = config_text(tmp_path) + BACKTEST_SPREAD + stage_toml
    (tmp_path / "crytobot.toml").write_text(text, encoding="utf-8")
    return report_file


def test_a_proven_paper_start_records_its_absolute_report(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    report_file = _proven_config(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK

    assert bot.run("start", trial=False)[0] == EXIT_OK

    records = load_start_records(bot.store).records
    assert [(r.trial, r.report_path, r.revision) for r in records] == [
        (False, str(report_file.resolve()), 1)
    ]


def test_a_trial_start_records_a_trial_without_a_report(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK

    assert bot.run("start", "--trial")[0] == EXIT_OK
    assert bot.run("start", "--trial")[0] == EXIT_OK

    records = load_start_records(bot.store).records
    assert [(r.trial, r.report_path) for r in records] == [(True, None), (True, None)]
    assert records[0].at <= records[1].at


def test_a_refused_start_leaves_no_record(tmp_path: Path) -> None:
    bot = Bot(tmp_path)
    _proven_config(tmp_path)
    (tmp_path / "backtest-report.txt").unlink()
    assert bot.run("prepare")[0] == EXIT_OK

    assert bot.run("start", trial=False)[0] == EXIT_REFUSED

    assert load_start_records(bot.store).records == ()


def test_a_start_whose_record_cannot_be_written_is_refused_before_any_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plan Risk 6: kaydı olmayan koşu kanıt sayılamaz."""
    bot = Bot(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK
    failed = StoreResult(StoreOutcome.WRITE_FAILED, None, (), "yazılamadı")
    monkeypatch.setattr(start_module, "append_start_record", lambda *_args: failed)

    code, console = bot.run("start", "--trial")

    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: başlatma kaydı yazılamadı" in console
    assert event_lines(console, "tur") == []
    assert bot.exchange.touched == []


# --- spec 0040 CB-1…CB-6: the new refusals at the entry point ---------------------------------


def test_a_proven_paper_start_records_the_report_fingerprint(tmp_path: Path) -> None:
    """CB-5: kanıtlı paper kaydı onaylanan raporun parmak izini taşır; deneme kaydı taşımaz."""
    bot = Bot(tmp_path)
    report_file = _proven_config(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK

    assert bot.run("start", trial=False)[0] == EXIT_OK
    assert bot.run("start", "--trial")[0] == EXIT_OK

    records = load_start_records(bot.store).records
    assert [r.report_sha256 for r in records] == [fingerprint(report_file), None]


def _files(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in sorted(root.iterdir()) if path.is_file()}


def _break(case: str, config: Path, report: Path) -> str:
    """Bir denetimi bozar; beklenen ret metnini döndürür."""
    text = config.read_text(encoding="utf-8")
    sha_line = f'report_sha256 = "{fingerprint(report)}"\n'
    if case == "fingerprint":
        report.write_bytes(report.read_bytes() + b"\n")
        return "rapor onaylanandan farklı"
    if case == "sha_missing":
        config.write_text(text.replace(sha_line, ""), encoding="utf-8")
        return "ayar eksik: stage.report_sha256"
    if case == "sha_invalid":
        config.write_text(text.replace(sha_line, 'report_sha256 = "xyz"\n'), encoding="utf-8")
        return "ayar geçersiz: stage.report_sha256"
    if case == "before":
        early = text.replace(APPROVED_AT, "2026-11-01T11:59:59Z")  # generation: 12:00
        config.write_text(early, encoding="utf-8")
        return "onay rapordan önce"
    if case == "future":
        config.write_text(text.replace(APPROVED_AT, "2026-11-30T00:00:00Z"), encoding="utf-8")
        return "onay gelecekte"
    if case == "fact":
        kept = [row for row in report.read_text(encoding="utf-8").splitlines(keepends=True)]
        report.write_bytes("".join(r for r in kept if not r.startswith("fee:")).encode())
        config.write_text(
            text.replace(sha_line, f'report_sha256 = "{fingerprint(report)}"\n'),
            encoding="utf-8",
        )
        return "rapor eksik: fee"
    if case == "spread_missing":
        config.write_text(text.replace(BACKTEST_SPREAD, "\n"), encoding="utf-8")
        return "ayar eksik: backtest.spread"
    if case in ("strategy", "not_final"):  # spec 0042 AC-8: the approval follows the new bytes
        body = report.read_text(encoding="utf-8")
        if case == "strategy":
            body = body.replace("strateji: S0 ", "strateji: S1 ", 1)
        else:
            body = body.replace(
                "CrytoBot backtest raporu — son değerlendirme", "CrytoBot backtest raporu", 1
            )
        report.write_bytes(body.encode("utf-8"))
        config.write_text(
            text.replace(sha_line, f'report_sha256 = "{fingerprint(report)}"\n'),
            encoding="utf-8",
        )
        return (
            "ayar uyuşmazlığı: strateji" if case == "strategy" else "rapor son değerlendirme değil"
        )
    if case in ("trend_period", "candidate_interval", "candidate_k"):  # spec 0043 AC-9
        return _break_candidate(case, config, report, text, sha_line)
    assert case == "condition"
    config.write_text(text.replace('fee = "0.001"', 'fee = "0.002"'), encoding="utf-8")
    return "ayar uyuşmazlığı: fee"


def _break_candidate(case: str, config: Path, report: Path, text: str, sha_line: str) -> str:
    """Spec 0043 AC-9: çalışan aday S1 (L=150) ya da S0 (k=3); rapor S1 L=100 ya da 4h."""
    body = report.read_text(encoding="utf-8")
    if case == "trend_period":
        text = text.replace('name = "S0"\n', 'name = "S1"\ntrend_period = 150\n', 1)
        body = body.replace(" k=2 r=2\n", " k=2 r=2 trend_period=100\n").replace(
            "strateji: S0 ", "strateji: S1 ", 1
        )
        expected = "ayar uyuşmazlığı: trend_period"
    elif case == "candidate_interval":
        body = body.replace("mum aralığı: 1h", "mum aralığı: 4h", 1)
        expected = "ayar uyuşmazlığı: candle_interval"
    else:
        text = text.replace('k = "2"', 'k = "3"', 1)
        expected = "ayar uyuşmazlığı: k"
    report.write_bytes(body.encode("utf-8"))
    config.write_text(
        text.replace(sha_line, f'report_sha256 = "{fingerprint(report)}"\n'), encoding="utf-8"
    )
    return expected


@pytest.mark.parametrize(
    "case",
    [
        "fingerprint",
        "sha_missing",
        "sha_invalid",
        "before",
        "future",
        "fact",
        "spread_missing",
        "condition",
    ],
)
def test_new_refusals_write_nothing_exit_1(tmp_path: Path, case: str) -> None:
    """CB-6: her yeni ret depoya yazmadan, kilit almadan, borsaya gitmeden, tur atmadan; çıkış 1
    ve satır yalnız ilk karşılanmayan denetimi adlandırır."""
    _refused_start(tmp_path, case)


@pytest.mark.parametrize("case", ["strategy", "not_final"])
def test_strategy_mismatch_writes_nothing_exit_1(tmp_path: Path, case: str) -> None:
    """Spec 0042 AC-8: strateji adı farklı ya da rapor son değerlendirme değilse `start` reddeder;
    depo yazılmaz, istemci çağrısı yok, tur yok, çıkış 1."""
    _refused_start(tmp_path, case)


@pytest.mark.parametrize("case", ["trend_period", "candidate_interval", "candidate_k"])
def test_candidate_mismatch_writes_nothing_exit_1(tmp_path: Path, case: str) -> None:
    """Spec 0043 AC-9: adayın parametresi ya da aralığı çalışan ayardan farklıysa `start`
    reddeder; depo yazılmaz, istemci çağrısı yok, tur yok, çıkış 1."""
    _refused_start(tmp_path, case)


def _refused_start(tmp_path: Path, case: str) -> None:
    bot = Bot(tmp_path)
    report_file = _proven_config(tmp_path)
    assert bot.run("prepare")[0] == EXIT_OK
    expected = _break(case, bot.config_path, report_file)
    before = _files(tmp_path)  # store, lock, log, config and report: every byte
    bot.exchange.touched.clear()

    code, console = bot.run("start", trial=False)

    assert code == EXIT_REFUSED
    (refusal,) = event_lines(console, "başlatma")
    assert refusal.endswith(f"başlatma reddedildi: {expected}")
    assert _files(tmp_path) == before
    assert load_start_records(bot.store).records == ()
    assert event_lines(console, "tur") == []
    assert bot.exchange.touched == []
