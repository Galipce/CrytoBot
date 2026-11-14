"""Spec 0033 AC-1, AC-2, AC-4: Canlı mod başlatma, çift kilit, hazırlık ve güvenlik kapıları."""

import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, run
from crytobot.app import (
    PrepareOutcome,
    StartOutcome,
    StopRequest,
    create_live_exchange,
    open_for_start,
    prepare_live_store,
    prepare_store,
)
from crytobot.execution import (
    CREDENTIALS_MISSING,
    SPOT_TRADING_DISABLED,
    WITHDRAWAL_PERMISSION_FORBIDDEN,
    AssetBalance,
    BinanceLiveClient,
    PermissionCheckFailedError,
    PermissionForbiddenError,
)
from crytobot.persistence import load_store
from tests.app.test_paper_proof import proof_store

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "crytobot.example.toml"

# spec 0042 (plan Risk 8): the gate reads only a final evaluation report naming its strategy
SAMPLE_REPORT_TEXT = """CrytoBot backtest raporu — son değerlendirme
dönem: 2026-01-01T00:00:00+00:00 .. 2026-01-03T00:00:00+00:00
mum aralığı: 1h
tur aralığı: 1h
ayrım anı: 2026-01-02T00:00:00+00:00
çiftler: BTC/USDT, ETH/USDT
indirme anı: 2026-02-01T12:30:00+00:00
ısınma mumu (candle_count): 200
spread: 0.0005
strateji: S0 fast=12 slow=26 rsi=14 rsi_threshold=70 atr=14 k=2 r=2
üretim anı: 2026-11-09T10:00:00+00:00
fee: 0.001
slippage: 0.001
per_trade_risk: 0.01
daily_loss_limit: 0.03
max_drawdown: 0.15
max_open_positions: 5
profit_cost_multiple: 2
opening_balance: 10000
sınanan kombinasyon: 1
paper adayı: S0 1h

== örneklem dışı — BR-10 kanıtı adayı ==
net kâr/zarar: 9.89000000 USDT (getiri %0.9891)
işlem: 1 (kazanan 1, zararlı 0)
kâr faktörü: tanımsız
en büyük drawdown: %0.0109

== tüm koşu ==
"""


# spec 0037 Amendment A-1: plenty of every coin; R-5 ignores a surplus, so no shortfall appears
PLENTY = AssetBalance(Decimal(10**9), Decimal(10**9))


class PlentyOfCoins(dict[str, AssetBalance]):
    """Bakiye yanıtı: listelenmeyen her coinden bol."""

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, PLENTY)


