"""Haber/duyuru kaynaklarını takip edip haber skoru üretmek.

Spec 0046: ileriye dönük haber toplama — ayardaki kaynaklardan (Binance duyuruları, RSS 2.0, Atom)
haberler `interval_minutes` aralıkla kendi SQLite deposuna yalnız eklenerek yazılır; her kayıt
kaynağını, yayın anını ve ilk görme anını taşır. Toplama işlem döngüsünden ayrıdır: `news` ticaret
modüllerini import etmez (R-3i), döngüyü giriş noktası bağlar. Skor üretimi sonraki spec'lerin
işidir.

Spec 0047: geçmiş Binance duyuru arşivi — `run_archive` bütün katalogları en eski sayfaya kadar
kendi SQLite deposuna (`ArchiveStore`) yalnız ekleyerek yazar; kayıtlar "arşivden" işaretlidir, ilk
görme anı taşımaz. Durum `archive_status_lines` ile ağsız okunur.
"""

from crytobot.news._archive import (
    PAGE_SIZE,
    ArchiveOutcome,
    ArchiveParts,
    CatalogRun,
    page_url,
    run_archive,
)
from crytobot.news._archive_status import ARCHIVE_EMPTY, NO_FORWARD, archive_status_lines
from crytobot.news._archive_store import (
    ORIGIN,
    ArchiveItem,
    ArchiveStore,
    ArchiveStoreError,
    CatalogState,
    prepare_archive,
    read_archive,
)
from crytobot.news._collect import (
    POSSIBLE_MISS,
    CollectionExit,
    CollectParts,
    SourceRound,
    outage_notice,
    recovery_notice,
    run_collection,
    run_round,
)
from crytobot.news._config import (
    MIN_ARCHIVE_GAP_S,
    MIN_INTERVAL_MINUTES,
    ArchiveConfig,
    ArchiveConfigResult,
    NewsConfig,
    NewsConfigResult,
    NewsSource,
    load_archive_config,
    load_news_config,
)
from crytobot.news._fetch import USER_AGENT, Fetched, Hop, fetch_source
from crytobot.news._items import TEXT_LIMIT_BYTES, NewsItem, RawItem
from crytobot.news._parse import CatalogPage, ParseError, parse_binance_page
from crytobot.news._status import EMPTY, NEVER, status_lines
from crytobot.news._store import (
    NewsStore,
    SourceState,
    StoreError,
    StoreSnapshot,
    read_snapshot,
)

__all__: list[str] = [
    "ARCHIVE_EMPTY",
    "EMPTY",
    "MIN_ARCHIVE_GAP_S",
    "MIN_INTERVAL_MINUTES",
    "NEVER",
    "NO_FORWARD",
    "ORIGIN",
    "PAGE_SIZE",
    "POSSIBLE_MISS",
    "TEXT_LIMIT_BYTES",
    "USER_AGENT",
    "ArchiveConfig",
    "ArchiveConfigResult",
    "ArchiveItem",
    "ArchiveOutcome",
    "ArchiveParts",
    "ArchiveStore",
    "ArchiveStoreError",
    "CatalogPage",
    "CatalogRun",
    "CatalogState",
    "CollectParts",
    "CollectionExit",
    "Fetched",
    "Hop",
    "NewsConfig",
    "NewsConfigResult",
    "NewsItem",
    "NewsSource",
    "NewsStore",
    "ParseError",
    "RawItem",
    "SourceRound",
    "SourceState",
    "StoreError",
    "StoreSnapshot",
    "archive_status_lines",
    "fetch_source",
    "load_archive_config",
    "load_news_config",
    "outage_notice",
    "page_url",
    "parse_binance_page",
    "prepare_archive",
    "read_archive",
    "read_snapshot",
    "recovery_notice",
    "run_archive",
    "run_collection",
    "run_round",
    "status_lines",
]
