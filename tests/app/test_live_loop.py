"""Spec 0033 AC-5, AC-6, AC-7, AC-8: Canlı mod döngüsü, bakiye mutabakatı ve güvenli mod."""

import io
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, StoreLock, run
from crytobot.app import (
    BuyHalt,
    ExitReason,
    NoticeKind,
    StopRequest,
    TurnMemory,
    TurnNotice,
    prepare_live_store,
    run_turn,
)
from crytobot.execution import (
    BannedError,
    LiveExchange,
    LiveExchangeCallError,
    OrderStatus,
)
from crytobot.persistence import load_store
from tests.app.helpers import BTC, CROSS, FLAT, NOW, make_settings, pair_market
from tests.app.loop_fakes import harness
from tests.app.test_live_start import FakeLiveClient, write_test_config


class MockLiveExchange(LiveExchange):
    def __init__(
        self,
        free_balance: Decimal = Decimal("1000.00"),
        balance_error: Exception | None = None,
        placements: dict[str, OrderStatus] | None = None,
        resolutions: dict[str, OrderStatus] | None = None,
    ) -> None:
        super().__init__(client=FakeLiveClient(free_balance=free_balance))
        self._free_balance = free_balance
        self.balance_error = balance_error
        self.placements = placements or {}
        self.resolutions = resolutions or {}
        self.placed_calls: list[dict[str, Any]] = []
        self.placed_stop_calls: list[dict[str, Any]] = []

    def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
        if self.balance_error is not None:
            raise self.balance_error
        return self._free_balance

    def place(
        self,
        client_order_id: str,
        symbol: str = "",
        side: str = "",
        amount: object = None,
    ) -> OrderStatus:
        self.placed_calls.append(
            {"id": client_order_id, "symbol": symbol, "side": side, "amount": amount}
        )
        return self.placements.get(client_order_id, OrderStatus.FILLED)

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        return self.resolutions.get(client_order_id, OrderStatus.UNKNOWN)

    def place_stop_order(
        self,
        client_order_id: str,
        symbol: str = "",
        amount: object = None,
        stop_price: object = None,
        limit_price: object = None,
    ) -> OrderStatus:
        self.placed_stop_calls.append(
            {
                "id": client_order_id,
                "symbol": symbol,
                "side": "sell",
                "amount": amount,
                "stop_price": stop_price,
            }
        )
        return self.placements.get(client_order_id, OrderStatus.NEW)

    def cancel_order(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        return self.placements.get(client_order_id, OrderStatus.CANCELED)

    def fetch_order(self, client_order_id: str, symbol: str = "") -> dict[str, Any] | None:
        return None


def test_balance_reconciliation_tolerance_and_halt(tmp_path: Path, monkeypatch: Any) -> None:
    """Spec 0033 AC-5 (R-6): Bakiye mutabakatı toleransı (<=0.05 USDT) ve RECONCILIATION_HALT."""
    store_path = str(tmp_path / "live_recon.db")
    # Defter açılış bakiyesi: 1000.00 USDT
    prepare_live_store(store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    notices: list[TurnNotice] = []
    memory = TurnMemory()
    settings = make_settings()
    market_flat = {BTC: pair_market(closes=FLAT)}
    market_cross = {BTC: pair_market(closes=CROSS)}

    # 1. Fark <= 0.05 USDT (örneğin borsa 1000.04): mutabakat geçerli, alım durmaz
    ex_ok = MockLiveExchange(free_balance=Decimal("1000.04"))
    res_ok = run_turn(
        market=market_flat,
        settings=settings,
        store_path=store_path,
        now=NOW,
        exchange=ex_ok,
        sink=notices.append,
        memory=memory,
    )
    assert BuyHalt.RECONCILIATION_HALT not in res_ok.halts
    assert BuyHalt.BALANCE_CHECK_FAILED not in res_ok.halts

    # 2. Fark > 0.05 USDT (örneğin borsa 1000.10): RECONCILIATION_HALT devrede, alım durur
    ex_halt = MockLiveExchange(free_balance=Decimal("1000.10"))
    res_halt = run_turn(
        market=market_cross,
        settings=settings,
        store_path=store_path,
        now=NOW,
        exchange=ex_halt,
        sink=notices.append,
        memory=memory,
    )
    assert BuyHalt.RECONCILIATION_HALT in res_halt.halts
    assert any(n.kind is NoticeKind.RECONCILIATION and n.entering for n in notices)
    # Yeni alım açılmamalı
    assert len(res_halt.buys) == 0

    # 3. Bakiye sorgusu ağ hatası / LiveExchangeCallError verirse: BALANCE_CHECK_FAILED
    ex_err = MockLiveExchange(
        balance_error=LiveExchangeCallError("Network timeout", is_unknown=True)
    )
    res_err = run_turn(
        market=market_flat,
        settings=settings,
        store_path=store_path,
        now=NOW,
        exchange=ex_err,
        sink=notices.append,
        memory=memory,
    )
    assert BuyHalt.BALANCE_CHECK_FAILED in res_err.halts

    # 4. Borsa bakiye mutabakatı engeli devredeyken açık pozisyonların kapanışı sürer (R-8)
    # Açık pozisyon bulunan bir market durumu: hedef fiyat aşıldığında close emri iletilir
    # Önce bir pozisyon açalım (tolerans içi bakiye ile)
    ex_buy = MockLiveExchange(free_balance=Decimal("1000.00"))
    res_buy = run_turn(
        market=market_cross,
        settings=settings,
        store_path=store_path,
        now=NOW,
        exchange=ex_buy,
        sink=notices.append,
        memory=memory,
    )
    assert len(res_buy.buys) == 1
    loaded_state = load_store(store_path, "live").state
    assert loaded_state is not None
    assert len(loaded_state.ledger.positions) > 0

    # Şimdi borsa bakiyesi tolerans dışı (1000.50), fakat fiyat hedefe (15 USDT) ulaştı
    market_exit = {BTC: pair_market(price=Decimal(15), closed_at=NOW + timedelta(hours=1))}
    ex_close = MockLiveExchange(free_balance=Decimal("1000.50"))
    res_close = run_turn(
        market=market_exit,
        settings=settings,
        store_path=store_path,
        now=NOW + timedelta(hours=1),
        exchange=ex_close,
        sink=notices.append,
        memory=memory,
    )
    # Alım durdurulmuştur
    assert BuyHalt.RECONCILIATION_HALT in res_close.halts
    # Fakat kapanış emri gönderilmiştir ve pozisyon kapatılmıştır (R-8)
    assert len(res_close.closes) > 0
    assert len(res_close.closures) > 0

    # 5. Sonraki turda borsa bakiyesi normale döndüğünde settle() bildirimi temizler (F-1)
    notices.clear()
    state_after_close = load_store(store_path, "live").state
    assert state_after_close is not None
    cur_bal = state_after_close.ledger.balance
    assert cur_bal is not None
    market_fresh = {
        BTC: pair_market(closes=FLAT, closed_at=NOW + timedelta(hours=2), price=Decimal(10))
    }
    res_recovered = run_turn(
        market=market_fresh,
        settings=settings,
        store_path=store_path,
        now=NOW + timedelta(hours=2),
        exchange=MockLiveExchange(free_balance=cur_bal),
        sink=notices.append,
        memory=memory,
    )
    assert BuyHalt.RECONCILIATION_HALT not in res_recovered.halts
    assert any(n.kind is NoticeKind.RECONCILIATION and not n.entering for n in notices)

    # 6. Depo kalıcı flagged durumdayken borsa bakiyesi tutsa bile bildirim silinmez (F-1)
    original_load = load_store(store_path, "live")
    flagged_loaded = replace(original_load, conflicts=("fill conflict",))
    monkeypatch.setattr(
        "crytobot.app._turn.load_store",
        lambda sp, mode: flagged_loaded,
    )
    notices.clear()
    mem_flagged = TurnMemory()
    market_fresh_3 = {
        BTC: pair_market(closes=FLAT, closed_at=NOW + timedelta(hours=3), price=Decimal(10))
    }
    res_flagged = run_turn(
        market=market_fresh_3,
        settings=settings,
        store_path=store_path,
        now=NOW + timedelta(hours=3),
        exchange=MockLiveExchange(free_balance=cur_bal),
        sink=notices.append,
        memory=mem_flagged,
    )
    assert BuyHalt.RECONCILIATION in res_flagged.halts
    assert (NoticeKind.RECONCILIATION, "") in mem_flagged.active


def test_live_turn_orders_and_safe_mode(tmp_path: Path) -> None:
    """Spec 0033 AC-6 (R-7, R-8): Canlı emir iletimi, mod=LIVE, ret ve UNKNOWN güvenli mod."""
    store_path = str(tmp_path / "live_orders.db")
    prepare_live_store(store_path, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    notices: list[TurnNotice] = []
    memory = TurnMemory()
    settings = make_settings()
    market = {BTC: pair_market()}

    # 1. FILLED durumu: emir borsaya iletilir ve dolum deftere yazılır
    ex_filled = MockLiveExchange(free_balance=Decimal("1000.00"))
    res_filled = run_turn(
        market=market,
        settings=settings,
        store_path=store_path,
        now=NOW,
        exchange=ex_filled,
        sink=notices.append,
        memory=memory,
    )
    assert len(res_filled.buys) == 1
    assert res_filled.buys[0].status is OrderStatus.FILLED
    # Borsa çağrısının yapıldığını doğrula
    assert len(ex_filled.placed_calls) == 1

    # 2. REJECTED durumu: borsa reddederse deftere yazılmaz
    store_rej = str(tmp_path / "live_rej.db")
    prepare_live_store(store_rej, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    # İlk emri reject edecek exchange
    class RejectAllExchange(MockLiveExchange):
        def place(
            self,
            client_order_id: str,
            symbol: str = "",
            side: str = "",
            amount: object = None,
        ) -> OrderStatus:
            return OrderStatus.REJECTED

    ex_rej = RejectAllExchange(free_balance=Decimal("1000.00"))
    res_rej = run_turn(
        market=market,
        settings=settings,
        store_path=store_rej,
        now=NOW,
        exchange=ex_rej,
        sink=notices.append,
        memory=TurnMemory(),
    )
    assert len(res_rej.buys) == 1
    assert res_rej.buys[0].status is OrderStatus.REJECTED
    loaded_rej = load_store(store_rej, "live").state
    assert loaded_rej is not None
    # Defter bakiyesi değişmedi
    assert loaded_rej.ledger.balance == Decimal("1000.00")
    assert len(loaded_rej.ledger.positions) == 0

    # 3. UNKNOWN durumu: borsa çağrısı belirsiz kalırsa UNKNOWN_ORDERS güvenli modu
    store_unk = str(tmp_path / "live_unk.db")
    prepare_live_store(store_unk, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    class UnknownExchange(MockLiveExchange):
        def place(
            self,
            client_order_id: str,
            symbol: str = "",
            side: str = "",
            amount: object = None,
        ) -> OrderStatus:
            return OrderStatus.UNKNOWN

    ex_unk = UnknownExchange(free_balance=Decimal("1000.00"))
    mem_unk = TurnMemory()
    res_unk = run_turn(
        market=market,
        settings=settings,
        store_path=store_unk,
        now=NOW,
        exchange=ex_unk,
        sink=notices.append,
        memory=mem_unk,
    )
    assert len(res_unk.buys) == 1
    unk_id = res_unk.buys[0].client_order_id
    assert res_unk.buys[0].status is OrderStatus.UNKNOWN
    loaded_unk = load_store(store_unk, "live").state
    assert loaded_unk is not None
    assert unk_id in loaded_unk.execution.unknown

    # Sonraki turda güvenli mod devrededir ve resolve_unknown emri sorgular
    ex_unk.resolutions[unk_id] = OrderStatus.FILLED
    run_turn(
        market=market,
        settings=settings,
        store_path=store_unk,
        now=NOW + timedelta(hours=1),
        exchange=ex_unk,
        sink=notices.append,
        memory=mem_unk,
    )
    # UNKNOWN emir çözülmüş olmalı
    loaded_resolved = load_store(store_unk, "live").state
    assert loaded_resolved is not None
    assert unk_id not in loaded_resolved.execution.unknown
    assert len(loaded_resolved.ledger.positions) > 0


def test_live_rate_limit_and_banned_handling(tmp_path: Path) -> None:
    """Spec 0033 AC-7 (R-9): Borsa rate limit (429) ve 418 ban (fail-closed çıkış)."""
    store_file = tmp_path / "bot.db"
    fake = FakeLiveClient(free_balance=Decimal("1000.00"))
    prepare_live_store(str(store_file), NOW, live_client=fake)

    # 1. 418 BannedError durumunda fail-closed çıkış (ExitReason.BANNED)
    class BannedExchange(MockLiveExchange):
        def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
            raise BannedError("IP banned HTTP 418")

    bot_banned = harness(store_file, stop_after=1)
    bot_banned.config = replace(bot_banned.config, mode="live")
    exit_banned = bot_banned.run(exchange=BannedExchange())  # type: ignore[arg-type]
    assert exit_banned.reason is ExitReason.BANNED
    assert any("418" in line or "banı" in line for line in bot_banned.lines)

    # 2. 429 Rate limit Retry-After beklemesi
    class RateLimitedExchange(MockLiveExchange):
        def __init__(self) -> None:
            super().__init__()
            self.first = True

        def fetch_free_balance(self, asset: str = "USDT") -> Decimal:
            if self.first:
                self.first = False
                raise LiveExchangeCallError("429 rate limit", retry_after=3.5, is_unknown=True)
            return Decimal("1000.00")

    bot_rate = harness(store_file, stop_after=1)
    bot_rate.config = replace(bot_rate.config, mode="live")
    ex_rate = RateLimitedExchange()
    exit_rate = bot_rate.run(exchange=ex_rate)  # type: ignore[arg-type]
    assert exit_rate.turns == 1
    assert 3.5 in bot_rate.waits
    assert any("429" in line and "3.5" in line for line in bot_rate.lines)


def test_live_clean_stop_and_process_lock(tmp_path: Path) -> None:
    """Spec 0033 AC-8 (R-10): Canlı temiz durdurma, süreç kilidi ve çift çalıştırma engeli."""
    cfg = write_test_config(tmp_path, mode="live")
    store_file = (tmp_path / "bot.db").as_posix()
    prepare_live_store(store_file, NOW, live_client=FakeLiveClient(free_balance=Decimal("1000.00")))

    # 1. Temiz durma (SIGINT / StopRequest): exit code 0 ve kilit temiz bırakılır
    stop_req = StopRequest()
    stop_req.request("sigint")
    out = io.StringIO()
    res = run(
        ["start", "--live"],
        config_path=cfg,
        console=out,
        live_client=FakeLiveClient(free_balance=Decimal("1000.00")),
        stop=stop_req,
    )
    assert res == EXIT_OK
    assert "durdurma" in out.getvalue()

    # Kilit bırakılmış olmalı: yeni bir süreç kilidi alabilmeli
    lock = StoreLock(store_file)
    assert lock.acquire() is None
    lock.release()

    # 2. İkinci süreç kilitliyken başlatma reddi: STORE_BUSY / reddedildi
    lock_busy = StoreLock(store_file)
    assert lock_busy.acquire() is None
    try:
        out_busy = io.StringIO()
        res_busy = run(
            ["start", "--live"],
            config_path=cfg,
            console=out_busy,
            live_client=FakeLiveClient(free_balance=Decimal("1000.00")),
        )
        assert res_busy == EXIT_REFUSED
        assert "reddedildi: depo başka bir bot sürecinde kullanılıyor" in out_busy.getvalue()
    finally:
        lock_busy.release()
