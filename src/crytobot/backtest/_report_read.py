"""Rapor dosyasını ve metnini ayrıştırma (spec 0028 R-3, R-4, R-5; plan Adım 1).

Rapor dosyasını okur, başlık bilgilerini ve örneklem dışı parçasındaki metrikleri çıkarır.
Aday işareti ("BR-10 kanıtı adayı") yoksa adıyla bildirir.

Spec 0040 (plan Risk 4): dosya bir kez bayt olarak okunur; parmak izi (`ReportRead.sha256`) ve
ayrıştırma aynı baytlardandır. Üretim anı, spread, strateji ve rapor koşulları başlıkta yoksa
ayrıştırma bozuk saymaz, alanı boş bırakır: eksikliği kapı adıyla söyler (CB-4). Var olan ama
değeri bozuk satır yine `CORRUPT`'tır.

Spec 0042 R-7 (0028 R-3'ün kapı kısmını geçersiz kılar): yalnız son değerlendirme raporu okunur.
İlk satır varsayılan raporun başlığıysa `NOT_FINAL` ("rapor son değerlendirme değil"), aday
işaretinden önce. `paper adayı: aday yok` → `NO_CANDIDATE_MARK`. Strateji satırının ilk `=`'siz
parçası strateji adıdır (`ParsedReport.strategy_name`); yoksa `None`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from enum import Enum
from pathlib import Path

from crytobot.backtest._report import (
    CANDIDATE_MARK,
    CONDITIONS,
    FINAL_TITLE,
    GENERATED_LABEL,
    NO_CANDIDATE,
    PAPER_LABEL,
    TITLE,
    UNDEFINED,
)
from crytobot.backtest._report_file import fingerprint_of


class ReportReadProblem(Enum):
    """Rapor okuma veya ayrıştırma sorunu."""

    MISSING = "missing"
    UNREADABLE = "unreadable"
    EMPTY = "empty"
    CORRUPT = "corrupt"
    INCOMPLETE = "incomplete"
    NO_CANDIDATE_MARK = "no_candidate_mark"
    NOT_FINAL = "not_final"


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
    """Ayrıştırılmış rapor bilgileri. `spread`, `strategy`, `generated_at` başlıkta yoksa `None`;
    `conditions` yalnız başlıkta bulunan rapor koşullarını taşır (spec 0040 CB-4)."""

    candle_interval: str
    turn_interval: str
    pairs: tuple[str, ...]
    spread: Decimal | None
    candidate: CandidateMetrics
    strategy: Mapping[str, int | Decimal] | None = None
    generated_at: datetime | None = None
    conditions: Mapping[str, Decimal] = field(default_factory=dict)
    strategy_name: str | None = None


@dataclass(frozen=True, slots=True)
class ReportRead:
    """Rapor okuma sonucu. `sha256`: dosya okunduysa ham baytlarının parmak izi (spec 0040)."""

    data: ParsedReport | None
    problem: ReportReadProblem | None
    detail: str | None = None
    sha256: str | None = None


def _strategy_name(line: str) -> str | None:
    """`strateji: S0 fast=12 ...` satırının ilk `=`'siz parçası (spec 0042 R-7)."""
    tokens = line.split()
    return tokens[0] if tokens and "=" not in tokens[0] else None


def _parse_strategy(line: str) -> dict[str, int | Decimal]:
    """`strateji: [ad] fast=12 slow=26 ...` satırını ayrıştırır; ad `_strategy_name`'dedir."""
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
    for value in params.values():
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError(value)  # NaN would compare unequal, sNaN would raise in the gate
    return params


def _finite(text: str) -> Decimal | None:
    """Sonlu ondalık; değilse `None` (NaN eşitsiz, sNaN karşılaştırmada fırlatır)."""
    try:
        number = Decimal(text)
    except DecimalException:
        return None
    return number if number.is_finite() else None


