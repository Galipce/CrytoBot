"""Skorlama turu ve döngüsü (spec 0051 R-1, R-2, R-6, R-10; plan step 6, Risk 6).

Kararlar burada; gerçek etkiler (saat, ≤1 s'lik bekleme, durdurma, LLM çağrısı, satır yazıcısı) ve
başlangıçta bir kez okunan bağlam ile USDT çiftleri `ScoreParts` ile gelir. `news` `llm`'i import
etmez: çağrıyı giriş noktası verir.

Tur: başlangıç anından sonra (ya da eşit) görülmüş, sonucu olmayan haberler ilk görme anı ve kimlik
sırasıyla. Önce çağrısız geçiş: ilk görme anından 24 saatten çok geçmiş haber "bayat" olur. Sonra
çağrılar; her çağrıdan önce durdurma, tur sınırı, kota beklemesi ve UTC günlük sınır denetlenir.
Çağrı süreç başlamadan sayılır. `ok` yanıt doğrulanır: "skorlandı" ya da "şema dışı" (yinelenmez).
Geçici hata (zaman aşımı, oturum yok, kota, tanınmayan) sonuç yazmaz, turu bitirir; haber sonraki
turda yeniden denenir. Kayıt dosyasına haber metni, prompt ve yanıt yazılmaz: yalnız kimlik, sonuç,
süre, sayılar ve neden adları.
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from crytobot.news._score_config import ScoreConfig
from crytobot.news._score_prompt import (
    PROMPT_FINGERPRINT,
    SYSTEM_PROMPT,
    ScoreContext,
    build_prompt,
)
from crytobot.news._score_store import (
    CallEnd,
    ResultKind,
    ScoreResult,
    ScoreStore,
    ScoreStoreError,
)
from crytobot.news._score_validate import check_reply
from crytobot.news._store import ForwardItem, StoreError, read_forward

STALE_AFTER = timedelta(hours=24)
OK = "ok"
QUOTA = "quota"
STOPPED = "stopped"
QUOTA_WAIT = "kota beklemesi"
DAILY_FULL = "günlük sınır dolu"
ROUND_FULL = "tur sınırı"


@dataclass(frozen=True)
class ScoreReply:
    """Bir LLM çağrısının sonucu, `news`'in diliyle. `outcome`: ok, timeout, no_session, quota,
    unknown ya da stopped; `text` yalnız `ok`'ta."""

    outcome: str
    text: str | None
    overflow: bool
    seconds: float
    workdir_clean: bool


# (model, system prompt, prompt, timeout_s) -> reply
ScoreCall = Callable[[str, str, str, float], ScoreReply]


@dataclass(frozen=True)
class ScoreParts:
    clock: Callable[[], datetime]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    call: ScoreCall
    say: Callable[[str], None]
    context: ScoreContext
    pairs: Collection[str]
    pairs_at: datetime | None = None


class ScoreExit(Enum):
    STOPPED = "stopped"
    STORE_FAILED = "store_failed"


@dataclass
class _Tally:
    pending: int = 0
    calls: int = 0
    scored: int = 0
    schema: int = 0
    stale: int = 0
    failure: str | None = None
    held: str | None = None

    @property
    def line(self) -> str:
        text = (
            f"tur: bekleyen={self.pending} çağrı={self.calls} skorlandı={self.scored}"
            f" şema_dışı={self.schema} bayat={self.stale}"
        )
        if self.failure is not None:
            text += f" hata={self.failure}"
        if self.held is not None:
            text += f" durum={self.held}"
        return text


def _held(config: ScoreConfig, store: ScoreStore, tally: _Tally, now: datetime) -> str | None:
    if tally.calls >= config.max_calls_per_round:
        return ROUND_FULL
    quota_at = store.last_quota_at()
    if quota_at is not None and now < quota_at + timedelta(minutes=config.quota_wait_minutes):
        return QUOTA_WAIT
    if store.calls_on(now.astimezone(UTC).date()) >= config.daily_call_limit:
        return DAILY_FULL
    return None


