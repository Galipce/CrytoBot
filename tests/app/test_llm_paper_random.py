"""Spec 0060 AC-7: eşlenik rastgele - tohumlu, tekrarlanabilir, ikiz kuralları (G-5)."""

from datetime import datetime
from decimal import Decimal

from crytobot.app._llm_paper import HOUR, Bar, PaperDecision, PaperTrade, Status
from crytobot.app._llm_paper_config import MEASUREMENT_END, MEASUREMENT_START
from crytobot.app._llm_paper_random import RandomResult, random_distribution, twins
from crytobot.risk import PairRules

START = MEASUREMENT_START
D = Decimal
COINS = ("AAA", "BBB", "CCC")
RULES = {coin: PairRules(D("0.0001"), D("0.0001"), D("5")) for coin in COINS}


def bars() -> dict[str, dict[datetime, Bar]]:
    found: dict[str, dict[datetime, Bar]] = {}
    for n, coin in enumerate(COINS):
        series = {}
        for i in range(-1, 300):
            at = START + HOUR * i
            price = D(100 + n * 10) * (1 + D(i % 9 - 4) / 100)
            series[at] = Bar(at, price, price * D("1.02"), price * D("0.98"), price)
        found[coin] = series
    return found


def llm(turn_hours: int, status: Status) -> PaperTrade:
    decision = PaperDecision(
        START + HOUR * turn_hours, "AAA", D("99"), D("100"), D("95"), D("110"), 4
    )
    return PaperTrade(decision, status)


def test_twin_rules() -> None:
    data = bars()
    trades = [
        llm(0, Status.CLOSED),
        llm(5, Status.REJECTED),
        llm(9, Status.NOT_FILLED),
        llm(12, Status.OPEN),
    ]
    made, missing = twins(trades, data, COINS, 0)
    assert missing == 0 and len(made) == 2  # only filled LLM trades get a twin
    first = made[0]
    assert first.market and first.turn == START
    previous_close = data[first.coin][START - HOUR].close
    assert first.entry_low == first.entry_high == previous_close
    assert first.stop == previous_close * (1 - D("0.05"))
    assert first.target == previous_close * (1 + D("0.10"))


def test_missing_entry_bar_counted() -> None:
    data = bars()
    for coin in COINS:
        del data[coin][START - HOUR]
    made, missing = twins([llm(0, Status.CLOSED)], data, COINS, 0)
    assert made == [] and missing == 1


def test_seeded_and_reproducible() -> None:
    data = bars()
    trades = [llm(0, Status.CLOSED), llm(20, Status.CLOSED), llm(40, Status.CLOSED)]
    window = (START, MEASUREMENT_END, START + HOUR * 250)
    one = random_distribution(trades, data, RULES, COINS, window, repeats=40)
    two = random_distribution(trades, data, RULES, COINS, window, repeats=40)
    assert one == two and len(one.nets) == 40
    assert len(set(one.nets)) > 1  # the draws differ between repeats


def test_percentiles() -> None:
    result = RandomResult(tuple(D(i) for i in range(1, 101)), 0)
    assert result.percentile(5) == 5 and result.percentile(50) == 50 and result.percentile(95) == 95
    assert result.rank_of(D("50.5")) == 50
    assert RandomResult((), 0).percentile(95) is None
