"""Spec 0056 AC-1, AC-7: anahtarlar yalnız ortamdan ya da `.env`'den; ad söylenir, değer asla."""

from pathlib import Path

import pytest

from crytobot.news._secrets import MASK, SecretsError, StreamKeys, load_stream_keys, redact

KEY = "k3y-VALUE-0123456789"
SECRET = "s3cr3t-VALUE-9876543210"


def test_environment_wins_over_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text('# yorum\nK="from-file"\nS=file-secret # not\n', encoding="utf-8")
    keys = load_stream_keys("K", "S", env={"K": KEY}, env_file=env_file)
    assert keys.values == (KEY, "file-secret")
    keys = load_stream_keys("K", "S", env={}, env_file=env_file)
    assert keys.values == ("from-file", "file-secret")


@pytest.mark.parametrize(
    ("env", "file_text", "missing"),
    [
        ({}, "", "K"),
        ({"K": KEY}, "", "S"),
        ({"K": "   ", "S": SECRET}, "", "K"),
        ({"K": KEY}, "S=\n", "S"),
    ],
)
def test_missing_or_empty_named_without_value(
    tmp_path: Path, env: dict[str, str], file_text: str, missing: str
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(file_text, encoding="utf-8")
    with pytest.raises(SecretsError) as raised:
        load_stream_keys("K", "S", env=env, env_file=env_file)
    assert raised.value.message == f"ortam değişkeni yok: {missing}"
    assert KEY not in str(raised.value) and SECRET not in str(raised.value)


def test_unreadable_file_is_empty(tmp_path: Path) -> None:
    with pytest.raises(SecretsError):
        load_stream_keys("K", "S", env={}, env_file=tmp_path / "yok.env")


def test_masked_repr() -> None:
    keys = StreamKeys(KEY, SECRET)
    for text in (repr(keys), str(keys), f"{keys}", repr([keys])):
        assert KEY not in text and SECRET not in text and MASK in text
    assert redact(f"hata: {KEY} ve {SECRET}", keys) == f"hata: {MASK} ve {MASK}"
    assert redact("düz", None) == "düz"
