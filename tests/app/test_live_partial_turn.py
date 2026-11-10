"""Spec 0037 AC-1…AC-4 (uygulama yarısı): canlı turda kısmi alım, asgari altı kısmi alım, kısmi
kapanış ve kalan pozisyonun yeniden korunması, üçüncü varlıktan (BNB) komisyon."""

from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from crytobot.app import BuyHalt, NoticeKind, TurnMemory, TurnNotice
from crytobot.execution import OrderStatus, stop_client_id
from crytobot.risk import PairRules
from tests.app.helpers import BTC, CROSS, ETH, FIRST_AMOUNT, FLAT, pair_market
from tests.app.test_live_fills_turn import (
    BUY_MARKET,
    DEPOSIT,
    T1,
    T2,
    Replier,
    Venue,
    ended,
    fill,
    ledger_balance,
    live_store,
    stored,
    target_market,
    turn,
)

T3 = T2 + (T2 - T1)


def partial_buy(filled: Decimal, fee: str = "0.4") -> Replier:
    return lambda cid, amount: ended(cid, filled, "10.01", fee)


def test_partial_buy_records_net_and_places_stop(tmp_path: Path) -> None:
    """AC-1 (R-1): alımın 40'ı dolup kalanı sona erer: pozisyon 40'tır, borsa stopu 40 ile verilir,
    çift ve emir kimliğiyle bir kez "kısmen doldu" bildirimi gider; güvenli mod yoktur."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    venue = Venue(buy=partial_buy(Decimal(40)))

    result = turn(path, venue, BUY_MARKET, notices=notices)

    order = result.buys[0]
    assert order.status is OrderStatus.FILLED
    assert (order.amount, order.filled, order.position_amount) == (
        FIRST_AMOUNT,
        Decimal(40),
        Decimal(40),
    )
    state = stored(path)
    position = state.ledger.positions[order.client_order_id]
    assert (position.amount, position.cost_price, position.fee) == (
        Decimal(40),
        Decimal("10.01"),
        Decimal("0.4"),
    )
    assert state.ledger.balance == DEPOSIT - Decimal(40) * Decimal("10.01") - Decimal("0.4")
    assert venue.stops == [{"id": stop_client_id(order.client_order_id), "amount": Decimal(40)}]
    partial = [n for n in notices if n.kind is NoticeKind.PARTIAL_FILL]
    assert [(n.subject, n.entering) for n in partial] == [(order.client_order_id, True)]
    assert BTC in partial[0].message and "dolan 40" in partial[0].message
    assert BuyHalt.UNKNOWN_ORDERS not in result.halts
    assert not any(n.kind is NoticeKind.SAFE_MODE for n in notices)


@pytest.mark.parametrize(
    ("filled", "rules", "halts"),
    [
        (Decimal("0.5"), PairRules(Decimal("0.001"), Decimal(1), Decimal(0)), True),
        (Decimal("0.5"), PairRules(Decimal("0.001"), Decimal("0.001"), Decimal(10)), True),
        (Decimal(1), PairRules(Decimal("0.001"), Decimal(1), Decimal(10)), False),
    ],
    ids=["below-min-amount", "below-min-notional", "exactly-the-minimum"],
)
def test_partial_buy_below_minimum_halts_same_turn(
    tmp_path: Path, filled: Decimal, rules: PairRules, halts: bool
) -> None:
    """AC-2 (R-2; plan Risk 7): kısmi alımın net miktarı asgari miktarın ya da (fiyat 10 ile)
    asgari tutarın altındaysa pozisyon yine yazılır, güvenli mod devreye girer, alım aynı turda
    durur (ETH alınmaz), bildirim üretilir. Tam asgari değer (1 BTC, 10 USDT) güvenli moda
    geçirmez."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    market = {BTC: pair_market(closes=CROSS, rules=rules), ETH: pair_market(closes=CROSS)}
    venue = Venue(buy=lambda cid, amount: ended(cid, filled, "10.01", "0.001"))

    result = turn(path, venue, market, notices=notices, whitelist=(BTC, ETH))

    btc = result.buys[0]
    assert btc.pair == BTC and stored(path).ledger.positions[btc.client_order_id].amount == filled
    below = [n for n in notices if n.kind is NoticeKind.POSITION_BELOW_MINIMUM]
    if halts:
        assert BuyHalt.POSITION_BELOW_MINIMUM in result.halts
        assert [o.pair for o in result.buys] == [BTC]
        assert [(n.subject, n.entering) for n in below] == [(btc.client_order_id, True)]
    else:
        assert BuyHalt.POSITION_BELOW_MINIMUM not in result.halts
        assert [o.pair for o in result.buys] == [BTC, ETH]
        assert below == []


