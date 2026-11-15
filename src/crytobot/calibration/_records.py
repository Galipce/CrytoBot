"""Sinyal kayıt dosyası (spec 0045 R-10, AC-9; plan Risk 10, 12). Saf: metni üretir.

JSON Lines, UTF-8. 1. satır başlıktır (biçim, sürüm, aşama, üretim anı) — değişen tek satır. Sonra
her ölçülen (dönemde sayılan) sinyal: indikatör, ayar, ayarın etiketi, çift, aralık, dönem, sinyal
anı, yön, giriş fiyatı, isabet, olağandışıya denk gelip gelmediği, boşluklu mu. Sıra ölçüm
sırasıdır (aralık, indikatör, ayar, dönem, çift, yön), içinde zaman. Sonra aşamanın dönemlerindeki
her olağandışı mum: anı, çifti, aralığı, işaretleyen kurallar; aralık, çift, zaman sırasıyla.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

from crytobot.calibration._signals import indicator, setting_label
from crytobot.calibration._tuning import INTERVALS, PAIRS, Measured

FORMAT: Final = "crytobot-calibration-records"
VERSION: Final = 1


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"


def _signal_lines(measured: Measured) -> Iterator[str]:
    for row in measured.measurements:
        spec = indicator(row.indicator)
        assert spec is not None  # measured from INDICATORS
        results = measured.outcomes[(row.interval, row.pair)]
        hits = results.hits(row.direction)
        label = setting_label(spec, row.setting)
        for position in row.positions:
            yield _line(
                {
                    "kind": "signal",
                    "indicator": row.indicator,
                    "setting": list(row.setting),
                    "label": label,
                    "pair": row.pair,
                    "interval": row.interval,
                    "period": row.period,
                    "time": results.opens[position].astimezone(UTC).isoformat(),
                    "direction": row.direction.value,
                    "entry": results.entry[position],
                    "hit": bool(hits[position]),
                    "unusual": results.unusual[position],
                    "gapped": results.gapped[position],
                }
            )


def _unusual_lines(measured: Measured) -> Iterator[str]:
    for interval in INTERVALS:
        for pair in PAIRS:
            key = (interval, pair)
            if key not in measured.flags:
                continue
            results, flags = measured.outcomes[key], measured.flags[key]
            positions = sorted(
                {
                    index
                    for period in measured.periods
                    if pair in period.pairs
                    for index in results.span(period)
                }
            )
            for index in positions:
                if flags[index]:
                    yield _line(
                        {
                            "kind": "unusual",
                            "pair": pair,
                            "interval": interval,
                            "time": results.opens[index].astimezone(UTC).isoformat(),
                            "rules": flags[index],
                        }
                    )


def records_text(measured: Measured, *, final: bool, generated_at: datetime) -> str:
    header = _line(
        {
            "format": FORMAT,
            "version": VERSION,
            "stage": "final" if final else "1",
            "generated_at": generated_at.astimezone(UTC).isoformat(),
        }
    )
    return header + "".join(_signal_lines(measured)) + "".join(_unusual_lines(measured))
