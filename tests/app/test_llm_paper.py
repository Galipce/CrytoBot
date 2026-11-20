"""Spec 0060 AC-3, AC-4, AC-5: dolum, çıkış, maliyet, risk kuralları ve drawdown durdurması."""

from datetime import datetime, timedelta
from decimal import Decimal

from crytobot.app._llm_paper import (
    HOLD_BARS,
    HOUR,
    Bar,
    ExitKind,
    PaperDecision,
    Replay,
    Status,
    replay,
)
from crytobot.app._llm_paper_config import (
    FEE,
    MEASUREMENT_END,
    MEASUREMENT_START,
    OPENING_BALANCE,
    SLIPPAGE,
)
from crytobot.risk import PairRules

START = MEASUREMENT_START
RULES = PairRules(Decimal("0.0001"), Decimal("0.0001"), Decimal("5"))
D = Decimal


def flat(coin_bars: dict[datetime, Bar], start: datetime, hours: int, price: str) -> None:
    for i in range(hours):
        at = start + HOUR * i
        coin_bars.setdefault(at, Bar(at, D(price), D(price), D(price), D(price)))


def bar(at: datetime, low: str, high: str, close: str | None = None) -> Bar:
    return Bar(at, D(close or high), D(high), D(low), D(close or high))


def series(overrides: dict[int, Bar], hours: int = 400, price: str = "105") -> dict[datetime, Bar]:
    found = {START + HOUR * i: b for i, b in overrides.items()}
    flat(found, START, hours, price)
    return found


def decision(coin: str = "SOL", turn: datetime = START, **changes: object) -> PaperDecision:
    values: dict[str, object] = {
        "entry_low": D("99"),
        "entry_high": D("100"),
        "stop": D("95"),
        "target": D("120"),
        "valid_hours": 4,
    }
    values.update(changes)
    return PaperDecision(turn, coin, **values)  # type: ignore[arg-type]


def run(
    decisions: list[PaperDecision],
    bars: dict[str, dict[datetime, Bar]],
    horizon: datetime = MEASUREMENT_END,
    rules: dict[str, PairRules] | None = None,
) -> Replay:
    found_rules = rules or {coin: RULES for coin in bars}
    return replay(decisions, bars, found_rules, START, MEASUREMENT_END, horizon)


def test_fill_in_zone_at_upper_bound() -> None:
    bars = {
        "SOL": series(
            {2: bar(START + 2 * HOUR, "99.5", "106"), 10: bar(START + 10 * HOUR, "104", "121")}
        )
    }
    trade = run([decision()], bars).trades[0]
    assert trade.status is Status.CLOSED
    assert trade.filled_at == START + 2 * HOUR
    assert trade.fill_price == D("100") * (1 + SLIPPAGE)
    assert trade.exit_kind is ExitKind.TARGET
    assert trade.exit_price == D("120") * (1 - SLIPPAGE)


def test_not_filled() -> None:
    bars = {"SOL": series({4: bar(START + 4 * HOUR, "99", "101")})}  # touches after validity
    assert run([decision()], bars).trades[0].status is Status.NOT_FILLED


def test_validity_boundary() -> None:
    bars = {"SOL": series({3: bar(START + 3 * HOUR, "99", "101")})}  # the last valid bar
    assert run([decision()], bars).trades[0].filled_at == START + 3 * HOUR  # L-4


def test_exits_target_stop_same_candle_time() -> None:
    both = {"SOL": series({1: bar(START + HOUR, "94", "121")})}
    trade = run([decision()], both).trades[0]
    assert trade.exit_kind is ExitKind.STOP  # fill bar touches both: stop first
    assert trade.exit_price == D("95") * (1 - SLIPPAGE)
    stopped = {
        "SOL": series({1: bar(START + HOUR, "99", "101"), 5: bar(START + 5 * HOUR, "94", "100")})
    }
    assert run([decision()], stopped).trades[0].exit_kind is ExitKind.STOP
    timed = {"SOL": series({1: bar(START + HOUR, "99", "101", "100")}, price="101")}
    trade = run([decision()], timed).trades[0]
    assert trade.exit_kind is ExitKind.TIME
    assert trade.exit_at == START + HOUR * (1 + HOLD_BARS + 1)
    assert trade.exit_price == D("101") * (1 - SLIPPAGE)


