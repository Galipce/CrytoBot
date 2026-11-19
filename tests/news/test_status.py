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


def test_stream_status_fields(tmp_path: Path) -> None:
    """Spec 0056 AC-8: akış kaynağının satırında kayıttaki bağlantı durumu; tur yazmadan hiç
    bağlanmadı."""
    from dataclasses import replace

    from crytobot.news import NewsStore, SourceState, StreamState

    stream = {**source_table("akış", "binance-akış"), "url": "wss://api.binance.com/sapi/wss"}
    harness = Harness(tmp_path, make_config(tmp_path, stream, source_table("coindesk")))
    harness.round()  # coindesk only: the stream source has no view here and is written `kopuk`
    snapshot = read_snapshot(harness.config.store_path)
    assert snapshot is not None
    first = status_lines(harness.config, snapshot)[0]
    assert first.endswith(
        " bağlantı=hiç bağlanmadı son_bağlantı=yok kopukluk_başı=yok kopukluk_toplam=0s"
    )
    assert "kopukluk" not in status_lines(harness.config, snapshot)[1]
    store = NewsStore.open(harness.config.store_path)
    try:
        state = replace(SourceState(), last_success_at=START)
        store.write("akış", [], state, StreamState(True, START, None, 42))
    finally:
        store.close()
    snapshot = read_snapshot(harness.config.store_path)
    assert snapshot is not None
    assert status_lines(harness.config, snapshot)[0].endswith(
        f" bağlantı=bağlı son_bağlantı={START.isoformat()} kopukluk_başı=yok kopukluk_toplam=42s"
    )
    store = NewsStore.open(harness.config.store_path)
    try:
        gap = START + timedelta(hours=1)
        store.write("akış", [], state, StreamState(False, START, gap, 50))
    finally:
        store.close()
    snapshot = read_snapshot(harness.config.store_path)
    assert snapshot is not None
    assert status_lines(harness.config, snapshot)[0].endswith(
        f" bağlantı=kopuk son_bağlantı={START.isoformat()} kopukluk_başı={gap.isoformat()}"
        " kopukluk_toplam=50s"
    )


def test_old_record_without_stream_table_readable(tmp_path: Path) -> None:
    """Plan Risk 4: eski koddan kalan kayıtta `stream_state` yoktur; durum okunur."""
    import sqlite3

    harness = Harness(tmp_path, make_config(tmp_path, source_table("coindesk")))
    harness.round()
    with sqlite3.connect(harness.config.store_path) as connection:
        connection.execute("DROP TABLE stream_state")
    snapshot = read_snapshot(harness.config.store_path)
    assert snapshot is not None and snapshot.sources["coindesk"].stream is None