def _moment(text: str) -> datetime | None:
    """Saat dilimli ISO an, UTC'ye çevrilmiş; değilse `None`."""
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    return None if moment.utcoffset() is None else moment.astimezone(UTC)


def parse_report(text: str) -> ReportRead:
    """Rapor metnini ayrıştırır."""
    stripped = text.strip()
    if not stripped:
        return ReportRead(None, ReportReadProblem.EMPTY, "rapor dosyası boş")

    lines = [line.strip() for line in text.splitlines()]
    if lines and lines[0] == TITLE:
        return ReportRead(None, ReportReadProblem.NOT_FINAL, "rapor son değerlendirme değil")
    if not lines or lines[0] != FINAL_TITLE:
        return ReportRead(None, ReportReadProblem.CORRUPT, "rapor başlığı eksik veya geçersiz")

    candle_interval: str | None = None
    turn_interval: str | None = None
    pairs: tuple[str, ...] | None = None
    spread: Decimal | None = None
    strategy: dict[str, int | Decimal] | None = None
    strategy_name: str | None = None
    generated_at: datetime | None = None
    conditions: dict[str, Decimal] = {}
    paper: str | None = None

    for line in lines:
        name, _, value = line.partition(":")
        if name in CONDITIONS:
            number = _finite(value.strip())
            if number is None:
                return ReportRead(None, ReportReadProblem.CORRUPT, f"geçersiz {name} değeri")
            conditions[name] = number
        elif name == GENERATED_LABEL:
            generated_at = _moment(value.strip())
            if generated_at is None:
                return ReportRead(None, ReportReadProblem.CORRUPT, "geçersiz üretim anı")
        elif line.startswith("mum aralığı:"):
            candle_interval = line.partition(":")[2].strip()
        elif line.startswith("tur aralığı:"):
            turn_interval = line.partition(":")[2].strip()
        elif line.startswith("çiftler:"):
            raw_pairs = line.partition(":")[2].strip()
            pairs = tuple(p.strip() for p in raw_pairs.split(",") if p.strip())
        elif line.startswith("spread:"):
            spread = _finite(line.partition(":")[2].strip())
            if spread is None:
                return ReportRead(None, ReportReadProblem.CORRUPT, "geçersiz spread değeri")
        elif line.startswith("strateji:"):
            raw_strategy = line.partition(":")[2].strip()
            try:
                strategy = _parse_strategy(raw_strategy)
            except (ValueError, DecimalException):
                return ReportRead(None, ReportReadProblem.CORRUPT, "geçersiz strateji satırı")
            strategy_name = _strategy_name(raw_strategy)
        elif name == PAPER_LABEL:
            paper = value.strip()
        elif line.startswith("== "):
            # Başlık bölümü bitti
            break

    if paper == NO_CANDIDATE:
        return ReportRead(None, ReportReadProblem.NO_CANDIDATE_MARK, "rapor aday işareti taşımıyor")

    if candle_interval is None or turn_interval is None or pairs is None:
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
        generated_at=generated_at,
        conditions=conditions,
        strategy_name=strategy_name,
    )
    return ReportRead(data=data, problem=None)


def read_report(path: str | Path) -> ReportRead:
    """Rapor dosyasını bir kez okur; aynı baytları özetler ve ayrıştırır (spec 0040, Risk 4)."""
    p = Path(path)
    if not p.is_file():
        return ReportRead(None, ReportReadProblem.MISSING, "rapor dosyası yok")
    try:
        data = p.read_bytes()
    except OSError as err:
        return ReportRead(
            None,
            ReportReadProblem.UNREADABLE,
            f"rapor dosyası okunamıyor: {type(err).__name__}",
        )
    sha256 = fingerprint_of(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ReportRead(
            None,
            ReportReadProblem.UNREADABLE,
            "rapor dosyası okunamıyor: UTF-8 değil",
            sha256,
        )
    # parsing sees universal newlines as before; the fingerprint is of the raw bytes (G-1)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return replace(parse_report(text), sha256=sha256)
