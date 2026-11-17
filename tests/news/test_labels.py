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
    title = "Notice of Removal of Trading Pairs: ABC/USDT, DEFUSDT, GHI/BTC, ABC/USDT"
    assert label(title).coins == ("ABC", "DEF", "GHI")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # parentheses decide: the staked quote asset is not a sample (review round 1 F-1)
        (
            "Introducing Renzo (REZ) on Binance Launchpool! Farm REZ by Staking BNB and FDUSD",
            ("REZ",),
        ),
        # a stable coin alone in parentheses decides: no coin, BTC of the pair is not a sample
        (
            "Binance Will List First Digital USD (FDUSD) and Enable Zero Maker Fees for BTC/FDUSD",
            (),
        ),
        # pairs: only the base asset
        ("Binance Adds ARB/BTC, OP/ETH & More on Cross Margin", ("ARB", "OP")),
        ("Binance Will Open Trading for BTC/EUR, ETH/TRY Spot Trading Pairs", ("BTC", "ETH")),
        # a single letter alone in parentheses is a coin (F-7), not elsewhere
        ("Binance Will List Wormhole (W) in the Launchpool", ("W",)),
        ("Binance Futures Will Launch USDⓈ-M (USDⓈ-M) ABCUSDT Perpetual", ("ABC",)),
        # a network in parentheses does not decide: the next tier names the coin
        ("Binance Will Support the XYZ Network Upgrade (BEP20)", ("XYZ",)),
    ],
)
def test_coin_tiers(title: str, expected: tuple[str, ...]) -> None:
    assert label(title).coins == expected


@pytest.mark.parametrize(
    "title",
    [
        "Binance Futures Will Delist USDⓈ-M ABCUSDT and DEFUSDT Perpetual Contracts",
        "Binance Margin Will Delist XYZ/BTC, XYZ/ETH Cross Margin Pairs",
    ],
)
def test_futures_and_margin_delist_not_delisting(title: str) -> None:
    # review round 1 F-2 (A-3): neither a spot delisting nor a futures/margin listing
    assert label(title).event_type == "diğer"


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


# Spec 0050 CB-1…CB-4 (plan Risk 2, 3): three types narrowed after the 0049 label audit (B-93)

FUTURES = "vadeli / marjin listeleme"
DELISTING = "listeden çıkarma"
SPOT = "spot listeleme"


@pytest.mark.parametrize(
    "title",
    [
        "Binance Futures Will Launch USDⓈ-M MBL Perpetual Contract With Up to 50x Leverage",
        "Binance Adds ANT, CLV, MDT, MIR, NEAR & WAXP on Cross Margin and ALCX, BICO & ELF on "
        "Isolated Margin",
        "Margin Trading for SNX & REEF Enabled on Binance",
        # boundary: new delivery contracts that name the coins
        "Binance Futures Will List BTC, ETH, ADA & LINK Coin-Margined Quarterly 0326 Futures "
        "Contracts",
        # boundary: a new coin added to several products, margin among them
        "Binance Will Add Kaia (KAIA) on Earn, Buy Crypto, Convert, and Margin",
    ],
)
def test_futures_margin_only_new_contract_for_a_coin(title: str) -> None:
    result = label(title)
    assert result.event_type == FUTURES, title
    assert result.coins, title


@pytest.mark.parametrize(
    "title",
    [
        # no coin named: a general announcement
        "Binance Launches Margin Trading Service",
        # campaign, voucher, bonus
        "Trade ONT to Win $50,000 in ONT Tokens & $15,000 in Binance Futures Vouchers!",
        "Binance Futures Launches 200,000 USDT Welcome Bonus",
        # system / function, collateral ratio
        "Binance to Fully Resume Market Order Function for All Spot and Margin Trading Pairs",
        "Binance Margin Will Update the Collateral Ratio of Multiple Cross Margin Assets "
        "(2025-07-18)",
        # boundary: trading resumes on an existing contract; copy trading
        "Binance Futures to Resume Trading on USDT-Margined MINA Perpetual Contract",
        "Binance Futures Copy Trading Adds New USDⓈ-M Contract (2024-08-06)",
    ],
)
def test_futures_margin_noise_is_not_futures_listing(title: str) -> None:
    assert label(title).event_type != FUTURES, title


def test_futures_margin_without_coin_falls_to_other() -> None:
    assert label("Binance Launches Margin Trading Service").event_type == "diğer"