class FakeLiveClient(BinanceLiveClient):
    def __init__(
        self,
        free_balance: Decimal = Decimal("1500.50"),
        permissions_error: Exception | None = None,
        balance_error: Exception | None = None,
    ) -> None:
        self.free_balance = free_balance
        self.permissions_error = permissions_error
        self.balance_error = balance_error
        self.permissions_checked = False

    def verify_permissions(self) -> None:
        self.permissions_checked = True
        if self.permissions_error is not None:
            raise self.permissions_error

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        if self.balance_error is not None:
            raise self.balance_error
        return self.free_balance

    def fetch_balances(self) -> dict[str, AssetBalance]:
        """Spec 0037 Amendment A-1: coin mutabakatının sorgusu; USDT ve her coinden bol."""
        if self.balance_error is not None:
            raise self.balance_error
        return PlentyOfCoins(USDT=AssetBalance(self.free_balance, self.free_balance))

    def place_stop_order(
        self,
        symbol: str,
        side: str,
        amount: str,
        stop_price: str,
        client_order_id: str,
        limit_price: str | None = None,
    ) -> dict[str, Any]:
        return {"status": "open", "id": client_order_id}

    def cancel_order(self, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        return {"status": "canceled", "id": client_order_id}

    def query_order(self, client_order_id: str, symbol: str) -> dict[str, Any] | None:
        return None


def write_test_config(
    dir_path: Path,
    mode: str = "paper",
    testnet: bool = False,
    include_live_stage: bool = True,
    include_paper_store: bool = True,
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    cfg_file = dir_path / "crytobot.toml"
    store_file = (dir_path / "bot.db").as_posix()
    log_file = (dir_path / "bot.log").as_posix()
    report_file = dir_path / "report.txt"
    report_file.write_bytes(SAMPLE_REPORT_TEXT.encode("utf-8"))
    sha = hashlib.sha256(report_file.read_bytes()).hexdigest()  # spec 0040 CB-1

    stage_lines = [
        "[stage]",
        f'report_path = "{(report_file).as_posix()}"',
        f'report_sha256 = "{sha}"',
        'approved_by = "Galip Badem"',
        'approved_at = "2026-11-09T12:00:00Z"',
        "min_trades = 1",
    ]
    if include_live_stage:
        stage_lines.extend(
            [
                'live_approved_by = "Galip Badem"',
                'live_approved_at = "2026-11-09T20:00:00Z"',
            ]
        )
        # spec 0038 CB-2: a live start needs a proven paper store, finished before the approval
        paper_file = dir_path / "paper.sqlite"
        if include_paper_store:
            if mode == "live" and not paper_file.exists():
                proof_store(paper_file, report=str(report_file), sha=sha)
            stage_lines.append(f'paper_store_path = "{paper_file.as_posix()}"')

    content = f"""
[bot]
store_path = "{store_file}"
log_path = "{log_file}"
turn_interval = "1h"
opening_balance = "10000"
mode = "{mode}"

[market]
exchange = "binance"
candle_interval = "1h"
candle_count = 200
call_timeout = 10
read_budget = 60

[turn]
whitelist = ["BTC/USDT", "ETH/USDT"]
fee = "0.001"
slippage = "0.001"
max_candle_age = 900
max_price_age = 120

[risk]
per_trade_risk = "0.01"
daily_loss_limit = "0.03"
max_drawdown = "0.15"
max_open_positions = 5
profit_cost_multiple = "2"

[strategy]
fast_period = 12
slow_period = 26
rsi_period = 14
rsi_threshold = "70"
atr_period = 14
k = "2"
r = "2"

[backtest]
spread = "0.0005"

{chr(10).join(stage_lines)}

[exchange]
testnet = {"true" if testnet else "false"}
"""
    cfg_file.write_text(content, encoding="utf-8")
    return cfg_file


def test_dual_lock_mode_mismatch_and_live_flag_required(tmp_path: Path) -> None:
    """Spec 0033 AC-1 (R-1, R-3): Çift kilit ve depo mod uyuşmazlığı denetimleri."""
    # 1. Config mode = "paper" iken CLI --live bayrağı -> MODE_MISMATCH
    cfg_paper = write_test_config(tmp_path / "c1", mode="paper")
    out_start = io.StringIO()
    res_start = run(["start", "--live"], config_path=cfg_paper, console=out_start)
    assert res_start == EXIT_REFUSED
    assert "MODE_MISMATCH" in out_start.getvalue()

    out_prep = io.StringIO()
    res_prep = run(["prepare", "--live"], config_path=cfg_paper, console=out_prep)
    assert res_prep == EXIT_REFUSED
    assert "MODE_MISMATCH" in out_prep.getvalue()

    # 2. Config mode = "live" iken CLI bayraksız start / prepare -> LIVE_FLAG_REQUIRED
    cfg_live = write_test_config(tmp_path / "c2", mode="live")
    out_start_noflag = io.StringIO()
    res_start_noflag = run(["start"], config_path=cfg_live, console=out_start_noflag)
    assert res_start_noflag == EXIT_REFUSED
    assert "LIVE_FLAG_REQUIRED" in out_start_noflag.getvalue()

    out_prep_noflag = io.StringIO()
    res_prep_noflag = run(["prepare"], config_path=cfg_live, console=out_prep_noflag)
    assert res_prep_noflag == EXIT_REFUSED
    assert "LIVE_FLAG_REQUIRED" in out_prep_noflag.getvalue()

    # 3. open_for_start mod kontrolü (R-3)
    # (a) Paper modda oluşturulmuş depoyu live modda başlatma girişimi -> MODE_MISMATCH
    store_p = str(tmp_path / "paper.db")
    prepare_store(store_p, Decimal("10000"), NOW)
    check_live_on_paper = open_for_start(store_p, mode="live")
    assert check_live_on_paper.outcome is StartOutcome.MODE_MISMATCH
    assert "MODE_MISMATCH" in check_live_on_paper.message

    # (b) Live modda oluşturulmuş depoyu paper modda başlatma girişimi -> MODE_MISMATCH
    store_l = str(tmp_path / "live.db")
    fake = FakeLiveClient(free_balance=Decimal("5000"))
    prepare_live_store(store_l, NOW, live_client=fake)
    check_paper_on_live = open_for_start(store_l, mode="paper")
    assert check_paper_on_live.outcome is StartOutcome.MODE_MISMATCH
    assert "MODE_MISMATCH" in check_paper_on_live.message

    # (c) Defter açılmamış depoda ipucu mod uyumu (F-3)
    from crytobot.persistence import create_store

    store_unopened_live = str(tmp_path / "unopened_live.db")
    create_store(store_unopened_live, "live")
    check_unopened_live = open_for_start(store_unopened_live, mode="live")
    assert check_unopened_live.outcome is StartOutcome.LEDGER_NOT_OPENED
    assert "prepare --live" in str(check_unopened_live.hint)

    store_unopened_paper = str(tmp_path / "unopened_paper.db")
    create_store(store_unopened_paper, "paper")
    check_unopened_paper = open_for_start(store_unopened_paper, mode="paper")
    assert check_unopened_paper.outcome is StartOutcome.LEDGER_NOT_OPENED
    assert check_unopened_paper.hint is None


def test_prepare_live_creates_store_with_exchange_balance(tmp_path: Path) -> None:
    """Spec 0033 AC-2 (R-2): Canlı depo hazırlığı borsadan serbest bakiye çeker ve defteri açar."""
    store_path = str(tmp_path / "live_prep.db")
    fake_client = FakeLiveClient(free_balance=Decimal("2450.75"))

    # 1. Başarılı hazırlık
    res = prepare_live_store(store_path, NOW, live_client=fake_client)
    assert res.outcome is PrepareOutcome.PREPARED
    assert "2450.75" in res.message
    assert fake_client.permissions_checked is True

    # Depo içeriğini doğrula
    loaded = load_store(store_path, "live")
    assert loaded.state is not None
    assert loaded.state.mode == "live"
    assert loaded.state.ledger.balance == Decimal("2450.75")

    # 2. Zaten var olan depoya tekrar prepare çalıştırılamaz
    res_dup = prepare_live_store(store_path, NOW, live_client=fake_client)
    assert res_dup.outcome is PrepareOutcome.STORE_EXISTS

    # 3. Pozitif olmayan bakiye reddedilir (defter açılmaz)
    store_zero = str(tmp_path / "live_zero.db")
    fake_zero = FakeLiveClient(free_balance=Decimal("0"))
    res_zero = prepare_live_store(store_zero, NOW, live_client=fake_zero)
    assert res_zero.outcome is PrepareOutcome.INVALID_BALANCE
    assert not Path(store_zero).exists()

    # 4. CLI python -m crytobot prepare --live akışı
    cfg = write_test_config(tmp_path / "cli_prep", mode="live")
    out = io.StringIO()
    cli_res = run(
        ["prepare", "--live"],
        config_path=cfg,
        console=out,
        live_client=FakeLiveClient(free_balance=Decimal("3000")),
    )
    assert cli_res == EXIT_OK
    assert "canlı depo hazır" in out.getvalue()
    assert "3000" in out.getvalue()


def test_prepare_live_is_not_subject_to_the_paper_proof_gate(tmp_path: Path) -> None:
    """Spec 0038 PB-3: `prepare --live` paper kanıtı aramaz; deposu ve alanı yokken de hazırlar."""
    cfg = write_test_config(tmp_path / "no_paper", mode="live", include_paper_store=False)
    assert "paper_store_path" not in cfg.read_text(encoding="utf-8")
    assert not (tmp_path / "no_paper" / "paper.sqlite").exists()

    out = io.StringIO()
    res = run(
        ["prepare", "--live"],
        config_path=cfg,
        console=out,
        live_client=FakeLiveClient(free_balance=Decimal("3000")),
    )

    assert res == EXIT_OK
    assert "canlı depo hazır" in out.getvalue()
    assert load_store(str(tmp_path / "no_paper" / "bot.db"), "live").state is not None


def test_live_start_fails_closed_on_credentials_or_permissions(tmp_path: Path) -> None:
    """Spec 0033 AC-4 (R-5): Kimlik eksikliği veya yetki ihlalinde fail-closed durma."""
    # 1. Ortamda API anahtarları eksikse
    exch, err = create_live_exchange(testnet=False, env={})
    assert exch is None
    assert CREDENTIALS_MISSING in str(err)

    # 2. API anahtarında para çekme (withdrawal) yetkisi açıksa -> fail-closed
    fake_withdraw = FakeLiveClient(
        permissions_error=PermissionForbiddenError(
            WITHDRAWAL_PERMISSION_FORBIDDEN, code=WITHDRAWAL_PERMISSION_FORBIDDEN
        )
    )
    exch_w, err_w = create_live_exchange(client=fake_withdraw)
    assert exch_w is None
    assert WITHDRAWAL_PERMISSION_FORBIDDEN in str(err_w)

    # 3. Spot işlem yetkisi kapalıysa -> fail-closed
    fake_no_spot = FakeLiveClient(
        permissions_error=PermissionForbiddenError(
            SPOT_TRADING_DISABLED, code=SPOT_TRADING_DISABLED
        )
    )
    exch_ns, err_ns = create_live_exchange(client=fake_no_spot)
    assert exch_ns is None
    assert SPOT_TRADING_DISABLED in str(err_ns)

    # 4. Yetki sorgusu ağ hatası verirse -> fail-closed
    fake_net_err = FakeLiveClient(permissions_error=PermissionCheckFailedError("Network timeout"))
    exch_ne, err_ne = create_live_exchange(client=fake_net_err)
    assert exch_ne is None
    assert "Network timeout" in str(err_ne)

    # 5. CLI start --live sırasında withdrawal yetkisi varsa durur (EXIT_REFUSED)
    cfg_dir = tmp_path / "cli_perm"
    cfg = write_test_config(cfg_dir, mode="live")
    # Depoyu önce live olarak hazırla
    store_file = (cfg_dir / "bot.db").as_posix()
    prepare_live_store(store_file, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000")))

    out_w = io.StringIO()
    res_w = run(
        ["start", "--live"],
        config_path=cfg,
        console=out_w,
        live_client=fake_withdraw,
    )
    assert res_w == EXIT_REFUSED
    assert WITHDRAWAL_PERMISSION_FORBIDDEN in out_w.getvalue()

    # 6. Testnet modu bildirimi
    cfg_testnet = write_test_config(tmp_path / "cli_testnet", mode="live", testnet=True)
    store_tn = (tmp_path / "cli_testnet" / "bot.db").as_posix()
    prepare_live_store(store_tn, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000")))

    out_tn = io.StringIO()
    # Canlı başlatmayı başarılı kuruyoruz; hemen durdurmak için StopRequest
    from crytobot.app import StopRequest

    stop_req = StopRequest()
    stop_req.request("test")
    res_tn = run(
        ["start", "--live"],
        config_path=cfg_testnet,
        console=out_tn,
        live_client=FakeLiveClient(free_balance=Decimal("1000")),
        stop=stop_req,
    )
    assert res_tn == EXIT_OK
    assert "Testnet" in out_tn.getvalue()


# --- spec 0040 CB-5, CB-6: the new refusals before any exchange call ---------------------------


class CallSpy(FakeLiveClient):
    """Her genel çağrıyı yazar: kapı reddinde liste boş kalmalı."""

    def __init__(self) -> None:
        super().__init__(free_balance=Decimal(1000))
        self.calls: list[str] = []

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        if callable(value) and not name.startswith("_"):
            object.__getattribute__(self, "calls").append(name)
        return value


def _refused_live(root: Path, case: str, *, testnet: bool) -> str:
    cfg = write_test_config(root, mode="live", testnet=testnet)
    prepare_live_store(
        (root / "bot.db").as_posix(), NOW, live_client=FakeLiveClient(free_balance=Decimal(1000))
    )
    report = root / "report.txt"
    if case == "fingerprint":
        report.write_bytes(report.read_bytes() + b"\n")
    elif case == "condition":
        text = cfg.read_text(encoding="utf-8").replace('slippage = "0.001"', 'slippage = "0.002"')
        cfg.write_text(text, encoding="utf-8")
    elif case == "spread":
        text = cfg.read_text(encoding="utf-8").replace('spread = "0.0005"', 'spread = "yarım"')
        cfg.write_text(text, encoding="utf-8")
    elif case in ("not_final", "strategy"):  # spec 0042 AC-8; the approval follows the new bytes
        body = report.read_text(encoding="utf-8")
        if case == "not_final":
            body = body.replace(" — son değerlendirme", "", 1)
        else:
            body = body.replace("strateji: S0 ", "strateji: S1 ", 1)
        old_sha = hashlib.sha256(report.read_bytes()).hexdigest()
        report.write_bytes(body.encode("utf-8"))
        new_sha = hashlib.sha256(report.read_bytes()).hexdigest()
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(old_sha, new_sha), encoding="utf-8")
    elif case in ("candidate_k", "candidate_interval"):  # spec 0043 AC-9: the running config
        text = cfg.read_text(encoding="utf-8")
        if case == "candidate_k":
            text = text.replace('k = "2"', 'k = "3"', 1)
        else:
            text = text.replace('candle_interval = "1h"', 'candle_interval = "4h"', 1)
            text = text.replace('turn_interval = "1h"', 'turn_interval = "4h"', 1)
        cfg.write_text(text, encoding="utf-8")
    elif case in ("whitelist_missing", "whitelist_different"):  # spec 0044 AC-3 (R-4)
        pairs = '["BTC/USDT"]' if case == "whitelist_missing" else '["BTC/USDT", "SOL/USDT"]'
        text = cfg.read_text(encoding="utf-8")
        text = text.replace('whitelist = ["BTC/USDT", "ETH/USDT"]', f"whitelist = {pairs}", 1)
        cfg.write_text(text, encoding="utf-8")
    else:  # the paper proof was run with another report of the same path
        assert case == "proof"
        paper = root / "paper.sqlite"
        paper.unlink()
        proof_store(paper, report=str(report), sha="f" * 64)
    before = {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.is_file()}
    client = CallSpy()
    stop = StopRequest()
    stop.request("test")  # should the gate wrongly pass, the loop ends at once
    out = io.StringIO()
    code = run(["start", "--live"], config_path=cfg, console=out, live_client=client, stop=stop)
    assert code == EXIT_REFUSED
    assert client.calls == []
    assert {p.name: p.read_bytes() for p in sorted(root.iterdir()) if p.is_file()} == before
    (refusal,) = out.getvalue().splitlines()
    return refusal


@pytest.mark.parametrize("testnet", [False, True])
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("fingerprint", "rapor onaylanandan farklı"),
        ("condition", "ayar uyuşmazlığı: slippage"),
        ("spread", "ayar geçersiz: backtest.spread"),
        ("proof", "paper kanıtı: rapor uyuşmazlığı"),
    ],
)
def test_live_and_testnet_refusal_no_exchange_call(
    tmp_path: Path, case: str, message: str, testnet: bool
) -> None:
    """CB-6: canlıda ve testnet'te yeni retler depoya yazmaz, borsaya gitmez, tur atmaz; çıkış 1."""
    refusal = _refused_live(tmp_path, case, testnet=testnet)
    assert refusal.endswith(f"başlatma reddedildi: {message}")


@pytest.mark.parametrize("testnet", [False, True])
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("not_final", "rapor son değerlendirme değil"),
        ("strategy", "ayar uyuşmazlığı: strateji"),
    ],
)
def test_live_non_final_report_no_exchange_call(
    tmp_path: Path, case: str, message: str, testnet: bool
) -> None:
    """Spec 0042 AC-8: `start --live` (ve testnet) son değerlendirme olmayan ya da başka stratejili
    raporla reddeder; depo yazılmaz, borsaya istek yok, çıkış 1."""
    refusal = _refused_live(tmp_path, case, testnet=testnet)
    assert refusal.endswith(f"başlatma reddedildi: {message}")


