"""Rapor dosyasını ve metnini ayrıştırma (spec 0028 R-3, R-4, R-5; plan Adım 1).

Rapor dosyasını okur, başlık bilgilerini ve örneklem dışı parçasındaki metrikleri çıkarır.
Aday işareti ("BR-10 kanıtı adayı") yoksa adıyla bildirir.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import Enum
from pathlib import Path

from crytobot.backtest._report import CANDIDATE_MARK, UNDEFINED


class ReportReadProblem(Enum):
    """Rapor okuma veya ayrıştırma sorunu."""

    MISSING = "missing"
    UNREADABLE = "unreadable"
    EMPTY = "empty"
    CORRUPT = "corrupt"
    INCOMPLETE = "incomplete"
    NO_CANDIDATE_MARK = "no_candidate_mark"


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    """Örneklem dışı parçasından çıkarılan metrikler."""

    net: Decimal
    return_ratio: Decimal | None
    max_drawdown: Decimal | None
    trades: int
    profit_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class ParsedReport:
    """Ayrıştırılmış rapor bilgileri."""

    candle_interval: str
    turn_interval: str
    pairs: tuple[str, ...]
    spread: Decimal
    candidate: CandidateMetrics
    strategy: Mapping[str, int | Decimal] | None = None


@dataclass(frozen=True, slots=True)
class ReportRead:
    """Rapor okuma sonucu."""

    data: ParsedReport | None
    problem: ReportReadProblem | None
    detail: str | None = None


def _parse_strategy(line: str) -> dict[str, int | Decimal]:
    """`strateji: fast=12 slow=26 ...` satırını ayrıştırır."""
    params: dict[str, int | Decimal] = {}
    tokens = line.split()
    for token in tokens:
        if "=" not in token:
            continue
        key, _, val = token.partition("=")
        key = key.strip()
        val = val.strip()
        if key in ("fast", "fast_period"):
            params["fast_period"] = int(val)
        elif key in ("slow", "slow_period"):
            params["slow_period"] = int(val)
        elif key in ("rsi", "rsi_period"):
            params["rsi_period"] = int(val)
        elif key == "rsi_threshold":
            params["rsi_threshold"] = Decimal(val)
        elif key in ("atr", "atr_period"):
            params["atr_period"] = int(val)
        elif key == "k":
            params["k"] = Decimal(val)
        elif key == "r":
            params["r"] = Decimal(val)
    return params


def parse_report(text: str) -> ReportRead:
    """Rapor metnini ayrıştırır."""
    stripped = text.strip()
    if not stripped:
        return ReportRead(None, ReportReadProblem.EMPTY, "rapor dosyası boş")

    lines = [line.strip() for line in text.splitlines()]
    if not lines or lines[0] != "CrytoBot backtest raporu":
        return ReportRead(None, ReportReadProblem.CORRUPT, "rapor başlığı eksik veya geçersiz")

    candle_interval: str | None = None
    turn_interval: str | None = None
    pairs: tuple[str, ...] | None = None
    spread: Decimal | None = None
    strategy: dict[str, int | Decimal] | None = None

    for line in lines:
        if line.startswith("mum aralığı:"):
            candle_interval = line.partition(":")[2].strip()
        elif line.startswith("tur aralığı:"):
            turn_interval = line.partition(":")[2].strip()
        elif line.startswith("çiftler:"):
            raw_pairs = line.partition(":")[2].strip()
            pairs = tuple(p.strip() for p in raw_pairs.split(",") if p.strip())
        elif line.startswith("spread:"):
            raw_spread = line.partition(":")[2].strip()
            try:
                spread = Decimal(raw_spread)
            except DecimalException:
                return ReportRead(None, ReportReadProblem.CORRUPT, "geçersiz spread değeri")
        elif line.startswith("strateji:"):
            raw_strategy = line.partition(":")[2].strip()
            try:
                strategy = _parse_strategy(raw_strategy)
            except (ValueError, DecimalException):
                return ReportRead(None, ReportReadProblem.CORRUPT, "geçersiz strateji satırı")
        elif line.startswith("== "):
            # Başlık bölümü bitti
            break

    if candle_interval is None or turn_interval is None or pairs is None or spread is None:
        return ReportRead(None, ReportReadProblem.CORRUPT, "başlık bilgileri eksik")

    if not pairs:
        return ReportRead(None, ReportReadProblem.CORRUPT, "çiftler listesi boş")

    candidate_header = f"== örneklem dışı — {CANDIDATE_MARK} =="
    if candidate_header not in text:
        return ReportRead(None, ReportReadProblem.NO_CANDIDATE_MARK, "rapor aday işareti taşımıyor")

    if "== tüm koşu ==" not in text:
        return ReportRead(None, ReportReadProblem.INCOMPLETE, "tüm koşu bölümü eksik")

    # Aday bölümünü ayıkla
    _, _, after_candidate = text.partition(candidate_header)
    candidate_body, _, _ = after_candidate.partition("\n== ")

    net: Decimal | None = None
    return_ratio: Decimal | None = None
    max_drawdown: Decimal | None = None
    trades: int | None = None
    profit_factor: Decimal | None = None

    try:
        for raw_line in candidate_body.splitlines():
            line = raw_line.strip()
            if line.startswith("net kâr/zarar:"):
                # Örnek: net kâr/zarar: 500.00000000 USDT (getiri %5.0000)
                content = line.partition(":")[2].strip()
                usdt_part, _, ret_part = content.partition(" USDT")
                net = Decimal(usdt_part.strip())
                if "(getiri " in ret_part:
                    raw_ret = ret_part.partition("(getiri ")[2].rstrip(")")
                    if raw_ret == UNDEFINED:
                        return_ratio = None
                    elif raw_ret.startswith("%"):
                        return_ratio = Decimal(raw_ret[1:]) / Decimal(100)
                    else:
                        return_ratio = Decimal(raw_ret)
            elif line.startswith("işlem:"):
                # Örnek: işlem: 15 (kazanan 10, zararlı 5)
                content = line.partition(":")[2].strip()
                trades_part, _, _ = content.partition("(")
                trades = int(trades_part.strip())
            elif line.startswith("kâr faktörü:"):
                content = line.partition(":")[2].strip()
                profit_factor = None if content == UNDEFINED else Decimal(content)
            elif line.startswith("en büyük drawdown:"):
                content = line.partition(":")[2].strip()
                if content == UNDEFINED:
                    max_drawdown = None
                elif content.startswith("%"):
                    max_drawdown = Decimal(content[1:]) / Decimal(100)
                else:
                    max_drawdown = Decimal(content)
    except (ValueError, DecimalException):
        return ReportRead(None, ReportReadProblem.CORRUPT, "örneklem dışı metrikleri okunamadı")

    if net is None or trades is None:
        return ReportRead(None, ReportReadProblem.CORRUPT, "örneklem dışı temel metrikleri eksik")

    candidate = CandidateMetrics(
        net=net,
        return_ratio=return_ratio,
        max_drawdown=max_drawdown,
        trades=trades,
        profit_factor=profit_factor,
    )
    data = ParsedReport(
        candle_interval=candle_interval,
        turn_interval=turn_interval,
        pairs=pairs,
        spread=spread,
        candidate=candidate,
        strategy=strategy,
    )
    return ReportRead(data=data, problem=None)


def read_report(path: str | Path) -> ReportRead:
    """Rapor dosyasını okur ve ayrıştırır."""
    p = Path(path)
    if not p.is_file():
        return ReportRead(None, ReportReadProblem.MISSING, "rapor dosyası yok")
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ReportRead(
            None,
            ReportReadProblem.UNREADABLE,
            "rapor dosyası okunamıyor: UTF-8 değil",
        )
    except OSError as err:
        return ReportRead(
            None,
            ReportReadProblem.UNREADABLE,
            f"rapor dosyası okunamıyor: {type(err).__name__}",
        )

    return parse_report(text)
