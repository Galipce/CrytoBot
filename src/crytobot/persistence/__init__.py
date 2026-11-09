"""Kalıcı durum: defter, emirler (dolum tahminleri dahil) ve risk durumu tek SQLite deposunda.

`create_store` depoyu yalnız açık çağrıyla bir modla oluşturur; `load_store` durumun tamamını ya da
adlandırılmış bir sonuç döndürür, boş ya da kısmi durum döndürmez (BR-6). `save_store` üç durumu tek
işlemde yazar: son yükleme ya da kaydın sonucuna (`base`) dayanmayan kayıt "eski yazım", geçmişi
değiştiren kayıt "geçmiş değiştirilemez". Geçerli ama birbiriyle çelişen durum yüklenir ve
`StoreResult.conflicts` ile işaretlenir ("mutabakat tutmuyor"); alımı durdurmak `app`'in işidir.
Hiçbir işlem istisna fırlatmaz; dosya yolunu çağıran verir. Yalnız `app` import eder.
"""

from crytobot.persistence._store import (
    FORMAT_VERSION,
    MODES,
    StoredState,
    StoreOutcome,
    StoreResult,
    append_audit_record,
    create_store,
    load_audit_records,
    load_store,
    save_store,
)

__all__: list[str] = [
    "FORMAT_VERSION",
    "MODES",
    "StoreOutcome",
    "StoreResult",
    "StoredState",
    "append_audit_record",
    "create_store",
    "load_audit_records",
    "load_store",
    "save_store",
]
