"""Spec 0046 AC-6: durum satırları — kaynak başına son başarı, son hata, kayıt sayısı; toplam
boyut; hiç başarılı olmamış kaynak; boş kayıt."""

from datetime import timedelta
from pathlib import Path

from crytobot.news import EMPTY, NEVER, Fetched, read_snapshot, status_lines
from tests.news.test_collect import START, Harness, make_config, source_table


def test_status_per_source_and_size(tmp_path: Path) -> None:
    harness = Harness(
        tmp_path,
        make_config(
            tmp_path,
            source_table("coindesk"),
            source_table("atom"),
            source_table("kapalı", enabled=False),
        ),
    )
    harness.round()
    harness.responses["atom"] = Fetched(error="http_404")
    harness.round()
    snapshot = read_snapshot(harness.config.store_path)
    assert snapshot is not None
    lines = status_lines(harness.config, snapshot)
    assert lines[0] == (
        f"kaynak=coindesk son_başarı={(START + timedelta(seconds=6)).isoformat()} son_hata=yok"
        " kayıt=3"
    )
    assert lines[1] == (
        f"kaynak=atom son_başarı={(START + timedelta(seconds=4)).isoformat()}"
        f" son_hata=http_404@{(START + timedelta(seconds=8)).isoformat()} kayıt=2"
    )
    assert lines[2] == f"kaynak=kapalı (kapalı) son_başarı={NEVER} son_hata=yok kayıt=0"
    assert lines[3].startswith("toplam: kayıt=5 boyut=")
    assert snapshot.size_bytes > 0
    assert f"boyut={snapshot.size_bytes} bayt" in lines[3]


def test_never_succeeded_shown(tmp_path: Path) -> None:
    harness = Harness(tmp_path, make_config(tmp_path, source_table("coindesk")))
    harness.responses["coindesk"] = Fetched(error="timeout")
    harness.round()
    lines = status_lines(harness.config, read_snapshot(harness.config.store_path))
    assert lines[0] == (
        f"kaynak=coindesk son_başarı={NEVER}"
        f" son_hata=timeout@{(START + timedelta(seconds=2)).isoformat()} kayıt=0"
    )
    assert lines[1].startswith(f"{EMPTY} boyut=")


def test_empty_store_exit_0(tmp_path: Path) -> None:
    """Depo yoksa dosya oluşturulmaz, satırlar boş kaydı söyler (çıkış kodu giriş noktası
    testinde)."""
    config = make_config(tmp_path, source_table("coindesk"))
    assert read_snapshot(config.store_path) is None
    assert not Path(config.store_path).exists()
    assert status_lines(config, None) == [
        f"kaynak=coindesk son_başarı={NEVER} son_hata=yok kayıt=0",
        f"{EMPTY} boyut=0 bayt",
    ]
