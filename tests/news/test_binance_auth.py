"""Spec 0056 AC-2 (plan Risk 7, A-1): imza ve anahtar yetkisinin hükmü."""

import json
from urllib.parse import parse_qsl

import pytest

from crytobot.news._binance_auth import (
    STREAM_TOPIC,
    Verdict,
    hmac_hex,
    judge_permissions,
    restrictions_query,
    signed_query,
    stream_query,
)

# Binance "WebSocket API Basic Information", Signature Generation example
DOC_SECRET = "Avqz4IQjoZSJOowMFSo3QZEd4ovfwLH7Kie8ZliTtP8ktDnqcX8bpCP7WluFtrfn"
DOC_PAYLOAD = (
    "random=56724ac693184379ae23ffe5e910063c&topic=topic1&recvWindow=30000&timestamp=1753244327210"
)
DOC_SIGNATURE = "8346d214e0da7165a0093043395f67e08c63f61b5d6e25779d513c11450e691b"

# the owner's read-only key as the probe saw it (plan A-1)
READ_ONLY = {
    "createTime": 1795060000000,
    "enableFixApiTrade": False,
    "enableFixReadOnly": False,
    "enableFutures": False,
    "enableInternalTransfer": False,
    "enableMargin": False,
    "enablePortfolioMarginTrading": False,
    "enableReading": True,
    "enableSpotAndMarginTrading": False,
    "enableVanillaOptions": False,
    "enableWithdrawals": False,
    "ipRestrict": False,
    "permitsUniversalTransfer": False,
}


def body(**changes: object) -> bytes:
    return json.dumps({**READ_ONLY, **changes}).encode()


def test_hmac_matches_binance_example() -> None:
    assert hmac_hex(DOC_SECRET, DOC_PAYLOAD) == DOC_SIGNATURE


def test_params_sorted_and_signed() -> None:
    query = signed_query("s", {"timestamp": 2, "random": "r", "recvWindow": 1, "topic": "a|b"})
    payload, signature = query.rsplit("&signature=", 1)
    assert payload == "random=r&recvWindow=1&timestamp=2&topic=a|b"
    assert signature == hmac_hex("s", payload)
    stream = dict(parse_qsl(stream_query("s", 5, "abc")))
    assert (stream["topic"], stream["timestamp"], stream["random"]) == (STREAM_TOPIC, "5", "abc")
    assert set(dict(parse_qsl(restrictions_query("s", 7)))) == {
        "recvWindow",
        "signature",
        "timestamp",
    }


@pytest.mark.parametrize(
    ("given", "verdict", "excess"),
    [
        (body(), Verdict.READ_ONLY, ()),
        (body(enableFixReadOnly=True, ipRestrict=True), Verdict.READ_ONLY, ()),
        (body(enableSpotAndMarginTrading=True), Verdict.EXCESS, ("enableSpotAndMarginTrading",)),
        (
            body(enableWithdrawals=True, permitsUniversalTransfer=True),
            Verdict.EXCESS,
            ("enableWithdrawals", "permitsUniversalTransfer"),
        ),
        (body(enableSomethingNew=True), Verdict.EXCESS, ("enableSomethingNew",)),
        (body(enableInternalTransfer=True), Verdict.EXCESS, ("enableInternalTransfer",)),
        (body(enableReading=False), Verdict.UNVERIFIED, ()),
        (body(enableWithdrawals="false"), Verdict.UNVERIFIED, ()),
        (json.dumps({"code": -2015, "msg": "Invalid API-key"}).encode(), Verdict.UNVERIFIED, ()),
        (b"<html>", Verdict.UNVERIFIED, ()),
        (b"[]", Verdict.UNVERIFIED, ()),
        (None, Verdict.UNVERIFIED, ()),
    ],
)
def test_permission_verdicts(
    given: bytes | None, verdict: Verdict, excess: tuple[str, ...]
) -> None:
    check = judge_permissions(given)
    assert (check.verdict, check.excess) == (verdict, excess)
    if verdict is Verdict.EXCESS:
        assert check.message == f"anahtar yetkisi fazla: {', '.join(excess)}"
    if verdict is Verdict.UNVERIFIED:
        assert check.message == "anahtar yetkisi doğrulanamadı"
