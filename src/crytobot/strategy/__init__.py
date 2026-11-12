"""Sinyalleri birleştirip işlem önerisi (yön, giriş, stop, hedef) üretmek.

`propose`, bir mum serisinin son mumu için tek sonuç üretir: `risk`'in kabul ettiği alım önerisi
(`TradeIntent`) ya da adı konmuş bir "öneri yok" nedeni (`NoProposal`). Ayarın tipi adayı seçer
(spec 0043 R-2, `CANDIDATES`): S0 (`StrategySettings`) son mumda hızlı EMA'nın yavaşı yukarı
kesmesi ve RSI'nın eşiğin altında olması; S1 (`TrendFilterSettings`) S0 ve son kapanışın trend
ortalamasının üzerinde olması; S2 (`BreakoutSettings`) son kapanışın önceki N mumun en yüksek
fiyatını aşması; S3 (`TrendDipSettings`) son kapanışın 200 mumluk ortalamanın üzerinde ve RSI'nın
aşırı satım eşiğinin altında olması. Her adayın önerisi aynı kuralla kurulur: k*ATR stop, r*risk
hedef. `required_candles` adayın en uzun göstergesinin istediği mum sayısıdır (R-4). Fiyatlar
`Decimal` ve tick'in katıdır; giriş yukarı, stop ve hedef aşağı yuvarlanır. Ayarların varsayılanı
yoktur ve kârlılıkları kanıtsızdır: stratejinin paper'a geçişi backtest kararına bağlıdır (BR-10).
Geçersiz girdi adı konmuş hatayla reddedilir. Saf hesaptır: `risk`'i çağırmaz, emir ya da pozisyon
boyutu üretmez.
"""

from crytobot.strategy._inputs import (
    CANDIDATES,
    S3_TREND_PERIOD,
    BreakoutSettings,
    InputProblem,
    InvalidCandlesError,
    InvalidInputError,
    NonFiniteIndicatorError,
    Parameters,
    Settings,
    StrategyError,
    StrategySettings,
    TrendDipSettings,
    TrendFilterSettings,
    candidate,
    candidate_parameters,
    required_candles,
)
from crytobot.strategy._proposal import NoProposal, NoProposalReason, propose

__all__: list[str] = [
    "CANDIDATES",
    "S3_TREND_PERIOD",
    "BreakoutSettings",
    "InputProblem",
    "InvalidCandlesError",
    "InvalidInputError",
    "NoProposal",
    "NoProposalReason",
    "NonFiniteIndicatorError",
    "Parameters",
    "Settings",
    "StrategyError",
    "StrategySettings",
    "TrendDipSettings",
    "TrendFilterSettings",
    "candidate",
    "candidate_parameters",
    "propose",
    "required_candles",
]
