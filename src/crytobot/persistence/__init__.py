"""Kalıcı durum: defter, emirler (dolum tahminleri dahil) ve risk durumu tek SQLite deposunda.

`create_store` depoyu yalnız açık çağrıyla bir modla oluşturur; `load_store` durumun tamamını ya da
adlandırılmış bir sonuç döndürür, boş ya da kısmi durum döndürmez (BR-6). `save_store` üç durumu tek
işlemde yazar: son yükleme ya da kaydın sonucuna (`base`) dayanmayan kayıt "eski yazım", geçmişi
değiştiren kayıt "geçmiş değiştirilemez". Geçerli ama birbiriyle çelişen durum yüklenir ve
`StoreResult.conflicts` ile işaretlenir ("mutabakat tutmuyor"); alımı durdurmak `app`'in işidir.
Paper deposu ayrıca (spec 0038) yalnız eklenen başlatma kayıtlarını (`append_start_record`,
`load_start_records`) ve son turun anını (`mark_turn`, revizyonu artırmaz) tutar. Canlı depo
(spec 0041) açıldığı ağı (`NETWORKS`) kaydeder; kaydı olmayan depo `mainnet`'tir, `bind_network`
eksik kaydı yazar, farklı ağı reddeder.
Hiçbir işlem istisna fırlatmaz; dosya yolunu çağıran verir. Yalnız `app` import eder.
"""

from crytobot.persistence._codec import StartRecord
from crytobot.persistence._store import (
    FORMAT_VERSION,
    MAINNET,
    MODES,
    NETWORKS,
    StartRecordsResult,
    StoredState,
    StoreOutcome,
    StoreResult,
    append_audit_record,
    append_start_record,
    bind_network,
    create_store,
    load_audit_records,
    load_start_records,
    load_store,
    mark_turn,
    save_store,
)

__all__: list[str] = [
    "FORMAT_VERSION",
    "MAINNET",
    "MODES",
    "NETWORKS",
    "StartRecord",
    "StartRecordsResult",
    "StoreOutcome",
    "StoreResult",
    "StoredState",
    "append_audit_record",
    "append_start_record",
    "bind_network",
    "create_store",
    "load_audit_records",
    "load_start_records",
    "load_store",
    "mark_turn",
    "save_store",
]