def _score(
    config: ScoreConfig, store: ScoreStore, parts: ScoreParts, item: ForwardItem, tally: _Tally
) -> bool:
    """Tek haber için tek çağrı; tur sürmeli mi."""
    prompt = build_prompt(parts.context, item.title, item.text)
    call_id = store.begin_call(item.record_id, parts.clock())
    tally.calls += 1
    reply = parts.call(config.model, SYSTEM_PROMPT, prompt.text, float(config.timeout_s))
    at = parts.clock()
    end = CallEnd(reply.outcome, reply.seconds, at)
    folder = "boş" if reply.workdir_clean else "boş değil"
    head = f"çağrı: haber={item.record_id} kaynak={item.source} süre={reply.seconds:.1f}s"
    if reply.outcome != OK:
        store.end_call(call_id, end)
        tally.failure = reply.outcome
        parts.say(f"{head} sonuç={reply.outcome} klasör={folder}")
        return False
    checked = check_reply(reply.text, reply.overflow, prompt.title, prompt.body, parts.pairs)
    common = (config.model, PROMPT_FINGERPRINT, parts.context.fingerprint)
    if checked.schema_reason is not None:
        result = ScoreResult(
            item.record_id,
            ResultKind.SCHEMA,
            at,
            *common,
            schema_reason=checked.schema_reason,
            reply_size=checked.size,
        )
        store.write_result(result, call_id, end)
        tally.schema += 1
        parts.say(
            f"{head} sonuç={ResultKind.SCHEMA.value} neden={checked.schema_reason}"
            f" boyut={checked.size} klasör={folder}"
        )
        return True
    store.write_result(
        ScoreResult(
            item.record_id,
            ResultKind.SCORED,
            at,
            *common,
            scores=checked.scores,
            rejections=checked.rejections,
            reply_size=checked.size,
        ),
        call_id,
        end,
    )
    tally.scored += 1
    rejected = "".join(f" ret[{reason}]={count}" for reason, count in checked.rejections)
    parts.say(
        f"{head} sonuç={ResultKind.SCORED.value} skor={len(checked.scores)}{rejected}"
        f" klasör={folder}"
    )
    return True


def run_score_round(config: ScoreConfig, store: ScoreStore, parts: ScoreParts) -> bool:
    """Bir tur; durdurmayla kesildiyse `False`."""
    tally = _Tally()
    items = read_forward(config.news.store_path, store.started_at)
    if items is None:
        raise StoreError("haber kaydı yok")
    done = store.resulted()
    pending: list[ForwardItem] = []
    for item in items:
        if item.record_id in done:
            continue
        now = parts.clock()
        if now - item.first_seen > STALE_AFTER:
            store.write_result(ScoreResult(item.record_id, ResultKind.STALE, now))
            tally.stale += 1
            parts.say(f"bayat: haber={item.record_id} kaynak={item.source} çağrı yok")
        else:
            pending.append(item)
    tally.pending = len(pending)
    finished = True
    for item in pending:
        if parts.stopped():
            finished = False
            break
        tally.held = _held(config, store, tally, parts.clock())
        if tally.held is not None:
            break
        if not _score(config, store, parts, item, tally):
            finished = tally.failure != STOPPED
            break
    parts.say(tally.line)
    return finished


def run_scoring(config: ScoreConfig, store: ScoreStore, parts: ScoreParts) -> ScoreExit:
    """Durdurulana kadar `interval_minutes` aralıkla turlar (R-1)."""
    snapshot = "yok" if parts.pairs_at is None else parts.pairs_at.isoformat()
    parts.say(
        f"başladı: model={config.model} aralık={config.interval_minutes}dk"
        f" başlangıç={store.started_at.isoformat()} prompt={PROMPT_FINGERPRINT}"
        f" bağlam={parts.context.fingerprint} borsa_bilgisi={snapshot}"
        f" usdt_çifti={len(parts.pairs)} günlük_sınır={config.daily_call_limit}"
    )
    interval = timedelta(minutes=config.interval_minutes)
    rounds = 0
    try:
        while not parts.stopped():
            started = parts.clock()
            finished = run_score_round(config, store, parts)
            if finished:
                rounds += 1
            if not finished or parts.stopped():
                break
            left = (started + interval - parts.clock()).total_seconds()
            if left > 0:
                parts.wait(left)
    except (StoreError, ScoreStoreError) as error:
        parts.say(f"durdu: {error} tur_sayısı={rounds}")
        return ScoreExit.STORE_FAILED
    parts.say(f"durdu: durdurma isteği tur_sayısı={rounds}")
    return ScoreExit.STOPPED