@pytest.mark.parametrize(
    "title",
    ["Binance Will Delist BEAM on 2023-01-26", "Binance Will Delist DEGO, DENT, TRU on 2026-04-28"],
)
def test_delisting_only_spot_trading(title: str) -> None:
    assert label(title).event_type == DELISTING, title


@pytest.mark.parametrize(
    "title",
    [
        "Binance Staking to Delist EZ, TRU, VITE, ANC & MIR",
        "Binance Flexible Loan Has Delisted PEPE as a Borrowable Asset",
        "Binance VIP Loan Will Delist TUSD and ALCX from Eligible Collateral Asset List - "
        "2026-03-30",
        "Notice on Converting Delisted Tokens Balances to BUSD (2021-07-02)",
        "Notice on the Withdrawals of Delisted Tokens & Conversion of Selected Tokens to USDT "
        "(2024-04-01)",
    ],
)
def test_product_delisting_is_not_spot_delisting(title: str) -> None:
    assert label(title).event_type == "diğer", title


@pytest.mark.parametrize(
    ("title", "coin"), [("Binance Lists LINK", "LINK"), ("Binance Lists SNGLS", "SNGLS")]
)
def test_lists_is_spot_listing(title: str, coin: str) -> None:
    result = label(title)
    assert (result.event_type, result.coins) == (SPOT, (coin,))


@pytest.mark.parametrize(
    "title",
    [
        "Binance Adds NEO/ETH Trading Pair",
        "Binance Will Add MCO/BTC Trading Pair On August 24",
        "Binance Adds XLM/BUSD and ADA/BUSD Trading Pairs",
        "Notice on New Trading Pairs & Trading Bots Services on Binance Spot - 2024-12-19",
    ],
)
def test_new_pair_is_other(title: str) -> None:
    assert label(title).event_type == "diğer", title


def test_lists_is_spot_listing_new_pair_is_other() -> None:
    # CB-3 in one place for the criterion map: "Lists" is a listing, a new pair is not
    assert label("Binance Lists LINK").event_type == SPOT
    assert label("Binance Adds NEO/ETH Trading Pair").event_type == "diğer"


def test_needs_coin_changes_fingerprint() -> None:
    # CB-4: the new rule field enters the canonical JSON
    rules = tuple(replace(r, needs_coin=not r.needs_coin) for r in RULES)
    assert rules_fingerprint(replace(DEFAULT_RULES, rules=rules)) != RULES_FINGERPRINT
    assert RULES_FINGERPRINT != "ed55dd4f70a48f40ed0d0da3bced85ddef8109c96efa8141df55d01813f941f2"
    # type list, order and expected directions are 0048's
    assert EVENT_TYPES == (
        ("spot listeleme", "olumlu"),
        ("listeden çıkarma", "olumsuz"),
        ("işlem çifti kaldırma", "olumsuz"),
        ("izleme etiketi", "olumsuz"),
        ("launchpool / launchpad / HODLer", "olumlu"),
        ("vadeli / marjin listeleme", "olumlu"),
        ("askıya alma ve bakım", "nötr"),
        ("ağ yükseltmesi", "nötr"),
        ("diğer", "nötr"),
    )


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        # a margin listing leading the title stays a listing with a campaign appended (plan step 3)
        ("Binance Adds FIS & WAXP on Isolated Margin, Launches 50,000 USDT Giveaway!", FUTURES),
        ("FET Added to Margin Trading on Binance - $100,000 in FET Tokens to be Won!", FUTURES),
        # WIN is a coin, "Ecosystem" is not a system notice
        ("BTCST & WIN Enabled on Binance Isolated Margin", FUTURES),
        (
            "Binance Futures Launches DOTECO (Polkadot Ecosystem) Composite Index Perpetual "
            "Contract with Up to 20x Leverage",
            FUTURES,
        ),
        # noise not led by a margin listing
        (
            "Binance Margin Enables a 5% Discount on Borrowing Interest When Paying With BNB",
            "diğer",
        ),
        ("Binance Futures Adds BTC to Cross Collateral", "diğer"),
        ("Binance Futures Will Postpone the Launch of AIAUSDT Perpetual Contract", "diğer"),
        ("Binance Launches Futures Battle Badges - $30,000 in BNB to Be Won", "diğer"),
        # delist / remove still excludes, as in 0048 (A-3)
        (
            "Binance Adds GLM, NEBL & VIB on Cross Margin and Isolated Margin, Delisting DF from "
            "Isolated Margin",
            "diğer",
        ),
    ],
)
def test_futures_margin_lead_and_noise_words(title: str, expected: str) -> None:
    assert label(title).event_type == expected, title
