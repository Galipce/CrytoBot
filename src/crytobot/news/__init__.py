"""Haber/duyuru kaynaklarını takip edip haber skoru üretmek.

Spec 0046: ileriye dönük haber toplama — ayardaki kaynaklardan (Binance duyuruları, RSS 2.0, Atom)
haberler `interval_minutes` aralıkla kendi SQLite deposuna yalnız eklenerek yazılır; her kayıt
kaynağını, yayın anını ve ilk görme anını taşır. Toplama işlem döngüsünden ayrıdır: `news` ticaret
modüllerini import etmez (R-3i), döngüyü giriş noktası bağlar. Skor üretimi sonraki spec'lerin
işidir.
"""

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
    MIN_INTERVAL_MINUTES,
    NewsConfig,
    NewsConfigResult,
    NewsSource,
    load_news_config,
)
from crytobot.news._fetch import USER_AGENT, Fetched, Hop, fetch_source
from crytobot.news._items import TEXT_LIMIT_BYTES, NewsItem, RawItem
from crytobot.news._status import EMPTY, NEVER, status_lines
from crytobot.news._store import (
    NewsStore,
    SourceState,
    StoreError,
    StoreSnapshot,
    read_snapshot,
)

__all__: list[str] = [
    "EMPTY",
    "MIN_INTERVAL_MINUTES",
    "NEVER",
    "POSSIBLE_MISS",
    "TEXT_LIMIT_BYTES",
    "USER_AGENT",
    "CollectParts",
    "CollectionExit",
    "Fetched",
    "Hop",
    "NewsConfig",
    "NewsConfigResult",
    "NewsItem",
    "NewsSource",
    "NewsStore",
    "RawItem",
    "SourceRound",
    "SourceState",
    "StoreError",
    "StoreSnapshot",
    "fetch_source",
    "load_news_config",
    "outage_notice",
    "read_snapshot",
    "recovery_notice",
    "run_collection",
    "run_round",
    "status_lines",
]
