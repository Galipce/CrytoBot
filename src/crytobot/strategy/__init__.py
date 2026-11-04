"""Sinyalleri birleştirip işlem önerisi (yön, giriş, stop, hedef) üretmek.

`propose`, bir mum serisinin son mumu için tek sonuç üretir: `risk`'in kabul ettiği alım önerisi
(`TradeIntent`) ya da adı konmuş bir "öneri yok" nedeni (`NoProposal`). Öneri koşulu: son mumda
hızlı EMA'nın yavaşı yukarı kesmesi ve RSI'nın eşiğin altında olması. Fiyatlar `Decimal` ve tick'in
katıdır; giriş yukarı, stop ve hedef aşağı yuvarlanır. Ayarların varsayılanı yoktur ve kârlılıkları
kanıtsızdır: stratejinin paper'a geçişi backtest kararına bağlıdır (BR-10). Geçersiz girdi adı
konmuş hatayla reddedilir. Saf hesaptır: `risk`'i çağırmaz, emir ya da pozisyon boyutu üretmez.
"""

from crytobot.strategy._inputs import (
    InputProblem,
    InvalidCandlesError,
    InvalidInputError,
    NonFiniteIndicatorError,
    StrategyError,
    StrategySettings,
)
from crytobot.strategy._proposal import NoProposal, NoProposalReason, propose

__all__: list[str] = [
    "InputProblem",
    "InvalidCandlesError",
    "InvalidInputError",
    "NoProposal",
    "NoProposalReason",
    "NonFiniteIndicatorError",
    "StrategyError",
    "StrategySettings",
    "propose",
]
