"""Geçmiş veri üzerinde strateji+risk+simüle execution koşturmak.

Spec 0025: koşunun kendisi (turlar, simüle saat) `app`'tedir; burada koşunun sonucu vardır.
`run_metrics` tur kayıtlarından (`TurnRecord`) örneklem içi, örneklem dışı ve tüm koşu için
metrikleri hesaplar (saf hesap). `report_text` raporu belirlenimci düz metin olarak yazar: koşunun
varsayımları, parçaların metrikleri; yalnız örneklem dışı "BR-10 kanıtı adayı"dır, hüküm yoktur.
`write_report` raporu `.part` üzerinden, var olan dosyanın üzerine yazmadan diske koyar;
`report_exists` yolda ya da `.part` yolunda bir şey olup olmadığını söyler. `report_fingerprint`
yazılan baytların SHA-256 özetidir (spec 0040). `app` ve
`market_data` import edilmez.
"""

from crytobot.backtest._metrics import (
    PartMetrics,
    RunMetrics,
    TurnRecord,
    part_metrics,
    run_metrics,
    unrealized,
)
from crytobot.backtest._report import (
    ASSUMPTIONS,
    CANDIDATE_MARK,
    CONDITIONS,
    GENERATED_LABEL,
    ReportFacts,
    money,
    percent,
    ratio,
    report_text,
)
from crytobot.backtest._report_file import (
    PART_SUFFIX,
    report_exists,
    report_fingerprint,
    write_report,
)
from crytobot.backtest._report_read import (
    CandidateMetrics,
    ParsedReport,
    ReportRead,
    ReportReadProblem,
    parse_report,
    read_report,
)

__all__: list[str] = [
    "ASSUMPTIONS",
    "CANDIDATE_MARK",
    "CONDITIONS",
    "GENERATED_LABEL",
    "PART_SUFFIX",
    "CandidateMetrics",
    "ParsedReport",
    "PartMetrics",
    "ReportFacts",
    "ReportRead",
    "ReportReadProblem",
    "RunMetrics",
    "TurnRecord",
    "money",
    "parse_report",
    "part_metrics",
    "percent",
    "ratio",
    "read_report",
    "report_exists",
    "report_fingerprint",
    "report_text",
    "run_metrics",
    "unrealized",
    "write_report",
]
