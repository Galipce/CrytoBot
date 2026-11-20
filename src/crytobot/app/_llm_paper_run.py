"""LLM paper ölçümünün iki koşusu: indirme ve rapor (spec 0060 R-2, R-3, R-6, R-7; plan Risk 5, 8).

`run_llm_paper_download`: önce on çiftin borsa kuralları (herkese açık okuma) kural dosyasına, sonra
listenin bütün coinleri için ölçüm penceresinin 1h mumları (`market_data`'nın indirme adımı; ikizin
giriş mumu için başlangıçtan bir saat önce). `run_llm_paper_report`: rapor anı (gelecekte ise ret)
-> karar kaydı -> etkin dönem ve sayılar -> mumlar ve kurallar (al yoksa okunmaz) -> oynatma,
eşlenik rastgele, metrik, hüküm -> işlem dosyası ve rapor (atomik). Ufuk rapor anının ve son
indirmenin tavanının küçüğüdür: indirilmemiş saatler bekleyen sayılır, ölçülemedi değil. Gerçek
etkiler `*Parts` ile gelir: `app` dosya açmaz, saat çağırmaz, ağa çıkmaz, `decide`'ı import etmez
(R-3k).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from crytobot.app._forward import _DOWNLOAD_OUTCOMES, ForwardExit, ForwardOutcome, _Halt
from crytobot.app._llm_paper import HOUR, Bar, replay
from crytobot.app._llm_paper_config import MEASUREMENT_END, MEASUREMENT_START, LlmPaperConfig
from crytobot.app._llm_paper_random import random_distribution
from crytobot.app._llm_paper_report import (
    RecordDecision,
    RecordTurn,
    ReportFacts,
    S0Summary,
    active_period,
    buy_decisions,
    counts,
    metrics,
    periods,
    report_text,
    trade_rows,
    verdict,
)
from crytobot.app._loop import ForcedStop
from crytobot.market_data import DownloadOutcome, PriceData, PriceNeed
from crytobot.risk import PairRules

EVENT = "llm-paper"
DOWNLOAD_FIRST = "önce llm-paper download"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class LlmPaperRecord:
    turns: tuple[RecordTurn, ...]
    decisions: tuple[RecordDecision, ...]
    skipped: int


RulesFile = tuple[str | None, Mapping[str, Mapping[str, str]]]


@dataclass(frozen=True)
class LlmPaperDownloadParts:
    """`fetch_rules`: borsa kuralları metni (JSON) ya da okunamama nedeni; `record`: karar kaydı
    (etkin dönemin sonu için; okunamıyorsa nedeni, M-2, M-8)."""

    coins: tuple[str, ...]
    record: Callable[[], LlmPaperRecord | str | None]
    fetch_rules: Callable[[], tuple[str, None] | tuple[None, str]]
    download: Callable[[tuple[PriceNeed, ...]], DownloadOutcome]
    write_file: Callable[[str, str], bool]
    write: Callable[[str], None]
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class LlmPaperReportParts:
    """`record`: karar kaydı (yoksa `None`, okunamıyorsa nedeni); `prices`: fiyat deposu; `rules`:
    kural dosyası çözülmüş hâliyle `(an, coin -> alan -> metin)` (yoksa `None`, çözülemiyorsa
    nedeni); `s0`: S0 özeti (yoksa `None`); `write_rows`: işlem satırlarını atomik yazar."""

    coins: tuple[str, ...]
    record: Callable[[], LlmPaperRecord | str | None]
    prices: Callable[[], PriceData | str | None]
    rules: Callable[[], RulesFile | str | None]
    s0: Callable[[datetime, datetime], S0Summary | None]
    write_rows: Callable[[str, Sequence[Mapping[str, str | int | None]]], bool]
    write_file: Callable[[str, str], bool]
    write: Callable[[str], None]
    clock: Callable[[], datetime]


def _guarded(write: Callable[[str], None], command: str, body: Callable[[], str]) -> ForwardExit:
    def say(text: str) -> None:
        write(f"{EVENT} {command}: {text}")

    try:
        message = body()
    except _Halt as halt:
        verb = "reddedildi" if halt.outcome is ForwardOutcome.REFUSED else "durdu"
        say(f"{verb}: {halt.message}")
        return ForwardExit(halt.outcome, halt.message)
    except ForcedStop:
        say("durdu: zorla durdurma")
        raise
    except Exception as error:  # the type only; the text may carry anything
        message = f"beklenmeyen hata: {type(error).__name__}"
        say(f"durdu: {message}")
        return ForwardExit(ForwardOutcome.FAILED, message)
    say(message)
    return ForwardExit(ForwardOutcome.COMPLETED, message)


def _floor(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _download(config: LlmPaperConfig, parts: LlmPaperDownloadParts) -> str:
    now = parts.clock()
    record = parts.record()
    if isinstance(record, str):
        raise _Halt(ForwardOutcome.REFUSED, record)
    period_end = MEASUREMENT_END if record is None else active_period(record.turns).end
    rules, reason = parts.fetch_rules()
    if rules is None:
        raise _Halt(ForwardOutcome.FAILED, f"borsa kuralları okunamadı: {reason}")
    if not parts.write_file(config.rules_path, rules):
        raise _Halt(ForwardOutcome.NOT_WRITTEN, f"kural dosyası yazılamadı: {config.rules_path}")
    start, end = MEASUREMENT_START - HOUR, min(_floor(now), period_end)
    wanted = tuple(PriceNeed(coin, start, end) for coin in parts.coins) if end > start else ()
    parts.write(f"{EVENT} download: başladı: coin={len(parts.coins)} aralık={len(wanted)}")
    if not wanted:
        return "tamam: indirilecek aralık yok"
    outcome = parts.download(wanted)
    if outcome in _DOWNLOAD_OUTCOMES:
        result, message = _DOWNLOAD_OUTCOMES[outcome]
        raise _Halt(result, message)
    return "tamam: kurallar ve fiyat verisi indirildi"


def run_llm_paper_download(config: LlmPaperConfig, parts: LlmPaperDownloadParts) -> ForwardExit:
    return _guarded(parts.write, "download", lambda: _download(config, parts))


def parse_rules(found: RulesFile, coins: Sequence[str]) -> dict[str, PairRules] | str:
    """Kural dosyasının çiftleri: miktar adımı, en küçük miktar, en küçük tutar (G-8)."""
    _, pairs = found
    try:
        return {
            coin: PairRules(
                Decimal(pairs[coin]["amount_step"]),
                Decimal(pairs[coin]["min_amount"]),
                Decimal(pairs[coin]["min_notional"]),
            )
            for coin in coins
            if coin in pairs
        }
    except (KeyError, TypeError, InvalidOperation):
        return f"kural dosyası okunamıyor; {DOWNLOAD_FIRST}"


def _covered(prices: PriceData, coins: Sequence[str]) -> datetime:
    """L-1: on coinin ölçüm başından kesintisiz indirilmiş kapsamının en erken sonu; yarım kalan
    bir indirme ufku ilerletmez."""
    pairs = prices.pairs or {}
    start = MEASUREMENT_START - HOUR
    ends = []
    for coin in coins:
        pair = pairs.get(coin)
        reach = start
        spans = () if pair is None else prices.spans.get(pair.symbol, ())
        for span in sorted(spans, key=lambda s: s.start):
            if span.start > reach:
                break
            reach = max(reach, span.end)
        ends.append(reach)
    return min(ends) if ends else start


def _bars(prices: PriceData, coins: Sequence[str]) -> dict[str, dict[datetime, Bar]]:
    pairs = prices.pairs or {}
    found: dict[str, dict[datetime, Bar]] = {}
    for coin in coins:
        pair = pairs.get(coin)
        if pair is None:
            continue
        series: dict[datetime, Bar] = {}
        for c in prices.candles.get(pair.symbol, ()):
            at = _EPOCH + timedelta(milliseconds=c.open_ms)
            series[at] = Bar(at, Decimal(c.open), Decimal(c.high), Decimal(c.low), Decimal(c.close))
        found[coin] = series
    return found


def _report(config: LlmPaperConfig, parts: LlmPaperReportParts, at: datetime | None) -> str:
    now = parts.clock()
    if at is not None and at > now:
        raise _Halt(ForwardOutcome.REFUSED, "rapor anı gelecekte")
    report_at = now if at is None else at
    record = parts.record()
    if record is None:
        raise _Halt(ForwardOutcome.REFUSED, f"karar kaydı yok: {config.decide_store_path}")
    if isinstance(record, str):
        raise _Halt(ForwardOutcome.REFUSED, record)
    all_periods = periods(record.turns)
    period = active_period(record.turns)
    tally = counts(record.turns, record.decisions, period)
    buys = buy_decisions(record.decisions, period)
    bars: dict[str, dict[datetime, Bar]] = {}
    rules: Mapping[str, PairRules] = {}
    horizon = min(_floor(report_at), period.end)
    rules_at: str | None = None
    if buys:
        prices = parts.prices()
        if prices is None:
            raise _Halt(
                ForwardOutcome.REFUSED,
                f"fiyat verisi yok: {config.price_store_path}; {DOWNLOAD_FIRST}",
            )
        if isinstance(prices, str):
            raise _Halt(ForwardOutcome.REFUSED, prices)
        rules_file = parts.rules()
        if rules_file is None:
            raise _Halt(ForwardOutcome.REFUSED, f"kural dosyası yok; {DOWNLOAD_FIRST}")
        if isinstance(rules_file, str):
            raise _Halt(ForwardOutcome.REFUSED, rules_file)
        rules_at = rules_file[0]
        parsed = parse_rules(rules_file, parts.coins)
        if isinstance(parsed, str):
            raise _Halt(ForwardOutcome.REFUSED, parsed)
        rules = parsed
        absent = [coin for coin in parts.coins if coin not in rules]
        if absent:
            raise _Halt(
                ForwardOutcome.REFUSED, f"kural dosyası eksik: {absent[0]}; {DOWNLOAD_FIRST}"
            )
        bars = _bars(prices, parts.coins)
        ceiling = prices.ceiling
        horizon = min(horizon, period.end if ceiling is None else _floor(ceiling))
        horizon = min(horizon, _covered(prices, parts.coins))
    window = (period.start, period.end, horizon)
    result = replay(buys, bars, rules, *window)
    chance = random_distribution(result.trades, bars, rules, parts.coins, window)
    found = metrics(result)
    judged = verdict(period, report_at, found, chance, tally, horizon)
    facts = ReportFacts(
        report_at,
        parts.clock(),
        config.decide_store_path,
        record.skipped,
        config.price_store_path,
        rules_at,
        parts.s0(period.start, period.end),
        chance.missing,
        horizon,
    )
    if not parts.write_rows(config.trades_path, trade_rows(result.trades)):
        raise _Halt(ForwardOutcome.NOT_WRITTEN, f"işlem dosyası yazılamadı: {config.trades_path}")
    text = report_text(all_periods, period, tally, result, found, chance, judged, facts)
    if not parts.write_file(config.report_path, text):
        raise _Halt(ForwardOutcome.NOT_WRITTEN, f"rapor yazılamadı: {config.report_path}")
    parts.write(f"{EVENT} report: hüküm: {judged.line}")
    return f"tamam: rapor dosyası {config.report_path}"


def run_llm_paper_report(
    config: LlmPaperConfig, parts: LlmPaperReportParts, at: datetime | None = None
) -> ForwardExit:
    """Ağa ve LLM'e çıkmaz, kilit almaz; rapor ve işlem dosyası her koşuda baştan yazılır."""
    return _guarded(parts.write, "report", lambda: _report(config, parts, at))