def proportional_cost(part: Decimal) -> Decimal:
    """G-7: part / 49.115 * (49.115 * 10.01 + 0.5); ücret payı A-2'deki gibi yuvarlanır."""
    with localcontext(prec=80):
        share = (Decimal("0.5") * part / FIRST_AMOUNT).quantize(Decimal("1E-25"))
        return part * Decimal("10.01") + share


def test_partial_close_keeps_rest_and_replaces_stop(tmp_path: Path) -> None:
    """AC-3 (R-3, G-7): kapanışın 30'u dolup kalanı sona erer: 30 kapanış olarak, maliyeti miktarla
    orantılı (30 / 49.115 * (49.115 * 10.01 + 0.5)) gerçekleşen kâr/zararla yazılır; kalan 19.115
    açık kalır ve borsa stopu kalan miktarla yeni nesil kimlikle (`cs2-`) hemen verilir; defter ↔
    emir çelişkisi yoktur."""
    path = live_store(tmp_path)
    subject = turn(path, Venue(), BUY_MARKET).buys[0].client_order_id
    notices: list[TurnNotice] = []
    sell: Replier = lambda cid, amount: ended(cid, Decimal(30), "14.97", "0.45")  # noqa: E731
    venue = Venue(balance=ledger_balance(path), sell=sell)

    result = turn(path, venue, target_market(T1), T1, notices=notices)

    (closure,) = result.closures
    assert closure.client_order_id == "cx-" + subject.removeprefix("cb-")
    assert closure.amount == Decimal(30)
    proceeds = Decimal(30) * Decimal("14.97") - Decimal("0.45")
    assert closure.proceeds == proceeds
    assert closure.realized == proceeds - proportional_cost(Decimal(30))
    state = stored(path)  # asserts no ledger <-> order conflict
    rest = state.ledger.positions[subject]
    assert rest.amount == FIRST_AMOUNT - 30
    assert venue.stops == [{"id": stop_client_id(subject, 1), "amount": FIRST_AMOUNT - 30}]
    assert venue.stops[0]["id"].startswith("cs2-")
    partial = [n for n in notices if n.kind is NoticeKind.PARTIAL_FILL]
    assert [n.subject for n in partial] == [closure.client_order_id]
    assert BuyHalt.STOP_ORDER_FAILED not in result.halts


