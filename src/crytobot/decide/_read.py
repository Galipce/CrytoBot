"""Karar kaydının salt okunur okuyucusu (spec 0060 plan step 1): ölçüm ve rapor için.

`mode=ro` ile açılır, dosya oluşturmaz, kilit almaz (karar turu çalışırken de). Her tur ve coin
başına karar ayrıştırılmış alanlarıyla döner; okunamayan satır sayılır, atlanır. Ham metin kayıtta
yoktur.
"""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from crytobot.decide._store import FORMAT_VERSION, DecideStoreError


@dataclass(frozen=True)
class TurnRow:
    at: datetime
    model: str
    prompt_fingerprint: str
    outcome: str
    called: bool


@dataclass(frozen=True)
class DecisionRow:
    """`action`: Claude'un kendi kararı (`al`/`bekle`); kararsız turun `bekle`sinde ve `veri yok`ta
    `None`."""

    at: datetime
    coin: str
    status: str
    action: str | None
    entry_low: float | None
    entry_high: float | None
    stop: float | None
    target: float | None
    valid_hours: int | None


@dataclass(frozen=True)
class DecisionRecord:
    turns: tuple[TurnRow, ...]
    decisions: tuple[DecisionRow, ...]
    skipped: int


def _moment(value: object) -> datetime:
    moment = datetime.fromisoformat(str(value))
    if moment.utcoffset() is None:
        raise ValueError("saat dilimi yok")
    return moment


def _real(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("sayı")
    return float(value)


def _whole(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("tam sayı")
    return value


def _optional(value: object) -> str | None:
    return None if value is None else str(value)


def read_decision_record(path: str) -> DecisionRecord | None:
    """Kayıt yoksa `None` (dosya oluşturulmaz); biçim tanınmıyor ya da okunamıyorsa
    `DecideStoreError`."""
    if not Path(path).is_file():
        return None
    uri = f"{Path(path).resolve().as_uri()}?mode=ro"
    turns: list[TurnRow] = []
    decisions: list[DecisionRow] = []
    skipped = 0
    try:
        with closing(sqlite3.connect(uri, uri=True, timeout=0)) as connection:
            row = connection.execute("SELECT value FROM meta WHERE name = 'format'").fetchone()
            if row is None or row[0] != FORMAT_VERSION:
                raise DecideStoreError("karar kaydının biçimi tanınmıyor")
            for at, model, prompt, outcome, called in connection.execute(
                "SELECT at, model, prompt_fingerprint, outcome, called FROM turns ORDER BY at"
            ):
                try:
                    turns.append(
                        TurnRow(_moment(at), str(model), str(prompt), str(outcome), bool(called))
                    )
                except (TypeError, ValueError):
                    skipped += 1
            for values in connection.execute(
                "SELECT t.at, d.coin, d.status, d.action, d.entry_low, d.entry_high, d.stop,"
                " d.target, d.valid_hours FROM decisions d JOIN turns t ON t.id = d.turn_id"
                " ORDER BY t.at, d.coin"
            ):
                at, coin, status, action, low, high, stop, target, hours = values
                try:
                    decisions.append(
                        DecisionRow(
                            _moment(at),
                            str(coin),
                            str(status),
                            _optional(action),
                            _real(low),
                            _real(high),
                            _real(stop),
                            _real(target),
                            _whole(hours),
                        )
                    )
                except (TypeError, ValueError):
                    skipped += 1
    except sqlite3.Error:
        raise DecideStoreError("karar kaydı okunamıyor") from None
    return DecisionRecord(tuple(turns), tuple(decisions), skipped)
