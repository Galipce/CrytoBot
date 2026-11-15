"""İndikatör kalibrasyonu ve isabet ölçümü (spec 0045). Saf: dosya, saat ve ağ kullanmaz.

Sekiz indikatörün (R-1) "al"/"sat" sinyallerinin kriptonun gerçek hareketlerini ne kadar isabetle
yakaladığını ölçer: isabet kuralı (Q-1), taban oran (Q-3), olağandışı mumlar (Q-8), BTC'de ayarlama
(R-4), dört çiftte çapraz sınama (R-5), görülmemiş dönemde hüküm (R-7). Yalnız `analysis`'i import
eder; veri, ayar ve dosya yazımı `app` ve giriş noktasındadır. Botun işlem davranışına girmez.

- `stage_one(veri, maliyet)` → `Measured`: varsayılan ölçüm, ızgara, seçim, çapraz sınama.
- `final_stage(veri, maliyet, seçimler)` → `Measured`: üç dönem, hükümler.
- `settings_text` / `read_settings`: ayar seti dosyası (kanonik JSON), `fingerprint`.
- `report_text`: rapor metni; `records_text`: sinyal kayıtları (JSON Lines).
"""

from crytobot.calibration._outcome import (
    Costs,
    Count,
    Direction,
    Outcomes,
    PairSeries,
    Period,
    Tally,
    outcomes,
    tally,
)
from crytobot.calibration._records import records_text
from crytobot.calibration._report import (
    GENERATED_PREFIX,
    DataFacts,
    GapRow,
    ReportFacts,
    report_text,
)
from crytobot.calibration._settings_file import (
    SettingsProblem,
    SettingsSet,
    fingerprint,
    read_settings,
    settings_text,
)
from crytobot.calibration._signals import (
    INDICATORS,
    IndicatorSpec,
    Setting,
    Signals,
    grid,
    neighbours,
    setting_label,
    signals,
)
from crytobot.calibration._tuning import (
    CROSS,
    DATA_START,
    INTERVALS,
    PAIRS,
    PERIODS,
    TUNING,
    UNSEEN,
    Choice,
    CrossTest,
    IntervalData,
    Measured,
    Periods,
    Robustness,
    Verdict,
    cross_test,
    final_stage,
    robustness,
    select,
    stage_one,
    verdict,
)
from crytobot.calibration._unusual import unusual_flags

__all__ = [
    "CROSS",
    "DATA_START",
    "GENERATED_PREFIX",
    "INDICATORS",
    "INTERVALS",
    "PAIRS",
    "PERIODS",
    "TUNING",
    "UNSEEN",
    "Choice",
    "Costs",
    "Count",
    "CrossTest",
    "DataFacts",
    "Direction",
    "GapRow",
    "IndicatorSpec",
    "IntervalData",
    "Measured",
    "Outcomes",
    "PairSeries",
    "Period",
    "Periods",
    "ReportFacts",
    "Robustness",
    "Setting",
    "SettingsProblem",
    "SettingsSet",
    "Signals",
    "Tally",
    "Verdict",
    "cross_test",
    "final_stage",
    "fingerprint",
    "grid",
    "neighbours",
    "outcomes",
    "read_settings",
    "records_text",
    "report_text",
    "robustness",
    "select",
    "setting_label",
    "settings_text",
    "signals",
    "stage_one",
    "tally",
    "unusual_flags",
    "verdict",
]