class Watching(Venue):
    """Sorgulanan stop kimliklerini kaydeder."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.stop_queries: list[str] = []

    def query(self, client_order_id: str, symbol: str = "") -> OrderStatus:
        self.stop_queries.append(client_order_id)
        return super().query(client_order_id, symbol)


def test_rest_reevaluated_next_turn_with_next_id(tmp_path: Path) -> None:
    """AC-3 (R-3; plan Risk 3): kalan pozisyon sonraki turda yeniden değerlendirilir: stop sorgusu
    yeni nesil (`cs2-`) içindir; fiyat arada kalırsa satış olmaz, hedefe gelince kalan miktar
    `cx2-` ile satılır ve pozisyon kapanır; iki kapanışın gerçekleşen toplamı tam kapanışın
    maliyetine göre hesaplanır."""
    path = live_store(tmp_path)
    subject = turn(path, Venue(), BUY_MARKET).buys[0].client_order_id
    memory = TurnMemory()
    sell: Replier = lambda cid, amount: ended(cid, Decimal(30), "14.97", "0.45")  # noqa: E731
    turn(path, Venue(balance=ledger_balance(path), sell=sell), target_market(T1), T1, memory=memory)

    quiet = Watching(balance=ledger_balance(path))
    middle = {BTC: pair_market(closes=FLAT, price=Decimal(12), closed_at=T2)}
    calm = turn(path, quiet, middle, T2, memory=memory)
    assert calm.closes == () and stop_client_id(subject, 1) in quiet.stop_queries
    assert stop_client_id(subject) not in quiet.stop_queries

    last = Watching(balance=ledger_balance(path))
    done = turn(path, last, target_market(T3), T3, memory=memory)
    sells = [m for m in last.markets if m["side"] == "sell"]
    assert [(m["id"], m["amount"]) for m in sells] == [
        ("cx2-" + subject.removeprefix("cb-"), FIRST_AMOUNT - 30)
    ]
    assert [c.amount for c in done.closures] == [FIRST_AMOUNT - 30]
    state = stored(path)
    assert state.ledger.positions == {}
    with localcontext(prec=80):
        cost = sum(c.proceeds - c.realized for c in state.ledger.closures.values())
        assert cost == FIRST_AMOUNT * Decimal("10.01") + Decimal("0.5")


def test_bnb_fee_notice_no_safe_mode_balance_reconciles(tmp_path: Path) -> None:
    """AC-4 (R-4; plan Risk 2): BNB komisyonlu alımda miktar dolan miktardır; BNB/USDT okunduğunda
    ücret 0.0008 * 600 = 0.48 USDT'dir ("tahmini" değil, bildirim yok). Okunamadığında ücret
    ayardaki oranla tahmin edilir, "tahmini" işareti ve bir kez bildirim gider. Güvenli mod yoktur;
    borsa USDT'yi yalnız ödenen tutar kadar düştüğü için mutabakat, defter + BNB komisyonlarının
    USDT değerini bekler ve durmaz — kapanıştan sonra da."""
    path = live_store(tmp_path)
    notices: list[TurnNotice] = []
    bnb: Replier = lambda cid, amount: fill(cid, amount, "10.01", "0.0008", "BNB")  # noqa: E731
    priced = Venue(buy=bnb, prices={"BNB/USDT": Decimal(600)})
    order = turn(path, priced, BUY_MARKET, notices=notices).buys[0]
    assert order.status is OrderStatus.FILLED and order.fee_estimated is False
    assert (order.fee, order.commission, order.commission_asset) == (
        Decimal("0.48"),
        Decimal("0.0008"),
        "BNB",
    )
    assert priced.priced == ["BNB/USDT"]
    assert stored(path).ledger.positions[order.client_order_id].amount == FIRST_AMOUNT
    assert not any(n.kind is NoticeKind.ESTIMATED_FEE for n in notices)

    paid = FIRST_AMOUNT * Decimal("10.01")
    exchange_balance = DEPOSIT - paid  # Binance debits only what the coin cost in USDT
    assert ledger_balance(path) == exchange_balance - Decimal("0.48")
    sell_bnb: Replier = lambda cid, amount: fill(cid, amount, "14.97", "0.001", "BNB")  # noqa: E731
    closing = Venue(balance=exchange_balance, sell=sell_bnb)  # BNB/USDT cannot be read
    closed = turn(path, closing, target_market(T1), T1, notices=notices)
    assert BuyHalt.RECONCILIATION_HALT not in closed.halts
    sale = closed.closes[0]
    assert sale.fee_estimated is True
    assert sale.fee == FIRST_AMOUNT * Decimal("14.97") * Decimal("0.001")
    estimated = [n for n in notices if n.kind is NoticeKind.ESTIMATED_FEE]
    assert [(n.subject, n.entering) for n in estimated] == [(sale.client_order_id, True)]
    assert "BNB" in estimated[0].message

    exchange_balance += FIRST_AMOUNT * Decimal("14.97")  # credited in full, fee taken in BNB
    after = turn(
        path, Venue(balance=exchange_balance), target_market(T2, "10"), T2, notices=notices
    )
    assert BuyHalt.RECONCILIATION_HALT not in after.halts
    assert BuyHalt.UNKNOWN_ORDERS not in after.halts
    assert not any(n.kind is NoticeKind.SAFE_MODE for n in notices)
    assert not any(n.kind is NoticeKind.RECONCILIATION for n in notices)
