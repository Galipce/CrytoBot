# ADR 0001 — Kalıcı durum ayrı `persistence` modülünde, tek SQLite işleminde

- Status: Accepted
- Date: 2026-11-03

## Context
Spec 0011 defter, emirler ve risk durumunun yeniden başlatmada birebir korunmasını ister. Üçü tek işlemde yazılmalıdır
(R-5). `docs/architecture.md`'ye göre `execution`'ı yalnız `risk`, `app`, `backtest` import edebiliyordu; `portfolio` ya da
`execution` üç durumu birden göremez. Spec, kodun yerini ve modül sınırını plana bırakır.

## Decision
Yeni `persistence` modülünü yalnız `app` import eder; modül diğerlerinin public arayüzünü kullanır. Her modül kendi durumunun
doğrulayıcısını sağlar (`ledger_problems`, `execution_problems`, `risk_state_problems`). Satırlar metin alanlı JSON'dur;
geçmiş karşılaştırması bu metin üstünden yapılır. Yazım baştan `BEGIN EXCLUSIVE` alır, yükleme de `mode=rw` açar.
`base` (son yükleme ya da kaydın sonucu) revizyon taşır; bağlantı ya da kilit durumda tutulmaz.

## Consequences
- Bir modül daha: `execution` import kuralı genişler, `R-3e` sözleşmesi ve ayrı %90 coverage kapısı gelir.
- Doğrulama kuralı verinin sahibinde kalır; ama `portfolio/_replay.py` motorun hesabını ikinci kez yazar, çünkü motoru
  tekrar çalıştırmak 10.000 kayıtta O(n²) olur. İkisinin aynı kaldığını test kanıtlar; hesap değişirse ikisi de değişir.
- Yazım sırasında okur kısa süre bekler; tek süreçli botta önemsiz.
- Her kayıt tüm durumu doğrular ve satırları okur: kayıt süresi defterle büyür (R-11 varsayımı 10.000 kayıt).

## Alternatives considered
- **Kodu `app` içine koymak:** shipped modül sayısı testi değişmezdi, ama bileşim köküne SQL ve hassas kural yığılırdı.
- **Modül başına ayrı depo:** tek işlem sözü (R-5) tutmaz, bir modül diğerinin türünü bilmeden çelişki aranamaz.
- **Sütunlu tablolar:** sorgu kolaylığı bugün gerekmiyor; alan başına eşleme ve biçim değişikliği maliyeti artardı.
- **`BEGIN IMMEDIATE`:** `COMMIT` ikinci kez bekleyebilir, 5 saniye sınırı (R-10) tek zaman aşımıyla tutmazdı.

## Revisit triggers
- 10.000 kayıt sınırını aşan hacim, ya da kayıt süresinin döngüyü geciktirmesi.
- Live: emri göndermeden önce yazma kuralı (spec 0011 Constraints) yazım akışını değiştirirse.
- Satırları SQL ile sorgulama ihtiyacı.
