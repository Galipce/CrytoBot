"""Haber/duyuru kaynaklarını takip edip haber skoru üretmek.

Spec 0046: ileriye dönük haber toplama — ayardaki kaynaklardan (Binance duyuruları, RSS 2.0, Atom)
haberler `interval_minutes` aralıkla kendi SQLite deposuna yalnız eklenerek yazılır; her kayıt
kaynağını, yayın anını ve ilk görme anını taşır. Toplama işlem döngüsünden ayrıdır: `news` ticaret
modüllerini import etmez (R-3i), döngüyü giriş noktası bağlar. Skor üretimi sonraki spec'lerin
işidir.

Spec 0047: geçmiş Binance duyuru arşivi — `run_archive` bütün katalogları en eski sayfaya kadar
kendi SQLite deposuna (`ArchiveStore`) yalnız ekleyerek yazar; kayıtlar "arşivden" işaretlidir, ilk
görme anı taşımaz. Durum `archive_status_lines` ile ağsız okunur.

Spec 0048: örnek kütüphanesinin girdisi — `label` başlığa sabit kurallarla olay türü, beklenen yön
ve coinler atar (`EVENT_TYPES`, `RULES_FINGERPRINT`); `read_library_sources` arşivi ve ileriye dönük
kaydın `binance-duyuru` kayıtlarını yalnız okur, kimliğe göre birleştirir ve etiketler.

Spec 0051: LLM olay skoru, gölge mod — `run_scoring` ileriye dönük kayıttaki yeni haberleri
(`read_forward`) prompt'a (`build_prompt`, bağlam `load_context`) koyar, çağrıyı giriş noktasından
alır (`ScoreParts.call`; `news` `llm`'i import etmez), yanıtı doğrular (`check_reply`) ve kendi
yalnız eklenen kaydına (`ScoreStore`) yazar. Durum `score_status_lines` ile ağsız, LLM'siz okunur.

Spec 0052: gölge filtre görünümü — `read_filter_view` skor ve haber kaydını yalnız okuyup bir paper
turu anında coin başına filtre durumunu (`FilterState`) verir; skorlayıcı her turda canlılık izini
(`ScoreStore.mark_round`) yazar. Bot görünümü giriş noktasının verdiği işlevle alır.
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
from crytobot.news._labels import (
    EVENT_TYPES,
    RULES_FINGERPRINT,
    Label,
    label,
    title_pattern,
)
from crytobot.news._library_sources import (
    FROM_ARCHIVE,
    FROM_BOTH,
    FROM_FORWARD,
    LibraryAnnouncement,
    LibrarySources,
    read_library_sources,
)
from crytobot.news._parse import CatalogPage, ParseError, parse_binance_page
from crytobot.news._score_config import (
    DAILY_CALL_HARD_CAP,
    INTERVAL_CAP_MINUTES,
    ScoreConfig,
    ScoreConfigResult,
    load_score_config,
)
from crytobot.news._score_prompt import (
    PROMPT_FINGERPRINT,
    SYSTEM_PROMPT,
    ContextError,
    ScoreContext,
    ScorePrompt,
    build_prompt,
    context_fingerprint,
    load_context,
)
from crytobot.news._score_run import (
    ScoreCall,
    ScoreExit,
    ScoreParts,
    ScoreReply,
    run_score_round,
    run_scoring,
)
from crytobot.news._score_status import NO_SCORES, score_status_lines
from crytobot.news._score_store import (
    CallEnd,
    EventScore,
    ResultKind,
    ScoreResult,
    ScoreSnapshot,
    ScoreStore,
    ScoreStoreError,
    read_score_snapshot,
)
from crytobot.news._score_validate import Checked, check_reply
from crytobot.news._shadow_view import (
    CoinFilter,
    EventRef,
    FilterState,
    MissingCounts,
    ScoreReadout,
    base_of,
    filter_view,
    read_filter_view,
    read_score_readout,
)
from crytobot.news._status import EMPTY, NEVER, status_lines
from crytobot.news._store import (
    ForwardItem,
    NewsStore,
    SourceState,
    StoreError,
    StoreSnapshot,
    read_forward,
    read_snapshot,
)

__all__: list[str] = [
    "ARCHIVE_EMPTY",
    "DAILY_CALL_HARD_CAP",
    "EMPTY",
    "EVENT_TYPES",
    "FROM_ARCHIVE",
    "FROM_BOTH",
    "FROM_FORWARD",
    "INTERVAL_CAP_MINUTES",
    "MIN_ARCHIVE_GAP_S",
    "MIN_INTERVAL_MINUTES",
    "NEVER",
    "NO_FORWARD",
    "NO_SCORES",
    "ORIGIN",
    "PAGE_SIZE",
    "POSSIBLE_MISS",
    "PROMPT_FINGERPRINT",
    "RULES_FINGERPRINT",
    "SYSTEM_PROMPT",
    "TEXT_LIMIT_BYTES",
    "USER_AGENT",
    "ArchiveConfig",
    "ArchiveConfigResult",
    "ArchiveItem",
    "ArchiveOutcome",
    "ArchiveParts",
    "ArchiveStore",
    "ArchiveStoreError",
    "CallEnd",
    "CatalogPage",
    "CatalogRun",
    "CatalogState",
    "Checked",
    "CoinFilter",
    "CollectParts",
    "CollectionExit",
    "ContextError",
    "EventRef",
    "EventScore",
    "Fetched",
    "FilterState",
    "ForwardItem",
    "Hop",
    "Label",
    "LibraryAnnouncement",
    "LibrarySources",
    "MissingCounts",
    "NewsConfig",
    "NewsConfigResult",
    "NewsItem",
    "NewsSource",
    "NewsStore",
    "ParseError",
    "RawItem",
    "ResultKind",
    "ScoreCall",
    "ScoreConfig",
    "ScoreConfigResult",
    "ScoreContext",
    "ScoreExit",
    "ScoreParts",
    "ScorePrompt",
    "ScoreReadout",
    "ScoreReply",
    "ScoreResult",
    "ScoreSnapshot",
    "ScoreStore",
    "ScoreStoreError",
    "SourceRound",
    "SourceState",
    "StoreError",
    "StoreSnapshot",
    "archive_status_lines",
    "base_of",
    "build_prompt",
    "check_reply",
    "context_fingerprint",
    "fetch_source",
    "filter_view",
    "label",
    "load_archive_config",
    "load_context",
    "load_news_config",
    "load_score_config",
    "outage_notice",
    "page_url",
    "parse_binance_page",
    "prepare_archive",
    "read_archive",
    "read_filter_view",
    "read_forward",
    "read_library_sources",
    "read_score_readout",
    "read_score_snapshot",
    "read_snapshot",
    "recovery_notice",
    "run_archive",
    "run_collection",
    "run_round",
    "run_score_round",
    "run_scoring",
    "score_status_lines",
    "status_lines",
    "title_pattern",
]
