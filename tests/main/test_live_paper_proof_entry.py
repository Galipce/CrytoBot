"""Spec 0038 CB-2, CB-5, PB-2 (plan Adım 5): `start --live`'da paper kanıtı kapısının yeri.

Sıra: ayar ve rapor kapıları → paper kanıtı → kimlik ve yetki (ağa çıkan tek adım). Paper kanıtı
reddi borsaya hiç istek göndermez, canlı depoya ve kilide dokunmaz, çıkış kodu 1'dir; testnet'te
aynıdır. Geçen canlı başlatmanın satırı paper kanıtını konsolda ve kayıt dosyasında taşır.
"""

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, run
from crytobot.app import StopRequest, prepare_live_store
from tests.app.test_live_start import NOW, FakeLiveClient, write_test_config
from tests.app.test_paper_proof import proof_store


class SpyClient(FakeLiveClient):
    """Her genel çağrıyı sırasıyla yazar: kapı reddinde liste boş kalmalı."""

    def __init__(self) -> None:
        super().__init__(free_balance=Decimal(1000))
        self.calls: list[str] = []

    def __getattribute__(self, name: str) -> Any:
        value = super().__getattribute__(name)
        if callable(value) and not name.startswith("_"):
            object.__getattribute__(self, "calls").append(name)
        return value


def live_dir(root: Path, *, testnet: bool = False) -> tuple[Path, Path]:
    """Hazır canlı depo ve kanıtlı paper deposuyla ayar dosyası."""
    config = write_test_config(root, mode="live", testnet=testnet)
    prepare_live_store(
        (root / "bot.db").as_posix(), NOW, live_client=FakeLiveClient(free_balance=Decimal(1000))
    )
    return config, root / "paper.sqlite"


def start_live(config: Path, client: object, *, stopped: bool = False) -> tuple[int, str]:
    out = io.StringIO()
    stop = StopRequest()
    if stopped:
        stop.request("test")
    code = run(["start", "--live"], config_path=config, console=out, live_client=client, stop=stop)
    return code, out.getvalue()


def test_a_refused_paper_proof_sends_nothing_and_touches_no_live_store(tmp_path: Path) -> None:
    config, paper = live_dir(tmp_path)
    paper.unlink()
    live = tmp_path / "bot.db"
    before = live.read_bytes()
    client = SpyClient()

    code, console = start_live(config, client)

    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: paper kanıtı: paper deposu yok" in console
    assert client.calls == []
    assert live.read_bytes() == before
    assert not (tmp_path / "bot.db.lock").exists()
    assert not (tmp_path / "bot.log").exists()
    assert not paper.exists()


def test_testnet_takes_the_same_gate(tmp_path: Path) -> None:
    """CB-5: testnet'te atlama yolu yok."""
    config, paper = live_dir(tmp_path, testnet=True)
    paper.unlink()
    client = SpyClient()

    code, console = start_live(config, client)

    assert code == EXIT_REFUSED
    assert "paper kanıtı: paper deposu yok" in console
    assert "Testnet" not in console
    assert client.calls == []


def test_the_report_gate_comes_before_the_paper_proof(tmp_path: Path) -> None:
    config, paper = live_dir(tmp_path)
    paper.unlink()
    (tmp_path / "report.txt").unlink()

    code, console = start_live(config, SpyClient())

    assert code == EXIT_REFUSED
    assert "paper kanıtı" not in console


def test_the_paper_proof_comes_before_credentials(tmp_path: Path) -> None:
    """Kimlik yüklenmeden (istemci verilmeden) paper reddi gelir: ağa çıkan adım en sondadır."""
    config, paper = live_dir(tmp_path)
    paper.unlink()

    code, console = start_live(config, None)

    assert code == EXIT_REFUSED
    assert "paper kanıtı: paper deposu yok" in console


def test_an_approval_before_the_paper_result_is_refused(tmp_path: Path) -> None:
    config, paper = live_dir(tmp_path)
    paper.unlink()
    proof_store(
        paper,
        report=str(tmp_path / "report.txt"),
        last_turn=datetime(2026, 11, 10, tzinfo=UTC),  # after live_approved_at (2026-11-09T20:00)
    )
    client = SpyClient()

    code, console = start_live(config, client)

    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: stage.live_approved_at: onay paper sonucundan önce" in console
    assert client.calls == []


def test_a_missing_paper_setting_is_named(tmp_path: Path) -> None:
    config, _paper = live_dir(tmp_path)
    text = config.read_text(encoding="utf-8")
    kept = [row for row in text.splitlines() if not row.startswith("paper_store_path")]
    config.write_text("\n".join(kept), encoding="utf-8")

    code, console = start_live(config, SpyClient())

    assert code == EXIT_REFUSED
    assert "başlatma reddedildi: ayar eksik: stage.paper_store_path" in console


def test_a_passing_live_start_line_carries_the_paper_proof(tmp_path: Path) -> None:
    """CB-5: konsol ve kayıt dosyasındaki başlatma satırı (plan Risk 5)."""
    config, paper = live_dir(tmp_path)
    client = SpyClient()

    code, console = start_live(config, client, stopped=True)

    assert code == EXIT_OK, console
    assert client.calls[0] == "verify_permissions"
    proof = f"paper={paper.as_posix()} gün=14 işlem=10 net="
    (start_line,) = [row for row in console.splitlines() if " başlatma başladı:" in row]
    assert proof in start_line and start_line.endswith(" açık=0")
    log = (tmp_path / "bot.log").read_text(encoding="utf-8")
    assert proof in log