def test_costs_each_side() -> None:
    bars = {
        "SOL": series({1: bar(START + HOUR, "99", "101"), 3: bar(START + 3 * HOUR, "110", "121")})
    }
    result = run([decision()], bars)
    trade = result.trades[0]
    assert trade.amount is not None and trade.net is not None
    paid = trade.amount * D("100") * (1 + SLIPPAGE) * (1 + FEE)
    proceeds = trade.amount * D("120") * (1 - SLIPPAGE)
    assert trade.net == proceeds - proceeds * FEE - paid
    assert result.final_equity == OPENING_BALANCE + trade.net


def test_measurement_end_close() -> None:
    late = MEASUREMENT_END - 3 * HOUR
    bars = {"SOL": {}}  # type: ignore[var-annotated]
    flat(bars["SOL"], late - HOUR, 10, "101")
    bars["SOL"][late] = bar(late, "99", "101", "100")
    trade = run([decision(turn=late)], bars).trades[0]
    assert trade.exit_kind is ExitKind.END
    assert trade.exit_at == MEASUREMENT_END


def test_open_and_pending_at_horizon() -> None:
    bars = {
        "SOL": series({1: bar(START + HOUR, "99", "101")}, hours=3, price="101"),
        "ETH": series({}, hours=3),
    }
    horizon = START + 2 * HOUR
    result = run([decision(), decision("ETH", turn=START + HOUR)], bars, horizon)
    assert [t.status for t in result.trades] == [Status.OPEN, Status.PENDING]


def test_unmeasurable_named() -> None:
    bars = {"SOL": series({})}
    del bars["SOL"][START + 3 * HOUR]
    assert run([decision()], bars).trades[0].status is Status.UNMEASURABLE


def test_same_coin_skipped() -> None:
    bars = {"SOL": series({})}
    result = run([decision(), decision(turn=START + HOUR)], bars)
    assert [t.status for t in result.trades] == [Status.NOT_FILLED, Status.SAME_COIN]


def test_each_risk_rule_named() -> None:
    coins = [f"C{i}" for i in range(6)]
    touch = {1: bar(START + HOUR, "99", "101", "100")}
    bars = {coin: series(dict(touch), price="100") for coin in coins}
    result = run([decision(coin) for coin in coins], bars)
    assert [t.rejection for t in result.trades].count("açık pozisyon sınırı") == 1
    small = run(
        [decision()],
        {"SOL": series(dict(touch))},
        rules={"SOL": PairRules(D("1"), D("1"), D("1000"))},
    )
    assert small.trades[0].rejection == "en küçük tutar"
    thin = run([decision(target=D("100.5"))], {"SOL": series(dict(touch))})
    assert thin.trades[0].rejection == "maliyet katı"


def _losses(days: int, per_day: int) -> tuple[list[PaperDecision], dict[str, dict[datetime, Bar]]]:
    decisions, bars = [], {}
    for day in range(days):
        for k in range(per_day):
            turn = START + timedelta(days=day) + HOUR * (2 * k)
            coin = f"L{day}_{k}"
            found = {
                turn: bar(turn, "99", "101", "100"),
                turn + HOUR: bar(turn + HOUR, "90", "100", "91"),
            }
            flat(found, START - HOUR, 24 * (days + 9), "100")
            bars[coin] = found
            decisions.append(decision(coin, turn=turn, stop=D("95"), target=D("130")))
    decisions.sort(key=lambda d: (d.turn, d.coin))
    return decisions, bars


def test_daily_loss_then_next_day() -> None:
    decisions, bars = _losses(2, 5)
    result = run(decisions, bars)
    first_day = [t for t in result.trades if t.decision.turn < START + timedelta(days=1)]
    assert "günlük zarar" in [t.rejection for t in first_day]
    second_day = [t for t in result.trades if t.decision.turn >= START + timedelta(days=1)]
    assert second_day[0].status is Status.CLOSED  # a new UTC day resets the day's start


