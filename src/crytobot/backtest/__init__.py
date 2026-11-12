"""Geçmiş veri üzerinde strateji+risk+simüle execution koşturmak.

Spec 0025: koşunun kendisi (turlar, simüle saat) `app`'tedir; burada koşunun sonucu vardır.
`run_metrics` tur kayıtlarından (`TurnRecord`) örneklem içi, örneklem dışı, saklı dönem (verildiyse)
ve tüm koşu için metrikleri hesaplar (saf hesap). `report_text` varsayılan raporu belirlenimci düz
metin olarak yazar: koşunun varsayımları ve yalnız örneklem içi metrikler; aday işareti, hüküm yok.
`write_report` raporu `.part` üzerinden, var olan dosyanın üzerine yazmadan diske koyar;
`report_exists` yolda ya da `.part` yolunda bir şey olup olmadığını söyler. `report_fingerprint`
yazılan baytların SHA-256 özetidir (spec 0040). Spec 0042: değerlendirme kuralı
(`select_combination`, `verdict`, `paper_candidate`; eşikler kodda sabit), saklı dönem metriği ve
son değerlendirme raporu (`final_report_text`); aşama kapısı yalnız son değerlendirme raporunu okur
(`NOT_FINAL`). `app` ve `market_data` import edilmez.
"""

from crytobot.backtest._evaluation import (
    HOLDOUT_DRAWDOWN,
    HOLDOUT_NET,
    MAX_DRAWDOWN,
    MIN_PROFIT_FACTOR,
    MIN_TRADES,
    NOT_ENOUGH_TRADES,
    OOS_DRAWDOWN,
    OOS_NET,
    OOS_PROFIT_FACTOR,
    OOS_TRADES,
    PASSED,
    Assessed,
    not_enough_trades,
    paper_candidate,
    select_combination,
    verdict,
)
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
    FINAL_TITLE,
    GENERATED_LABEL,
    NO_CANDIDATE,
    NO_GAPS,
    TITLE,
    CandidateResult,
    DataGap,
    IntervalData,
    ReportFacts,
    final_report_text,
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
    "FINAL_TITLE",
    "GENERATED_LABEL",
    "HOLDOUT_DRAWDOWN",
    "HOLDOUT_NET",
    "MAX_DRAWDOWN",
    "MIN_PROFIT_FACTOR",
    "MIN_TRADES",
    "NOT_ENOUGH_TRADES",
    "NO_CANDIDATE",
    "NO_GAPS",
    "OOS_DRAWDOWN",
    "OOS_NET",
    "OOS_PROFIT_FACTOR",
    "OOS_TRADES",
    "PART_SUFFIX",
    "PASSED",
    "TITLE",
    "Assessed",
    "CandidateMetrics",
    "CandidateResult",
    "DataGap",
    "IntervalData",
    "ParsedReport",
    "PartMetrics",
    "ReportFacts",
    "ReportRead",
    "ReportReadProblem",
    "RunMetrics",
    "TurnRecord",
    "final_report_text",
    "money",
    "not_enough_trades",
    "paper_candidate",
    "parse_report",
    "part_metrics",
    "percent",
    "ratio",
    "read_report",
    "report_exists",
    "report_fingerprint",
    "report_text",
    "run_metrics",
    "select_combination",
    "unrealized",
    "verdict",
    "write_report",
]
