"""Karar turu ve döngüsü (spec 0059 R-2…R-6, AC-3, AC-6, AC-8; G-4…G-6; plan Risk 6).

Kararlar burada, gerçek etkiler (saat, bekleme, durdurma, piyasa okuması, Claude çağrısı, bildirim,
satır yazıcısı) `DecideParts` ile gelir. Tur, 1h sınırından `minute_after_close` dakika sonra koşar;
aynı sınır için ikinci tur yoktur (kayıtta varsa atlanır). Tur başına tek çağrı; UTC günündeki çağrı
sayısı sınırdaysa çağrı yapılmaz (`sınır`); kota yanıtından sonra `quota_wait_minutes` çağrısız
(`kota bekleniyor`). Verisi olmayan coin `veri yok` olur; hiçbir coinin verisi yoksa çağrı yapılmaz.
Yeniden sorma ya da "en iyisini seçme" yoktur (G-6). Süreç turun anından `LATE_LIMIT`'ten geç
başlarsa (ya da uyanırsa) o sınırın turu atlanır, satırı yazılır: kararın verisi bayatlamıştır.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from crytobot.decide._config import DecideConfig
from crytobot.decide._notice import buy_notice
from crytobot.decide._prompt import PROMPT_FINGERPRINT, SYSTEM_PROMPT, build_prompt
from crytobot.decide._store import DecideStore, DecideStoreError, Turn
from crytobot.decide._summary import HOUR, CoinData, CoinSummary, summarize
from crytobot.decide._validate import Decision, Status, check_reply

CONTEXT_COIN: Final = "BTC"
LATE_LIMIT: Final = timedelta(minutes=15)
OK: Final = "ok"


@dataclass(frozen=True)
class DecideReply:
    """`outcome`: `ok`, `timeout`, `no_session`, `quota`, `unknown`, `stopped` (0051 sınıfları)."""

    outcome: str
    text: str | None


@dataclass(frozen=True)
class DecideParts:
    """`read`: coin → veri (okunamayan `None`), turun sınırıyla; `notify` yoksa yalnız satır."""

    clock: Callable[[], datetime]
    wait: Callable[[float], None]
    stopped: Callable[[], bool]
    read: Callable[[tuple[str, ...], datetime], Mapping[str, CoinData | None]]
    call: Callable[[str, str, str, float], DecideReply]
    say: Callable[[str], None]
    notify: Callable[[str], str | None] | None = None


class DecideExit(Enum):
    STOPPED = "stopped"
    STORE_FAILED = "store_failed"


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _counts(decisions: tuple[Decision, ...]) -> str:
    names = (Status.BUY, Status.WAIT, Status.INCONSISTENT, Status.NO_DATA, Status.SCHEMA)
    return " ".join(
        f"{name.value.replace(' ', '_')}={sum(d.status is name for d in decisions)}"
        for name in names
    )


def run_turn(
    config: DecideConfig, store: DecideStore, parts: DecideParts, boundary: datetime
) -> Turn:
    """Bir sınırın turu; kayda yazılacak `Turn` (yazmaz)."""
    data = parts.read(config.coins, boundary)
    summaries: list[CoinSummary] = []
    missing: list[Decision] = []
    for coin in config.coins:
        coin_data = data.get(coin)
        summary = None if coin_data is None else summarize(coin_data, boundary)
        if summary is None:
            missing.append(Decision(coin, Status.NO_DATA, reason="veri yok"))
        else:
            summaries.append(summary)

    def turn(
        outcome: str, called: bool, decided: tuple[Decision, ...] | None = None, **extra: object
    ) -> Turn:
        if decided is None:  # no decision this turn: every asked coin waits, the reason named
            decided = tuple(Decision(s.coin, Status.WAIT, reason=outcome) for s in summaries)
        return Turn(
            boundary,
            config.model,
            PROMPT_FINGERPRINT,
            extra.get("input_fingerprint"),  # type: ignore[arg-type]
            outcome,
            called,
            (*decided, *missing),
            extra.get("reason"),  # type: ignore[arg-type]
            extra.get("ended_at"),  # type: ignore[arg-type]
        )

    if not summaries:
        return turn("veri yok", False)
    now = parts.clock()
    quota_at = store.last_quota_at()
    if quota_at is not None and now < quota_at + timedelta(minutes=config.quota_wait_minutes):
        return turn("kota bekleniyor", False)
    if store.calls_on(now.date()) >= config.daily_call_limit:
        return turn("sınır", False)
    context = next((s for s in summaries if s.coin == CONTEXT_COIN), None)
    prompt = build_prompt(summaries, context, boundary)
    reply = parts.call(config.model, SYSTEM_PROMPT, prompt.text, float(config.timeout_s))
    ended = parts.clock()
    if reply.outcome != OK:
        return turn(reply.outcome, True, input_fingerprint=prompt.input_fingerprint, ended_at=ended)
    checked = check_reply(reply.text, {s.coin: (s.low, s.high) for s in summaries})
    outcome = OK if checked.schema_reason is None else Status.SCHEMA.value
    return turn(
        outcome,
        True,
        checked.decisions,
        input_fingerprint=prompt.input_fingerprint,
        reason=checked.schema_reason,
        ended_at=ended,
    )


def _notify(parts: DecideParts, turn: Turn) -> None:
    for decision in turn.decisions:
        text = buy_notice(decision, turn.at)
        if text is None:
            continue
        parts.say(f"bildirim: {decision.coin} al")
        if parts.notify is not None:
            try:
                error = parts.notify(text)
            except Exception:  # reporting never stops the decision loop
                parts.say("bildirim iletilemedi")
                continue
            if error is not None:
                parts.say(f"bildirim kuyrukta ({error})")


def run_decide(config: DecideConfig, store: DecideStore, parts: DecideParts) -> DecideExit:
    """Durdurulana kadar saatte bir tur (R-3, AC-8)."""
    parts.say(
        f"başladı: model={config.model} coin={len(config.coins)} dakika={config.minute_after_close}"
        f" günlük_sınır={config.daily_call_limit} kayıt={config.store_path}"
    )
    after = timedelta(minutes=config.minute_after_close)
    turns = 0
    try:
        while not parts.stopped():
            now = parts.clock()
            boundary = floor_hour(now)
            if now < boundary + after:
                parts.wait((boundary + after - now).total_seconds())
                continue
            if now > boundary + after + LATE_LIMIT and not store.has_turn(boundary):
                parts.say(f"tur atlandı: an={boundary.isoformat()} geç kalındı")
            elif not store.has_turn(boundary):
                turn = run_turn(config, store, parts, boundary)
                if parts.stopped() and turn.outcome == "stopped":
                    break
                store.write(turn)
                turns += 1
                parts.say(
                    f"tur: an={boundary.isoformat()} sonuç={turn.outcome}"
                    f" çağrı={'var' if turn.called else 'yok'} {_counts(turn.decisions)}"
                    + ("" if turn.reason is None else f" neden={turn.reason}")
                )
                _notify(parts, turn)
            left = (boundary + HOUR + after - parts.clock()).total_seconds()
            if left > 0:
                parts.wait(left)
    except DecideStoreError as error:
        parts.say(f"durdu: {error} tur_sayısı={turns}")
        return DecideExit.STORE_FAILED
    parts.say(f"durdu: durdurma isteği tur_sayısı={turns}")
    return DecideExit.STOPPED