def test_drawdown_halts_new_trades() -> None:
    decisions, bars = _losses(10, 2)
    result = run(decisions, bars)
    assert result.halted_at is not None
    after = [t for t in result.trades if t.decision.turn >= result.halted_at]
    assert after and all(t.rejection == "drawdown durdurması" for t in after)


def test_cash_never_negative_when_balance_limits() -> None:
    """Review round 1 M-3: bakiyeyle sınırlı dolumlar kasayı aşmaz; ret adı doğru."""
    rules = {c: PairRules(D("0.001"), D("0.001"), D("1")) for c in ("A", "B", "C")}
    bars = {c: series({}, hours=10, price="1") for c in rules}
    made = [
        decision(c, entry_low=D("0.999"), entry_high=D("1"), stop=D("0.99"), target=D("1.05"),
                 valid_hours=3)
        for c in rules
    ]  # fmt: skip
    result = run(made, bars, START + 3 * HOUR, rules)
    paid = sum(
        (t.amount * t.fill_price * (1 + FEE) for t in result.trades if t.amount and t.fill_price),
        D(0),
    )
    assert paid <= OPENING_BALANCE
    assert "geçersiz girdi" not in [t.rejection for t in result.trades]


def test_target_in_fill_bar_only_when_filled_at_open() -> None:
    """Review round 1 M-4, A-8: tepesi dolumdan önce gelmiş olabilecek hedef aynı mumda sayılmaz."""
    gap = {"SOL": series({1: Bar(START + HOUR, D("105"), D("125"), D("99"), D("104"))})}
    trade = run([decision()], gap).trades[0]
    assert trade.filled_at == START + HOUR and trade.exit_kind is not ExitKind.TARGET
    at_open = {"SOL": series({1: Bar(START + HOUR, D("100"), D("125"), D("99"), D("104"))})}
    trade = run([decision()], at_open).trades[0]
    assert trade.exit_kind is ExitKind.TARGET and trade.exit_at == START + 2 * HOUR


def test_daily_loss_is_the_utc_day() -> None:
    """Review round 1 L-5: 22:00'de dolan günlük zarar ertesi gün 01:00'de engel değil."""
    evening = START.replace(hour=0) + timedelta(hours=17)
    decisions, bars = [], {}
    for k in range(5):
        turn = evening + HOUR * k
        coin = f"E{k}"
        found = {
            turn: bar(turn, "99", "101", "100"),
            turn + HOUR: bar(turn + HOUR, "90", "100", "91"),
        }
        flat(found, START - HOUR, 24 * 12, "100")
        bars[coin] = found
        decisions.append(decision(coin, turn=turn, target=D("130")))
    late = evening + HOUR * 4
    assert "günlük zarar" in [t.rejection for t in run(decisions, bars).trades]
    morning = evening + HOUR * 8  # 01:00 the next UTC day: less than 24 hours after the losses
    found = {morning: bar(morning, "99", "101", "100")}
    flat(found, START - HOUR, 24 * 12, "100")
    bars["M"] = found
    result = run([*decisions, decision("M", turn=morning, target=D("130"))], bars)
    assert result.trades[-1].status is not Status.REJECTED
    assert late.date() != morning.date()


def test_pending_not_counted_and_risk_budget() -> None:
    """Review round 1 L-6: bekleyenler pozisyon sınırına girmez; miktar risk bütçesine sığar."""
    coins = [f"P{i}" for i in range(6)]
    # P0 waits (its zone is touched an hour later); P1...P5 fill at once: five open, one pending
    bars = {c: series({0: bar(START, "99", "101", "100")}, price="104") for c in coins[1:]}
    bars["P0"] = series({1: bar(START + HOUR, "99", "101", "100")}, price="104")
    result = run([decision(c) for c in coins], bars)
    by_coin = {t.decision.coin: t for t in result.trades}
    assert all(by_coin[c].status is not Status.REJECTED for c in coins[1:])
    assert by_coin["P0"].rejection == "açık pozisyon sınırı"
    trade = by_coin["P1"]
    assert trade.amount is not None
    unit_loss = D("100") * (1 + SLIPPAGE) - D("95") * (1 - SLIPPAGE)
    assert trade.amount * unit_loss <= OPENING_BALANCE * D("0.01")
