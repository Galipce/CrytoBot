"""Spec 0041 CB-3, plan Risk 7: ağın tek okuyucusu ve paper modda testnet reddi."""

import pytest

from crytobot.app import TESTNET_PAPER_REFUSAL, load_network


def test_paper_with_testnet_refused() -> None:
    """CB-3: paper modda `testnet = true` adıyla reddedilir."""
    result = load_network({"exchange": {"testnet": True}}, "paper")

    assert result.network is None
    assert result.message == TESTNET_PAPER_REFUSAL
    assert result.message == "ayar geçersiz: exchange.testnet (testnet yalnız live modda)"


@pytest.mark.parametrize("mode", ["paper", "live"])
@pytest.mark.parametrize(
    "document",
    [{}, {"exchange": {}}, {"exchange": {"testnet": False}}],
    ids=["no-section", "no-key", "false"],
)
def test_absent_or_false_is_mainnet(document: dict[str, object], mode: str) -> None:
    """PB-1, PB-2: bölüm, anahtar yoksa ya da `false` ise iki modda da mainnet."""
    assert load_network(document, mode).network == "mainnet"


def test_live_with_testnet_is_testnet() -> None:
    assert load_network({"exchange": {"testnet": True}}, "live").network == "testnet"


@pytest.mark.parametrize("mode", ["paper", "live"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, ["true"]])
def test_non_boolean_testnet_is_invalid(value: object, mode: str) -> None:
    """Risk 7: `"false"` metni artık testnet değildir, geçersizdir; belirsiz değer fail-closed."""
    result = load_network({"exchange": {"testnet": value}}, mode)

    assert result.network is None
    assert result.message == "ayar geçersiz: exchange.testnet"


@pytest.mark.parametrize("table", ["testnet", 1, ["testnet"]])
def test_exchange_section_must_be_a_table(table: object) -> None:
    result = load_network({"exchange": table}, "live")

    assert result.network is None
    assert result.message == "ayar geçersiz: exchange"
