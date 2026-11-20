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
