"""Bileşim kökü: modülleri bağlar, zamanlayıcı/döngü.

Bugün yalnız `run_turn` vardır (spec 0016): verilen piyasa verisi, ayarlar, depo yolu, zaman, paper
simülatörü ve bildirim alıcısıyla tek paper turu. Sıra: depoyu yükle → bilinmeyen emirleri sorgula →
kasayı gözle → stop ve hedef kapanışları → kasayı gözle → beyaz liste sırasıyla alım; her adım
kaydedilir. Belirsiz durumda alım durur, kapanış sürer, bildirim gider (BR-11). Tur istisna
fırlatmaz, her zaman paper'dır ve yalnız testlerde sahte veriyle koşar: giriş noktası, döngü, CLI ve
gerçek veri yoktur; gerçek paper başlatma BR-10'a bağlıdır.
"""

from crytobot.app._inputs import PairMarket, TurnSettings
from crytobot.app._notices import NoticeKind, TurnMemory, TurnNotice
from crytobot.app._result import BuyHalt, PairNote, PairOutcome, TurnOutcome, TurnResult
from crytobot.app._turn import run_turn

__all__: list[str] = [
    "BuyHalt",
    "NoticeKind",
    "PairMarket",
    "PairNote",
    "PairOutcome",
    "TurnMemory",
    "TurnNotice",
    "TurnOutcome",
    "TurnResult",
    "TurnSettings",
    "run_turn",
]
