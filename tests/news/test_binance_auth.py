"""Spec 0056 AC-2 (plan Risk 7, A-1): imza ve anahtar yetkisinin hükmü."""

import json
from urllib.parse import parse_qsl

import pytest

from crytobot.news._binance_auth import (
    STREAM_TOPIC,
    Verdict,
    error_reason,
    hmac_hex,
    judge_permissions,
    restrictions_query,
    server_time,
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


INVALID = "anahtar yetkisi doğrulanamadı (yanıt geçersiz)"


@pytest.mark.parametrize(
    ("given", "verdict", "excess", "message"),
    [
        (body(), Verdict.READ_ONLY, (), "anahtar yetkisi: yalnız okuma"),
        (body(enableFixReadOnly=True, ipRestrict=True), Verdict.READ_ONLY, (), None),
        (
            body(enableSpotAndMarginTrading=True),
            Verdict.EXCESS,
            ("enableSpotAndMarginTrading",),
            None,
        ),
        (
            body(enableWithdrawals=True, permitsUniversalTransfer=True),
            Verdict.EXCESS,
            ("enableWithdrawals", "permitsUniversalTransfer"),
            "anahtar yetkisi fazla: enableWithdrawals, permitsUniversalTransfer",
        ),
        (body(enableSomethingNew=True), Verdict.EXCESS, ("enableSomethingNew",), None),
        (body(enableInternalTransfer=True), Verdict.EXCESS, ("enableInternalTransfer",), None),
        (body(enableReading=False), Verdict.UNVERIFIED, (), INVALID),
        (body(enableWithdrawals="false"), Verdict.UNVERIFIED, (), INVALID),
        (json.dumps({"code": -2015, "msg": "Invalid"}).encode(), Verdict.UNVERIFIED, (), INVALID),
        (b"<html>", Verdict.UNVERIFIED, (), INVALID),
        (b"[]", Verdict.UNVERIFIED, (), INVALID),
        (None, Verdict.UNVERIFIED, (), "anahtar yetkisi doğrulanamadı"),
        # plan A-7: a reason name from the request layer is carried, never a value
        (
            "http_400/-1021",
            Verdict.UNVERIFIED,
            (),
            "anahtar yetkisi doğrulanamadı (http_400/-1021)",
        ),
        ("timeout", Verdict.UNVERIFIED, (), "anahtar yetkisi doğrulanamadı (timeout)"),
    ],
)
def test_permission_verdicts(
    given: bytes | str | None, verdict: Verdict, excess: tuple[str, ...], message: str | None
) -> None:
    check = judge_permissions(given)
    assert (check.verdict, check.excess) == (verdict, excess)
    if message is not None:
        assert check.message == message
    if verdict is Verdict.EXCESS:
        assert check.message == f"anahtar yetkisi fazla: {', '.join(excess)}"


@pytest.mark.parametrize(
    ("status", "detail", "name"),
    [
        (
            400,
            b'{"code":-1021,"msg":"Timestamp for this request was 1000ms ahead"}',
            "http_400/-1021",
        ),
        (401, b'{"code":-2015,"msg":"Invalid API-key, IP, or permissions"}', "http_401/-2015"),
        (502, b"<html>bad gateway</html>", "http_502"),
        (400, b'{"code":"x"}', "http_400"),
        (400, b'{"code":true}', "http_400"),
        (418, b"", "http_418"),
    ],
)
def test_error_reason_carries_code_not_text(status: int, detail: bytes, name: str) -> None:
    """Plan A-7: yalnız durum ve Binance'in sayısal kodu; Binance'in metni alınmaz."""
    reason = error_reason(status, detail)
    assert reason == name and "msg" not in reason and "Timestamp" not in reason


@pytest.mark.parametrize(
    ("given", "found"),
    [
        (b'{"serverTime":1795000000123}', 1795000000123),
        (b'{"serverTime":"1795000000123"}', None),
        (b'{"serverTime":true}', None),
        (b'{"serverTime":0}', None),
        (b"[]", None),
        (b"<html>", None),
    ],
)
def test_server_time_read(given: bytes, found: int | None) -> None:
    assert server_time(given) == found
