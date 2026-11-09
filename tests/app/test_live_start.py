"""Spec 0033 AC-1, AC-2, AC-4: Canlı mod başlatma, çift kilit, hazırlık ve güvenlik kapıları."""

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, run
from crytobot.app import (
    PrepareOutcome,
    StartOutcome,
    create_live_exchange,
    open_for_start,
    prepare_live_store,
    prepare_store,
)
from crytobot.execution import (
    CREDENTIALS_MISSING,
    SPOT_TRADING_DISABLED,
    WITHDRAWAL_PERMISSION_FORBIDDEN,
    BinanceLiveClient,
    PermissionCheckFailedError,
    PermissionForbiddenError,
)
from crytobot.persistence import load_store

NOW = datetime(2026, 11, 9, 20, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "crytobot.example.toml"

SAMPLE_REPORT_TEXT = """== örneklem dışı — BR-10 kanıtı adayı ==
turlar: 2 (ilk 2026-01-02T00:00:00+00:00, son 2026-01-02T01:00:00+00:00)
başlangıç kasası: 999.90000000 USDT
bitiş kasası: 1009.79000000 USDT
net kâr/zarar: 9.89000000 USDT (getiri %0.9891)
gerçekleşen kâr/zarar: 9.79000000 USDT
gerçekleşmemiş kâr/zarar: 0.10000000 USDT
işlem: 1 (kazanan 1, zararlı 0)
kazanma oranı: %100.0000
kâr faktörü: tanımsız
en büyük drawdown: %0.0109
ortalama günlük getiri: %0.9891
ödenen komisyon: 0.11000000 USDT
ödenen slippage: 0.11000000 USDT
günlük zarar durdurmalı gün: 0
drawdown durdurması: yok
fiyatı ya da verisi eksik tur (çift başına): BTC/USDT 0
öneri yok (nedene göre): yok
ret (nedene göre): yok
gönderilmeyen durum bildirimi (türe göre): yok
"""


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


def write_test_config(
    dir_path: Path,
    mode: str = "paper",
    testnet: bool = False,
    include_live_stage: bool = True,
) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    cfg_file = dir_path / "crytobot.toml"
    store_file = (dir_path / "bot.db").as_posix()
    log_file = (dir_path / "bot.log").as_posix()
    report_file = dir_path / "report.txt"
    report_file.write_text(SAMPLE_REPORT_TEXT, encoding="utf-8")

    stage_lines = [
        "[stage]",
        f'report_path = "{(report_file).as_posix()}"',
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
