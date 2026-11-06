"""Geçmiş veri dosyası: biçim, `.part`'a akışlı yazma, üzerine yazmayan son ad (spec 0023 R-4, R-8;
plan Risk 7, 8).

Biçim UTF-8 JSON Lines'tır. 1. satır başlıktır (`format`, `version`, mum aralığı, dönem, ısınma
başlangıcı, indirme anı, çift sırasıyla kurallar ve fiyat adımı). Sonra çift başına, açılış
sırasıyla mum satırları gelir: `[çift, açılış ms, open, high, low, close]`, fiyatlar borsanın
metniyle. Son satır tamamlanma satırıdır (`complete`, çift başına mum sayısı); onsuz dosya bozuk
sayılır (okuyucu 0025).

Yazma `<yol>.part`'a yapılır, `.part` dışlayıcı açılır: var olan `.part` başka bir indirmenindir,
silinmez. Başarıda `os.link` ile son ada bağlanır: hedef varsa `FileExistsError`, üzerine yazılmaz.
Hata, durdurma ya da `ForcedStop`'ta yalnız bu indirmenin `.part`'ı silinir.
"""

import json
import os
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import IO, Final

from crytobot.market_data._types import MarketDataError, MarketRules

FORMAT: Final = "crytobot-history"
VERSION: Final = 1
PART_SUFFIX: Final = ".part"


class HistoryFileError(MarketDataError):
    """Veri dosyası yazılamadı; işletim sisteminin metnini taşımaz."""


class HistoryFileExists(MarketDataError):
    """Yolda bir şey var: `part` ise yarım kalmış başka bir indirmenin `.part`'ı."""

    def __init__(self, part: bool) -> None:
        super().__init__("part" if part else "data")
        self.part = part


@dataclass(frozen=True, slots=True)
class PairHeader:
    pair: str
    market_id: str
    tick: Decimal
    rules: MarketRules


@dataclass(frozen=True, slots=True)
class FileHeader:
    exchange: str
    candle_interval: str
    start: datetime
    end: datetime
    warmup_start: datetime
    downloaded_at: datetime
    pairs: tuple[PairHeader, ...]


def part_path(path: Path) -> Path:
    return path.with_name(path.name + PART_SUFFIX)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _text(value: Decimal) -> str:
    # `str` writes 1E-8 for 0.00000001; `f` keeps the plain digits the exchange sent
    return format(value, "f")


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def header_line(header: FileHeader) -> str:
    return _line(
        {
            "format": FORMAT,
            "version": VERSION,
            "exchange": header.exchange,
            "candle_interval": header.candle_interval,
            "start": _iso(header.start),
            "end": _iso(header.end),
            "warmup_start": _iso(header.warmup_start),
            "downloaded_at": _iso(header.downloaded_at),
            "pairs": [
                {
                    "pair": pair.pair,
                    "market_id": pair.market_id,
                    "tick": _text(pair.tick),
                    "amount_step": _text(pair.rules.amount_step),
                    "min_amount": _text(pair.rules.min_amount),
                    "min_notional": _text(pair.rules.min_notional),
                }
                for pair in header.pairs
            ],
        }
    )


def candle_line(pair: str, open_ms: int, prices: Sequence[str]) -> str:
    """`prices`: borsanın open, high, low, close metni; denetlenmiş, yuvarlanmaz (R-3)."""
    return _line([pair, open_ms, *prices])


def complete_line(counts: Sequence[tuple[str, int]]) -> str:
    return _line({"complete": True, "counts": dict(counts)})


def existing(path: Path) -> HistoryFileExists | None:
    """R-4: yolda okunabilir, bozuk ya da başka türden bir şey varsa ret; `.part` de."""
    if os.path.lexists(path):
        return HistoryFileExists(part=False)
    if os.path.lexists(part_path(path)):
        return HistoryFileExists(part=True)
    return None


class HistoryWriter:
    """Bir indirmenin `.part` dosyası. `close` her durumda çağrılır; `finish` olmadıysa siler."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.part = part_path(path)
        self._file: IO[str] | None = None

    def open(self) -> None:
        try:
            self._file = open(self.part, "x", encoding="utf-8", newline="\n")  # noqa: SIM115
        except FileExistsError:
            raise HistoryFileExists(part=True) from None
        except OSError:
            raise HistoryFileError from None

    def write(self, text: str) -> None:
        if self._file is None:
            raise HistoryFileError
        try:
            self._file.write(text)
        except OSError:
            raise HistoryFileError from None

    def finish(self) -> None:
        """Tamamlanmış `.part` son ada bağlanır; hedef artık varsa üzerine yazılmaz."""
        if self._file is None:
            raise HistoryFileError
        try:
            self._file.close()
            os.link(self.part, self.path)
        except FileExistsError:
            raise HistoryFileExists(part=False) from None
        except OSError:
            raise HistoryFileError from None

    def close(self) -> None:
        """Açık dosyayı kapatır, bu indirmenin `.part`'ını siler (başarıda da: son ad kalır).

        `open` başarısızsa hiçbir şey silinmez: var olan `.part` başka bir indirmenindir.
        """
        handle, self._file = self._file, None
        if handle is None:
            return
        with suppress(OSError):
            handle.close()
        with suppress(OSError):
            self.part.unlink(missing_ok=True)
