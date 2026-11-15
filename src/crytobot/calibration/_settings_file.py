"""Ayar seti dosyası (spec 0045 R-6; plan Risk 3). Saf: metni üretir ve okur, dosyaya dokunmaz.

Biçim kanonik JSON'dur (anahtarlar sıralı, 2 boşluk girinti, UTF-8, sonda satır sonu): aynı içerik
aynı baytları verir. Parmak izi yazılan baytların SHA-256'sıdır. Alanlar: biçim adı ve sürümü,
üretim anı (UTC), ölçüm maliyetleri (metin), aralık başına veri dosyasının SHA-256'sı ve her
indikatör x aralık için seçilen ayar (ya da `null` ve nedeni), "dayanıksız" ve "çapraz sınamada
geçmedi" işaretleri, komşu ve çapraz sınama sayıları.

Okuma her alanı denetler: ayar ızgaranın içinde olmalı, her indikatör x aralık tam bir kez
bulunmalı. Bozuk dosya `SettingsProblem` ile adlandırılır; istisna fırlatmaz.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

from crytobot.calibration._outcome import Costs
from crytobot.calibration._signals import INDICATORS, in_grid, indicator
from crytobot.calibration._tuning import INTERVALS, Choice, CrossTest, Robustness

FORMAT: Final = "crytobot-calibration-settings"
VERSION: Final = 1
_HEX: Final = frozenset("0123456789abcdef")


@dataclass(frozen=True, slots=True)
class SettingsSet:
    generated_at: datetime
    costs: Costs
    data: tuple[tuple[str, str], ...]  # (interval, sha256) in `INTERVALS` order
    choices: tuple[Choice, ...]


@dataclass(frozen=True, slots=True)
class SettingsProblem:
    detail: str


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _number_list(values: Sequence[int | float]) -> list[int | float]:
    return list(values)


def _choice(choice: Choice) -> dict[str, object]:
    near, cross = choice.neighbours, choice.cross
    return {
        "indicator": choice.indicator,
        "interval": choice.interval,
        "setting": None if choice.setting is None else _number_list(choice.setting),
        "reason": choice.reason,
        "fragile": choice.fragile,
        "cross_failed": choice.cross_failed,
        "neighbours": None if near is None else [near.passing, near.total],
        "cross": None if cross is None else [cross.passing, cross.total],
    }


def settings_text(
    choices: Sequence[Choice],
    generated_at: datetime,
    costs: Costs,
    data: Sequence[tuple[str, str]],
) -> str:
    document = {
        "format": FORMAT,
        "version": VERSION,
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "costs": {
            "fee": format(costs.fee, "f"),
            "slippage": format(costs.slippage, "f"),
            "spread": format(costs.spread, "f"),
        },
        "data": dict(data),
        "choices": [_choice(choice) for choice in choices],
    }
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


class _Bad(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def _decimal(value: object, name: str) -> Decimal:
    if type(value) is not str:
        raise _Bad(name)
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise _Bad(name) from None
    if not number.is_finite() or number < 0:
        raise _Bad(name)
    return number


def _pair_of_ints(value: object, name: str) -> tuple[int, int] | None:
    if value is None:
        return None
    if not (
        isinstance(value, list)
        and len(value) == 2
        and all(type(item) is int and item >= 0 for item in value)
    ):
        raise _Bad(name)
    return value[0], value[1]


def _parse_choice(item: object) -> Choice:
    if not isinstance(item, Mapping):
        raise _Bad("choices")
    name, interval = item.get("indicator"), item.get("interval")
    spec = indicator(name) if type(name) is str else None
    if spec is None or interval not in INTERVALS:
        raise _Bad("choices.indicator")
    assert type(name) is str and type(interval) is str
    raw, reason = item.get("setting"), item.get("reason")
    fragile, cross_failed = item.get("fragile"), item.get("cross_failed")
    if type(fragile) is not bool or type(cross_failed) is not bool:
        raise _Bad("choices.flags")
    near = _pair_of_ints(item.get("neighbours"), "choices.neighbours")
    cross = _pair_of_ints(item.get("cross"), "choices.cross")
    if raw is None:
        if type(reason) is not str or not reason or fragile or cross_failed:
            raise _Bad("choices.reason")
        return Choice(name, interval, None, reason, False, False)
    if not isinstance(raw, list) or not all(type(value) in (int, float) for value in raw):
        raise _Bad("choices.setting")
    setting = tuple(raw)
    if not in_grid(spec, setting) or reason is not None:
        raise _Bad("choices.setting")
    return Choice(
        name,
        interval,
        setting,
        None,
        fragile,
        cross_failed,
        neighbours=None if near is None else Robustness(*near),
        cross=None if cross is None else CrossTest(*cross),
    )


def _parse(text: str) -> SettingsSet:
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise _Bad("json") from None
    if not isinstance(document, Mapping):
        raise _Bad("json")
    if document.get("format") != FORMAT or document.get("version") != VERSION:
        raise _Bad("format")
    moment = document.get("generated_at")
    try:
        generated_at = datetime.fromisoformat(moment) if type(moment) is str else None
    except ValueError:
        generated_at = None
    if generated_at is None or generated_at.utcoffset() != timedelta(0):
        raise _Bad("generated_at")
    costs = document.get("costs")
    if not isinstance(costs, Mapping) or set(costs) != {"fee", "slippage", "spread"}:
        raise _Bad("costs")
    parsed_costs = Costs(
        _decimal(costs["fee"], "costs"),
        _decimal(costs["slippage"], "costs"),
        _decimal(costs["spread"], "costs"),
    )
    data = document.get("data")
    if not isinstance(data, Mapping) or set(data) != set(INTERVALS):
        raise _Bad("data")
    for value in data.values():
        if type(value) is not str or len(value) != 64 or not set(value) <= _HEX:
            raise _Bad("data")
    items = document.get("choices")
    if not isinstance(items, list):
        raise _Bad("choices")
    choices = tuple(_parse_choice(item) for item in items)
    keys = [(choice.indicator, choice.interval) for choice in choices]
    expected = [(spec.name, interval) for interval in INTERVALS for spec in INDICATORS]
    if keys != expected:
        raise _Bad("choices.order")
    return SettingsSet(
        generated_at.astimezone(UTC),
        parsed_costs,
        tuple((interval, data[interval]) for interval in INTERVALS),
        choices,
    )


def read_settings(text: str) -> SettingsSet | SettingsProblem:
    """Ayar seti metnini okur ve denetler; istisna fırlatmaz."""
    try:
        return _parse(text)
    except _Bad as bad:
        return SettingsProblem(bad.detail)