@pytest.mark.parametrize("testnet", [False, True])
@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("candidate_k", "ayar uyuşmazlığı: k"),
        ("candidate_interval", "ayar uyuşmazlığı: candle_interval"),
    ],
)
def test_live_candidate_mismatch_no_exchange_call(
    tmp_path: Path, case: str, message: str, testnet: bool
) -> None:
    """Spec 0043 AC-9: `start --live` (ve testnet) adayın parametresi ya da aralığı çalışan ayardan
    farklıysa reddeder; depo yazılmaz, borsaya istek yok, çıkış 1."""
    refusal = _refused_live(tmp_path, case, testnet=testnet)
    assert refusal.endswith(f"başlatma reddedildi: {message}")


@pytest.mark.parametrize("testnet", [False, True])
@pytest.mark.parametrize("case", ["whitelist_missing", "whitelist_different"])
def test_live_whitelist_mismatch_no_exchange_call(tmp_path: Path, case: str, testnet: bool) -> None:
    """Spec 0044 AC-3 (R-4, korunan davranış): rapordaki çift listesi çalışan beyaz listeden
    eksik ya da farklıysa `start --live` (ve testnet) reddeder; borsaya istek yok, çıkış 1."""
    refusal = _refused_live(tmp_path, case, testnet=testnet)
    assert refusal.endswith("başlatma reddedildi: ayar uyuşmazlığı: whitelist")
