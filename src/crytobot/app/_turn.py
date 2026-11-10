"""`run_turn`: tek paper turu, sırası ve en dış hata ağı (spec 0016 R-1, R-11, R-13)."""

from collections.abc import Callable, Mapping
from datetime import datetime

from crytobot.app._buys import buy_pairs
from crytobot.app._closes import close_positions, resolve_unknown, sync_exchange_stops
from crytobot.app._inputs import TurnSettings, aware, read_market, settings_problem
from crytobot.app._notices import NoticeKind, Notices, TurnMemory, TurnNotice
from crytobot.app._result import BuyHalt, TurnOutcome, TurnResult
from crytobot.app._session import KillRequest, SaveRefusedError, TurnRun
from crytobot.execution import LIVE, PAPER, BannedError, Exchange, LiveExchange
from crytobot.persistence import load_store


def _refusal(outcome: TurnOutcome, message: str, notices: Notices | None = None) -> TurnResult:
    errors = () if notices is None else tuple(notices.errors)
    return TurnResult(outcome, (), (), (), (), errors, message)


def _unexpected(error: Exception, notices: Notices) -> str:
    """Plan Risk 13: yalnız tip adı; istisna metni sır taşıyabilir."""
    message = f"beklenmeyen hata: {type(error).__name__}"
    notices.enter(NoticeKind.UNEXPECTED_ERROR, "", message)
    return message


def _trade(run: TurnRun) -> TurnResult:
    """R-1: kill isteği → sorgu → borsa stop senk. → mutabakat → gözlem → kapanış → gözlem →
    alım → kill isteği. Spec 0035 AC-11: tur sırasında gelen istek turun son kaydından önce
    işlenir."""
    run.apply_kill_request()
    resolve_unknown(run)
    sync_exchange_stops(run)
    run.reconcile_balance()
    pairs = dict.fromkeys(
        (*run.settings.whitelist, *(p.pair for p in run.state.ledger.positions.values()))
    )
    run.apply_report(read_market(run.market, tuple(pairs), run.settings, run.now))
    run.observe_equity()
    close_positions(run)
    run.observe_equity()
    buy_pairs(run)
    run.apply_kill_request()
    run.notices.settle()
    return run.result(TurnOutcome.COMPLETED, "tur tamamlandı")


def _begin(
    *,
    market: Mapping[str, object],
    settings: TurnSettings,
    store_path: object,
    now: datetime,
    exchange: Exchange,
    notices: Notices,
    memory: TurnMemory,
    mode: str = PAPER,
    kill_request: KillRequest | None = None,
) -> TurnResult:
    if not aware(now):
        notices.enter(NoticeKind.INVALID_TIME, "", "turun zamanı zaman dilimi taşımalı")
        return _refusal(TurnOutcome.INVALID_TIME, "geçersiz zaman", notices)
    notices.clear(NoticeKind.INVALID_TIME)
    problem = settings_problem(settings, now)
    if problem is not None:
        return _refusal(TurnOutcome.INVALID_SETTINGS, f"geçersiz ayar: {problem}", notices)
    loaded = load_store(store_path, mode)
    if loaded.state is None:
        notices.enter(NoticeKind.STORE_UNAVAILABLE, "", loaded.message)
        return _refusal(TurnOutcome.STORE_UNAVAILABLE, loaded.message, notices)
    notices.clear(NoticeKind.STORE_UNAVAILABLE)
    if loaded.state.ledger.balance is None:
        message = "defter açılmamış"
        notices.enter(NoticeKind.LEDGER_NOT_OPENED, "", message)
        return _refusal(TurnOutcome.LEDGER_NOT_OPENED, message, notices)
    notices.clear(NoticeKind.LEDGER_NOT_OPENED)
    plain = dict(market) if isinstance(market, Mapping) else {}  # not a mapping: all data missing
    run = TurnRun(store_path, settings, plain, now, exchange, notices, memory, loaded.state)
    run.kill_request = kill_request
    run.note_drawdown()
    run.sync_safe_mode()
    if loaded.conflicts:
        run.flag_reconciliation(loaded.message)
    if memory.history_halted:
        run.halt(BuyHalt.HISTORY_IMMUTABLE)
        notices.enter(NoticeKind.HISTORY_IMMUTABLE, "", "geçmiş değiştirilemez")
    try:
        return _trade(run)
    except SaveRefusedError as refused:
        return run.result(TurnOutcome.SAVE_REFUSED, str(refused))
    except BannedError:
        raise
    except Exception as error:  # R-11: what was saved so far stays in the result
        return run.result(TurnOutcome.UNEXPECTED_ERROR, _unexpected(error, notices))


def run_turn(
    *,
    market: Mapping[str, object],
    settings: TurnSettings,
    store_path: object,
    now: datetime,
    exchange: Exchange,
    sink: Callable[[TurnNotice], None],
    memory: TurnMemory,
    kill_request: KillRequest | None = None,
) -> TurnResult:
    """Tek geçiş: açık pozisyonları kapatır, risk onaylı alım yapar, her adımı kaydeder.

    İstisna fırlatmaz (R-11). Kâr hedefi ve kâr-zarar girdi değildir
    (R-14). `memory` süreç belleğidir: aynı süreçte aynı nesne verilir (plan Risk 5).
    `kill_request` çalışan bota gelen kill switch isteğidir (spec 0035 R-4, AC-11).
    """
    for name, valid in (
        ("memory", isinstance(memory, TurnMemory)),
        ("exchange", isinstance(exchange, Exchange)),
        ("sink", callable(sink)),
    ):
        if not valid:
            return _refusal(TurnOutcome.INVALID_SETTINGS, f"geçersiz ayar: {name}")
    notices = Notices(memory, sink, now)
    turn_mode = LIVE if isinstance(exchange, LiveExchange) else PAPER
    try:
        return _begin(
            market=market,
            settings=settings,
            store_path=store_path,
            now=now,
            exchange=exchange,
            notices=notices,
            memory=memory,
            mode=turn_mode,
            kill_request=kill_request,
        )
    except BannedError:
        raise
    except Exception as error:  # R-11; every completed step is already saved (plan Risk 13)
        return _refusal(TurnOutcome.UNEXPECTED_ERROR, _unexpected(error, notices), notices)
