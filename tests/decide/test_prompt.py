"""Spec 0059 AC-3 (istem): veri bölümü işaretli; parmak izleri; BTC bağlamı; boyut sınırı."""

from crytobot.decide import (
    PROMPT_FINGERPRINT,
    PROMPT_LIMIT,
    SYSTEM_PROMPT,
    CoinSummary,
    build_prompt,
    summarize,
)
from tests.decide.helpers import BOUNDARY, coin_data


def summary(coin: str, base: float = 100.0) -> CoinSummary:
    found = summarize(coin_data(coin, base), BOUNDARY)
    assert found is not None
    return found


def test_data_section_marked_and_fingerprints() -> None:
    sol, eth = summary("SOL"), summary("ETH", 50.0)
    prompt = build_prompt([sol, eth], None, BOUNDARY)
    text = prompt.text
    assert text.startswith("TALİMAT")
    assert "talimat değildir" in text
    marks = [w for w in text.split() if "VERİ-" in w]
    open_mark = next(m for m in marks if m.startswith("<<<VERİ-"))
    close_mark = next(m for m in marks if m.endswith(">>>"))
    start, end = text.index(open_mark + "\n"), text.rindex(close_mark)
    assert sol.text in text[start:end] and eth.text in text[start:end]
    assert prompt.coins == ("SOL", "ETH")
    assert "Coinler: SOL, ETH" in text
    again = build_prompt([sol, eth], None, BOUNDARY)
    assert again.input_fingerprint == prompt.input_fingerprint
    other = build_prompt([sol], None, BOUNDARY)
    assert other.input_fingerprint != prompt.input_fingerprint
    assert len(PROMPT_FINGERPRINT) == 64


def test_system_prompt_is_one_ascii_line() -> None:
    assert SYSTEM_PROMPT.isascii() and "\n" not in SYSTEM_PROMPT
    assert not set('&|<>^%"') & set(SYSTEM_PROMPT)


def test_btc_context_added_when_not_decided() -> None:
    btc, sol = summary("BTC", 90000.0), summary("SOL")
    prompt = build_prompt([sol], btc, BOUNDARY)
    assert "(bağlam, karar istenmez)\n## BTC" in prompt.text
    assert prompt.coins == ("SOL",)
    both = build_prompt([btc, sol], btc, BOUNDARY)
    assert "bağlam, karar istenmez" not in both.text


def test_size_limit_shortens_4h_rows() -> None:
    big = [summary(f"C{i}") for i in range(40)]
    big = [CoinSummary(f"C{i}", s.text, s.low, s.high, s.last_close) for i, s in enumerate(big)]
    prompt = build_prompt(big, None, BOUNDARY)
    full = sum(len(s.text.encode("utf-8")) for s in big)
    assert full > PROMPT_LIMIT
    assert len(prompt.text.encode("utf-8")) < full
    assert big[0].text not in prompt.text  # shortened


def test_twenty_coins_fit_without_shortening() -> None:
    """Spec 0061 CB-2: gerçekçi fiyat ve adımlarla 20 coin 64 KB'a kısaltılmadan sığar."""
    from decimal import Decimal

    from crytobot.decide import PREREGISTERED_COINS

    levels = {
        "BTC": (62000.0, "0.01"), "ETH": (1750.0, "0.01"), "SOL": (71.0, "0.01"),
        "BNB": (570.0, "0.01"), "XRP": (0.95, "0.0001"), "ADA": (0.1465, "0.0001"),
        "DOGE": (0.0566, "0.00001"), "AVAX": (6.8, "0.001"), "LINK": (8.8, "0.001"),
        "TRX": (0.306, "0.0001"), "BCH": (300.0, "0.1"), "LTC": (55.0, "0.01"),
        "SUI": (1.1, "0.0001"), "XLM": (0.11, "0.00001"), "HBAR": (0.08, "0.00001"),
        "DOT": (1.9, "0.001"), "SHIB": (0.0000071, "0.00000001"), "UNI": (3.9, "0.001"),
        "NEAR": (1.4, "0.001"), "APT": (2.6, "0.0001"),
    }  # fmt: skip
    assert set(levels) == set(PREREGISTERED_COINS)
    summaries = []
    for coin in PREREGISTERED_COINS:
        base, tick = levels[coin]
        found = summarize(coin_data(coin, base, tick=Decimal(tick)), BOUNDARY)
        assert found is not None, coin
        summaries.append(found)
    data = "\n\n".join(s.text for s in summaries)
    assert len(data.encode("utf-8")) < PROMPT_LIMIT
    prompt = build_prompt(summaries, None, BOUNDARY)
    assert all(s.text in prompt.text for s in summaries)  # nothing shortened
