# Spec 0026 — Bot ayar yükleyicisinin `[backtest]` bölümünü tanıması ve `app`'in `backtest`'i import etmesi (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0026-plan.md`
- Self-critique: done
- Source: plan 0025, Risk 2 (R-10, karar: Galip Badem, 2026-11-06)
- Supersedes: 0022/AC-3, 0016/AC-13

## Intent
Botun sahibi, backtest koşusunun (0025) ayarlarını botun ayar dosyasında bir `[backtest]` bölümüne yazabilmek istiyor. Bugün bot bu bölümü görünce "bilinmeyen ayar: backtest" der. Hazırlık, başlatma ve indirme bu yüzden reddedilir. Ayrıca `app`'in import izin listesinde `crytobot.backtest` yoktur. Bu iki engel yüzünden 0025'in BUILD'i bekliyor. Başarı şöyle görünür: bot yükleyicisi `[backtest]`'i tanır ve içine bakmadan geçer, `app` de `crytobot.backtest`'in yalnız kökünü import edebilir. Botun kendi ayarlarının denetimi ve `app`'in öteki import sınırları aynen kalır. Bu iş backtest ayarlarını denetlemez, backtest kodu yazmaz, turun davranışını değiştirmez.

## Changed behavior
- [ ] CB-1 — `[backtest]` bölümü bulunan ve botun ayarları geçerli olan bir ayar eşlemiyle bot ayar yükleyicisi geçerli sonuç verir. Ayarlar, `[backtest]` yokkenkiyle aynıdır ve mesaj bugünkü gibi `ayarlar geçerli` olur. Bölüm isteğe bağlıdır: yokken de sonuç bugünkü gibidir. `[history]` ile birlikte bulunduğunda da aynısı geçerlidir.
- [ ] CB-2 — Bot ayar yükleyicisi `[backtest]`'in değerine bakmaz. Boş tablo, bilinmeyen anahtarlar (`mode = "live"` dahil), biçimi geçersiz değerler, alt tablo ve tablo olmayan değer (metin, sayı, liste) ayarları reddettirmez. Bu değerler sonucun mesajında geçmez ve ayarlara taşınmaz.
- [ ] CB-3 — Yalnız tam olarak `backtest` adı tanınır. `Backtest`, `BACKTEST`, `bactest`, `backtests`, `backtest_`, `back_test` adlı bölümler bugünkü gibi `bilinmeyen ayar: <ad>` ile ve o adla reddedilir.
- [ ] CB-4 — `app`'in import sınır testi `crytobot.backtest`'i kabul eder ama yalnız kökünü: `import crytobot.backtest` ve `from crytobot.backtest import <ad>` kabul edilir. `crytobot.backtest._<alt modül>` gibi alt modül importu ve `from crytobot.backtest import *` reddedilir (0019 emsali, R-3d).
- [ ] CB-5 — Giriş noktası: `[backtest]` bölümü eklenmiş bir ayar dosyasıyla hazırlık depoyu oluşturur, başlatma sahte borsayla tur atar, indirme de ayarları kabul eder. Hiçbiri "bilinmeyen ayar" demez.

## Preserved behavior
- [ ] PB-1 — `test_unknown_setting_is_refused`'ın bugünkü örnekleri aynen reddedilir ve mesajları değişmez. Beş bot bölümünün her birinde bilinmeyen anahtar, `[backtest]` varken de `bilinmeyen ayar: <bölüm>.<anahtar>` ile reddedilir.
- [ ] PB-2 — `[backtest]` varken de bilinmeyen başka bir bölüm o bölümün adıyla reddedilir. `[history]`'nin geçilmesi (0024) ve CB-3 örnekleri değişmez.
- [ ] PB-3 — `[backtest]` varken de botun her eksik ve geçersiz ayarı, her eksik ya da bozuk bölümü ve tablo olmayan bir ayar eşlemi bugünkü adla ve mesajla reddedilir. Yalnız `[backtest]` bulunan bir eşlem `ayar eksik: bot` ile reddedilir. İlk sorun dosya sırasıyla söylenir (0022/AC-3).
- [ ] PB-4 — `app`'in öteki import sınırları aynen kalır: izin listesindeki öteki adlar, `market_data`'nın yalnız kök kuralı, okuma işlevinin adının geçmemesi (0019) ve `test_boundaries.py`'deki her mevcut ret örneği. Hiçbir beklenti kaldırılmaz.
- [ ] PB-5 — `SETTING_NAMES` ve `BotConfig`'in alanları değişmez. `load_download_config`'in `[history]` denetimi ve mesajları değişmez. `_config.py` dışındaki `src/` kodu, `pyproject.toml`, `crytobot.example.toml`, `scripts/check.conf` ve `.github/` değişmez. Turun davranışı değişmez. `./scripts/doctor --strict` geçer.

## Constraints
- Sensitive area: doğrudan yok. Paper ↔ live mod anahtarına (`docs/domain.md`) dolaylı olarak değiyor: `backtest.mode` CB-2 gereği geçilir. Botta mod alanı olmadığı (0022 R-1) ve bot `[backtest]`'in değerini okumadığı için bu hiçbir davranışı değiştiremez. `[backtest]`'in içini 0025'in yükleyicisi denetler (0025 R-2). Emsal: 0024 Constraints.
- Supersedes kapsamı: 0022/AC-3'ün yalnız "bilinmeyen ayar reddedilir" kısmı, o da yalnız `backtest` adı için. 0016/AC-13'ün yalnız "import sınırları" kısmı, o da yalnız `crytobot.backtest`'in kökü için. İki kriterin geri kalanı geçerlidir. Dayanak: `docs/testing.md`, "Lists that grow": izin listesine ekleme kendi mini-spec'idir. Emsaller 0019 ve 0024.
- CB-4 neden yalnız kök: R-3d (`pyproject.toml`) zaten başka modülün iç alt modülünün importunu yasaklıyor. Test aynı kuralı `market_data` gibi kaynak üzerinde de sınar. `backtest` paketi 0025'te yazılacağı için bugün yoktur. Testin kaynak üzerindeki kontrolü paketin varlığına bağlı değildir.
- `import-linter`'ın `pyproject.toml` sözleşmeleri değişmez. `backtest`'in `app`'i import etmemesi 0025'in sözleşmesidir.
- Korunan testler: `test_unknown_setting_is_refused` ve 0024'ün `history` testleri adlarını ve örneklerini korur. `backtest` kabulü ve ret örnekleri ayrı testlere eklenir. `ALLOWED_MODULES` dokunulmaz. `crytobot.backtest`, `ROOT_ONLY_MODULES`'e eklenir: listeye ekleme hiçbir beklentiyi kaldırmaz. `_config.py`'nin ve `test_boundaries.py`'nin dosya başı açıklaması yeni kuralı anlatır.
- Numaralandırma: kural gereği bu spec 0026'dır. 0025'teki BR-10 kapısı atıfları numarasız ("BR-10 kapı spec'i") yazıldı. Karar: Galip Badem, 2026-11-06 (plan 0025 Risk 2).

## Out of scope
- `[backtest]`'in içeriğinin denetimi, `load_backtest_config`, backtest kodu, `crytobot.backtest` paketinin kendisi ve `crytobot.example.toml`'a `[backtest]` örneği: 0025'e aittir.
- 0025'in spec ve plan dosyaları; `specs/done/`.
- `BotConfig`'e alan ya da `SETTING_NAMES`'e ad eklemek; `import-linter` sözleşmeleri.
- Bölüm adında büyük/küçük harf duyarsızlığı ya da başka bir bölüme izin vermek.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [ ] Spec moved to `specs/done/` (immutable there)
