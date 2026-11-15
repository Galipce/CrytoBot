"""Spec 0045 R-6: ayar seti dosyası — kanonik metin, parmak izi, denetimli okuma (plan Risk 3)."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from crytobot.calibration import (
    INDICATORS,
    INTERVALS,
    Choice,
    Costs,
    CrossTest,
    Robustness,
    SettingsProblem,
    SettingsSet,
    fingerprint,
    read_settings,
    settings_text,
)

MOMENT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
COSTS = Costs(Decimal("0.001"), Decimal("0.001"), Decimal("0.0005"))
DATA = tuple((interval, f"{index:064x}") for index, interval in enumerate(INTERVALS))


def choices() -> list[Choice]:
    found = []
    for interval in INTERVALS:
        for spec in INDICATORS:
            if spec.name == "Donchian":
                found.append(Choice(spec.name, interval, None, "ayar yok: x", False, False))
            else:
                found.append(
                    Choice(
                        spec.name,
                        interval,
                        spec.default,
                        None,
                        spec.name == "RSI",
                        spec.name == "MACD",
                        Robustness(1, 4),
                        CrossTest(2, 4),
                    )
                )
    return found


def text() -> str:
    return settings_text(choices(), MOMENT, COSTS, DATA)


def test_round_trip_and_canonical_bytes() -> None:
    written = text()
    assert written == text()  # same content, same bytes
    assert written.endswith("}\n")
    document = json.loads(written)
    assert written == json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    read = read_settings(written)
    assert isinstance(read, SettingsSet)
    assert read.generated_at == MOMENT
    assert read.costs == COSTS
    assert read.data == DATA
    assert list(read.choices) == choices()


def test_fingerprint_is_sha256_of_the_utf8_bytes() -> None:
    written = text()
    assert fingerprint(written) == hashlib.sha256(written.encode("utf-8")).hexdigest()


def _edit(change: Callable[[dict[str, Any]], None]) -> str:
    document = json.loads(text())
    change(document)
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _set(path: str, value: object) -> Callable[[dict[str, Any]], None]:
    def change(document: dict[str, Any]) -> None:
        target: Any = document
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        last = keys[-1]
        if last.isdigit():
            target[int(last)] = value
        else:
            target[last] = value

    return change


BROKEN: dict[str, tuple[str, str]] = {
    "not json": ("{", "json"),
    "a list": ("[]\n", "json"),
    "format": (_edit(_set("format", "x")), "format"),
    "version": (_edit(_set("version", 2)), "format"),
    "naive moment": (_edit(_set("generated_at", "2026-11-15T12:00:00")), "generated_at"),
    "moment not text": (_edit(_set("generated_at", 5)), "generated_at"),
    "moment not a time": (_edit(_set("generated_at", "dün")), "generated_at"),
    "costs keys": (_edit(_set("costs", {"fee": "0.001"})), "costs"),
    "cost negative": (_edit(_set("costs.fee", "-1")), "costs"),
    "cost not text": (_edit(_set("costs.fee", 0.001)), "costs"),
    "cost not a number": (_edit(_set("costs.fee", "x")), "costs"),
    "data missing interval": (_edit(lambda d: d["data"].pop("15m")), "data"),
    "data not hex": (_edit(_set("data.15m", "z" * 64)), "data"),
    "choices not a list": (_edit(_set("choices", {})), "choices"),
    "choice not an object": (_edit(_set("choices.0", 1)), "choices"),
    "unknown indicator": (_edit(_set("choices.0.indicator", "X")), "choices.indicator"),
    "unknown interval": (_edit(_set("choices.0.interval", "7m")), "choices.indicator"),
    "outside grid": (_edit(_set("choices.0.setting", [15, 30])), "choices.setting"),
    "setting not numbers": (_edit(_set("choices.0.setting", ["14", 30])), "choices.setting"),
    "setting with reason": (_edit(_set("choices.0.reason", "x")), "choices.setting"),
    "no setting no reason": (_edit(_set("choices.6.reason", None)), "choices.reason"),
    "no setting but fragile": (_edit(_set("choices.6.fragile", True)), "choices.reason"),
    "flag not bool": (_edit(_set("choices.0.fragile", 1)), "choices.flags"),
    "neighbours shape": (_edit(_set("choices.0.neighbours", [1])), "choices.neighbours"),
    "cross shape": (_edit(_set("choices.0.cross", [1, -1])), "choices.cross"),
    "missing choice": (_edit(lambda d: d["choices"].pop()), "choices.order"),
    "order": (
        _edit(
            lambda d: d.__setitem__(
                "choices", [d["choices"][1], d["choices"][0], *d["choices"][2:]]
            )
        ),
        "choices.order",
    ),
}


@pytest.mark.parametrize("case", sorted(BROKEN))
def test_broken_settings_named(case: str) -> None:
    written, detail = BROKEN[case]
    assert read_settings(written) == SettingsProblem(detail)


def test_moment_kept_in_utc() -> None:
    later = settings_text(choices(), MOMENT + timedelta(hours=3), COSTS, DATA)
    read = read_settings(later)
    assert isinstance(read, SettingsSet) and read.generated_at.utcoffset() == timedelta(0)
