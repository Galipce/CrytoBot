# Spec 0024 — Bot ayar yükleyicisinin `[history]` bölümünü tanıması (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0024-plan.md`
- Self-critique: done
- Source: plan 0023, Risk 1 (R-10, karar A — Galip Badem, 2026-11-06)
- Supersedes: 0022/AC-3

## Intent
Botun sahibi, geçmiş veri indirmesinin (0023) ayarlarını botun ayar dosyasında bir `[history]` bölümüne yazabilmek istiyor. Bugün bot bu bölümü görünce
"bilinmeyen ayar: history" der, hazırlık ve başlatma reddedilir; bu yüzden 0023'ün BUILD'i bekliyor. Başarı: bot yükleyicisi `[history]`'yi tanır ve
içine bakmadan geçer, botun kendi ayarlarının denetimi aynen kalır, başka her bilinmeyen bölüm ve anahtar reddedilmeyi sürdürür. Bu iş indirme
ayarlarını denetlemez, indirme kodu yazmaz, turun davranışını değiştirmez.

## Changed behavior
- [x] CB-1 — `[history]` bölümü bulunan, botun ayarları geçerli bir ayar eşlemiyle bot ayar yükleyicisi geçerli sonuç verir ve ayarlar `[history]` yokken verilenle aynıdır; mesaj bugünkü gibi `ayarlar geçerli` olur. Bölüm isteğe bağlıdır: yokken de sonuç bugünkü gibidir.
- [x] CB-2 — Bot ayar yükleyicisi `[history]`'nin değerine bakmaz: boş tablo, bilinmeyen anahtarlar (`mode = "live"` dahil), biçimi geçersiz değerler, alt tablo ve tablo olmayan bir değer (metin, sayı, liste) ayarları reddettirmez. Bu değerler sonucun mesajında geçmez ve ayarlara taşınmaz.
- [x] CB-3 — Yalnız tam olarak `history` adı tanınır. `History`, `HISTORY`, `histroy`, `historyy`, `history_` adlı bölümler bugünkü gibi `bilinmeyen ayar: <ad>` ile, o adla reddedilir.
- [x] CB-4 — Giriş noktası: `[history]` bölümü eklenmiş bir ayar dosyasıyla hazırlık depoyu oluşturur, başlatma da sahte borsayla tur atar. Hiçbiri "bilinmeyen ayar" demez.

## Preserved behavior
- [x] PB-1 — `test_unknown_setting_is_refused`'ın bugünkü örnekleri aynen reddedilir (`bot.mode`, `risk.api_key`, `live` bölümü) ve mesajları değişmez. Beş bölümün (`bot`, `market`, `turn`, `risk`, `strategy`) her birinde bilinmeyen anahtar `bilinmeyen ayar: <bölüm>.<anahtar>` ile reddedilir.
- [x] PB-2 — `[history]` varken de bilinmeyen başka bir bölüm, o bölümün adıyla reddedilir.
- [x] PB-3 — `[history]` varken de botun her eksik ve geçersiz ayarı, her eksik ya da bozuk bölüm ve tablo olmayan bir ayar eşlemi bugünkü adla ve mesajla reddedilir. Yalnız `[history]` bulunan bir eşlem `ayar eksik: bot` ile reddedilir. İlk sorun dosya sırasıyla söylenir (0022/AC-3).
- [x] PB-4 — `SETTING_NAMES` ve `BotConfig`'in alanları değişmez. `tests/app/test_config.py`'nin geri kalan testleri ve assert'leri aynen kalır.
- [x] PB-5 — `_config.py` dışındaki `src/` kodu, `crytobot.example.toml`, `scripts/check.conf` ve `.github/` değişmez; turun davranışı değişmez. `./scripts/doctor --strict` geçer.

## Constraints
- Sensitive area: doğrudan yok. Paper ↔ live mod anahtarına (`docs/domain.md`) dolaylı olarak değiyor: bugünkü bilinmeyen anahtar reddi `bot.mode`'u da yakalıyor. `history.mode` CB-2 gereği geçilir. Botta mod alanı olmadığı (0022 R-1) ve bot `[history]`'nin değerini okumadığı için hiçbir davranışı değiştiremez. Beş bot bölümündeki ret PB-1 ile korunur. `[history]`'nin içini indirme yükleyicisi denetler (0023 R-2, AC-3). Karar: Galip Badem, 2026-11-06 (clarify 4).
- Supersedes kapsamı: 0022/AC-3'ün yalnız "bilinmeyen ayar reddedilir" kısmı, o da yalnız `history` adı için. AC-3'ün geri kalanı geçerlidir. Dayanak: `docs/testing.md`, "Lists that grow" (izin listesi kendi mini-spec'idir); emsal 0019.
- Korunan testler: `test_unknown_setting_is_refused` adını ve üç örneğini korur, hiçbir beklenti kaldırılmaz; `history` kabulü ve CB-3'ün ret örnekleri ayrı testlere eklenir. `_config.py`'nin dosya başı açıklaması yeni kuralı anlatacak biçimde güncellenir.
- CB-4'ün gerekçesi: sorun giriş noktasında görüldü (plan 0023, Risk 1: `start` ve `prepare` "bilinmeyen ayar: history" der); kanıt, gerçek dosyanın gerçek giriş noktasından geçmesidir. Karar: Galip Badem, 2026-11-06 (self-critique G-1; G-2 ve G-3 de işlendi).
- Numaralandırma: kural gereği bu spec 0024'tür (en yüksek numara + 1). 0023'ün Split satırı 0024'ü backtest'e, 0025'i BR-10 kapısına ayırmıştı; bu işler 0025 ve 0026 olur. 0023'ün dosyaları bu turda değişmez, eski göndermeleri 0023 kendi turunda düzeltir. Karar: Galip Badem, 2026-11-06 (clarify 1).

## Out of scope
- `[history]`'nin içeriğinin denetimi, `load_download_config`, indirme kodu ve `crytobot.example.toml`'a `[history]` örneği: 0023'e aittir.
- 0023'ün spec ve plan dosyaları; `specs/done/`.
- `BotConfig`'e alan ya da `SETTING_NAMES`'e ad eklemek.
- Bölüm adında büyük/küçük harf duyarsızlığı ya da başka bir bölüme izin vermek.

## Definition of Done
- [x] `scripts/check` green — `CHECK GREEN (full, 7 steps, 389 s)`, CI run 42213403068 @`9cf785e`
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [x] Spec moved to `specs/done/` (immutable there)
