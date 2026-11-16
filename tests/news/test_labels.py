"""Spec 0048 AC-1 (R-1, Q-1, Q-2; plan Risk 3, 4): başlık etiketleri — tür, beklenen yön, coinler,
dışlama listesi, kural seti parmak izi."""

from dataclasses import replace

import pytest

from crytobot.news import EVENT_TYPES, RULES_FINGERPRINT, label, title_pattern
from crytobot.news._labels import DEFAULT_RULES, RULES, EventRule, rules_fingerprint

# One recorded-style Binance title per type (table order)
TITLES = {
    "spot listeleme": "Binance Will List Pepe (PEPE)",
    "listeden çıkarma": "Binance Will Delist ANT, MULTI, VAI & XMR on 2024-02-20",
    "işlem çifti kaldırma": "Notice of Removal of Spot Trading Pairs - 2024-05-10",
    "izleme etiketi": "Binance Will Extend the Monitoring Tag to Include ZEC",
    "launchpool / launchpad / HODLer": "Introducing Lista (LISTA) on Binance Launchpool!",
    "vadeli / marjin listeleme": (
        "Binance Futures Will Launch USDⓈ-Margined WIFUSDT Perpetual Contract"
    ),
    "askıya alma ve bakım": "Binance Will Suspend Deposits and Withdrawals on the Solana Network",
    "ağ yükseltmesi": "Binance Will Support the Ethereum Network Upgrade & Hard Fork",
}


def test_each_type_has_a_recorded_title() -> None:
    assert [name for name, _ in EVENT_TYPES][:-1] == list(TITLES)
    for name, title in TITLES.items():
        assert label(title).event_type == name, title
    directions = dict(EVENT_TYPES)
    assert directions["spot listeleme"] == "olumlu"
    assert directions["listeden çıkarma"] == "olumsuz"
    assert directions["askıya alma ve bakım"] == "nötr"


def test_unmatched_is_other() -> None:
    result = label("Binance Completes the Integration of Something New")
    assert (result.event_type, result.direction) == ("diğer", "nötr")


def test_first_type_in_table_order_wins() -> None:
    # "will list" and "delist" both match: the spot listing comes first in the table
    assert label("Binance Will List XYZ and Delist ABC").event_type == "spot listeleme"
    # "will list" with "futures" is not a spot listing: the next matching type wins
    assert label("Binance Will List XYZ Futures").event_type == "vadeli / marjin listeleme"
    # delisting before the monitoring tag
    assert label("Binance Will Delist ABC and Remove the Monitoring Tag").event_type == (
        "listeden çıkarma"
    )


def test_three_coins_three_samples() -> None:
    assert label("Binance Will Delist ANT, MULTI & VAI").coins == ("ANT", "MULTI", "VAI")
    # pairs: XYZ/USDT and XYZUSDT name the coin once, in title order, without repeats
    title = "Notice of Removal of Trading Pairs: ABC/USDT, DEFUSDT, ABC/USDT (GHI)"
    assert label(title).coins == ("ABC", "DEF", "GHI")


def test_no_coin_single_sample() -> None:
    assert label("Notice of Removal of Spot Trading Pairs - 2024-05-10").coins == ()


@pytest.mark.parametrize(
    "token",
    [
        "(BEP20)",
        "(ERC20)",
        "(USDT)",
        "(USDC)",
        "(FDUSD)",
        "(2024-02-20)",
        "(UTC)",
        "10AM",
        "1ST",
        "AM",
        "KYC",
        "USDⓈ",
    ],
)
def test_excluded_tokens_not_coins(token: str) -> None:
    assert label(f"Binance Will List Pepe {token}").coins == ()


def test_digits_and_mixed_case_tokens() -> None:
    # a real coin with digits is a coin; a capitalised word is not
    assert label("Binance Will List 1INCH and 1000SATS (Pepe)").coins == ("1INCH", "1000SATS")


def test_fingerprint_stable_and_rule_sensitive() -> None:
    assert RULES_FINGERPRINT == rules_fingerprint() == rules_fingerprint(DEFAULT_RULES)
    assert len(RULES_FINGERPRINT) == 64
    changed_rule = replace(
        DEFAULT_RULES, rules=(EventRule("spot listeleme", "olumlu", "will list"), *RULES[1:])
    )
    changed_list = replace(DEFAULT_RULES, excluded=(*DEFAULT_RULES.excluded, "XYZ"))
    assert rules_fingerprint(changed_rule) != RULES_FINGERPRINT
    assert rules_fingerprint(changed_list) != RULES_FINGERPRINT


def test_title_pattern_hides_coins_and_digits() -> None:
    assert title_pattern("Binance Will Delist ANT, MULTI on 2024-02-20") == (
        "Binance Will Delist X, X on ####-##-##"
    )
    assert title_pattern("Removal of DEFUSDT") == "Removal of X"
