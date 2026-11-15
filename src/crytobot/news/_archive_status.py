"""Arşiv durum satırları (spec 0047 R-8, AC-8): ağsız, kilitsiz; arşiv ve ileriye dönük haber kaydı
yalnız okunur (yalnız SELECT, dosya oluşturulmaz; plan A-2). Katalog başına kayıt, son bildirilen
toplam ve fark, en eski ve en yeni yayın anı, tamam/eksik, son hata, son çalıştırma; keşifte artık
görünmeyen katalog "listede yok". Sonda toplam kayıt, boyut (depo + WAL) ve ileriye dönük kayıtla
örtüşme (`binance-duyuru` türü kaynakların `id:<kimlik>` anahtarları; plan Risk 9, G-5)."""

from datetime import datetime

from crytobot.news._archive_store import (
    ArchiveSnapshot,
    CatalogSummary,
    forward_binance_ids,
    read_archive,
)
from crytobot.news._config import ArchiveConfig
from crytobot.news._store import store_size

ARCHIVE_EMPTY = "arşiv boş"
NO_FORWARD = "ileriye dönük kayıt yok"
_NONE = "yok"


def _at(moment: datetime | None) -> str:
    return _NONE if moment is None else moment.isoformat()


def _catalog_line(summary: CatalogSummary) -> str:
    state = summary.state
    total = state.reported_total
    reported = _NONE if total is None else str(total)
    difference = _NONE if total is None else str(total - summary.records)
    text = (
        f"katalog={state.name} kayıt={summary.records} bildirilen={reported} fark={difference}"
        f" en_eski={_at(summary.oldest)} en_yeni={_at(summary.newest)}"
        f" {'tamam' if state.complete else 'eksik'}"
        f" son_hata={state.last_error or _NONE} son_çalıştırma={_at(state.last_run_at)}"
    )
    return text if state.listed else f"{text} (listede yok)"


def _overlap(config: ArchiveConfig, snapshot: ArchiveSnapshot) -> str:
    sources = [source.name for source in config.news.sources if source.kind == "binance-duyuru"]
    forward = forward_binance_ids(config.news.store_path, sources)
    if forward is None:
        return NO_FORWARD
    return f"örtüşme={len(snapshot.article_ids & forward)}"


def archive_status_lines(config: ArchiveConfig) -> list[str]:
    """`ArchiveStoreError`: arşiv ya da ileriye dönük kayıt okunamıyor."""
    snapshot = read_archive(config.store_path)
    size = store_size(config.store_path)
    if snapshot is None:
        return [f"{ARCHIVE_EMPTY} boyut={size} bayt"]
    lines = [_catalog_line(summary) for summary in snapshot.catalogs]
    if snapshot.records == 0:
        return [*lines, f"{ARCHIVE_EMPTY} boyut={size} bayt"]
    lines.append(
        f"arşiv: kayıt={snapshot.records} boyut={size} bayt ({size / 1024:.1f} KB)"
        f" son_çalıştırma={_at(snapshot.last_run_at)} {_overlap(config, snapshot)}"
    )
    return lines
