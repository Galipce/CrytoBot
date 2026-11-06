"""Geçmiş veri üzerinde strateji+risk+simüle execution koşturmak.

Spec 0025: koşunun kendisi (turlar, simüle saat) `app`'tedir; burada koşunun sonucu vardır.
`run_metrics` tur kayıtlarından (`TurnRecord`) örneklem içi, örneklem dışı ve tüm koşu için
metrikleri hesaplar (saf hesap). `app` ve `market_data` import edilmez.
"""

from crytobot.backtest._metrics import (
    PartMetrics,
    RunMetrics,
    TurnRecord,
    part_metrics,
    run_metrics,
    unrealized,
)

__all__: list[str] = [
    "PartMetrics",
    "RunMetrics",
    "TurnRecord",
    "part_metrics",
    "run_metrics",
    "unrealized",
]
