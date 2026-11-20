"""Spec 0059 AC-7: durum satırları; kayıt yoksa "henüz tur yok"."""

from pathlib import Path

from crytobot.decide import (
    NO_TURNS,
    PROMPT_FINGERPRINT,
    DecideConfig,
    DecideStore,
    Decision,
    Status,
    Turn,
    decide_status_lines,
    load_decide_config,
    read_decide_snapshot,
)
from tests.decide.helpers import BOUNDARY, HOUR
from tests.decide.test_config import document


def config() -> DecideConfig:
    loaded = load_decide_config(document()).config
    assert loaded is not None
    return loaded


def test_no_record_said() -> None:
    lines = decide_status_lines(config(), None, BOUNDARY.date())
    assert lines[-1] == NO_TURNS == "henüz tur yok"


def test_status_lines(tmp_path: Path) -> None:
    path = str(tmp_path / "decide.db")
    store = DecideStore.open(path)
    buy = Decision("SOL", Status.BUY, 98.0, 100.0, 95.0, 105.0, 4, 3, ("a",), action="al")
    schema = Decision("ETH", Status.SCHEMA, reason="JSON değil")
    store.write(Turn(BOUNDARY, "m", PROMPT_FINGERPRINT, None, "ok", True, (buy,)))
    store.write(
        Turn(
            BOUNDARY + HOUR,
            "m",
            PROMPT_FINGERPRINT,
            None,
            "şema dışı",
            True,
            (schema,),
            "JSON değil",
        )
    )
    store.close()
    snapshot = read_decide_snapshot(path, BOUNDARY.date())
    lines = decide_status_lines(config(), snapshot, BOUNDARY.date())
    text = "\n".join(lines)
    assert "bugünkü çağrı (UTC 2026-11-20): 2/24" in text
    assert "2026-11-20T11:00:00+00:00 sonuç=şema dışı çağrı=var neden=JSON değil" in text
    assert "  SOL: al (2026-11-20T10:00:00+00:00) giriş=98-100 stop=95 hedef=105" in text
    assert "  ETH: şema dışı (2026-11-20T11:00:00+00:00) neden=JSON değil" in text
    assert lines[-1] == "toplam: al=1 bekle=0 tutarsız=0 veri_yok=0 şema_dışı=1"
