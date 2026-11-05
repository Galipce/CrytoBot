# Spec 0018 — `ccxt` runtime bağımlılığı (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0018-plan.md`
- Self-critique: done
- Source: plan 0017, Risk 1
- Supersedes: 0001/AC-10

## Intent
Sistemin sahibi, `market_data`'nın (spec 0017) gerçek borsa verisi okuyabilmesi için `ccxt`'nin projenin onaylı tek runtime bağımlılığı olmasını
istiyor. Bugün 0001/AC-10 runtime bağımlılığını yasaklıyor ve test bunu kesin listeyle zorluyor, bu yüzden 0017'nin BUILD'i başlayamıyor. Başarı:
`ccxt` bildirilmiş ve kilitlenmiş olur, izin listesi yine "başka hiçbir şey kabul edilmez" der, denetim kayıtlı kalır. Bu iş `ccxt` kullanan kod
yazmaz, borsaya bağlanmaz, botun davranışını değiştirmez. 0017 ship edilene kadar `ccxt` kurulu ama kullanılmıyor olur.

## Changed behavior
- [x] CB-1 — `pyproject.toml`'un doğrudan runtime bağımlılığı tam olarak birdir: `ccxt>=4.5,<5`.
- [x] CB-2 — `uv.lock`'ta projenin doğrudan runtime bağımlılığı tam olarak `ccxt`'dir; `ccxt` ve dolaylı bağımlılıkları sürüm ve hash ile sabittir; kilit `pyproject.toml` ile tutarlıdır (`uv lock --check` temiz).
- [x] CB-3 — `tests/test_dependencies.py` runtime listesini kesin ad listesi olarak zorlar, hem `pyproject.toml` hem `uv.lock` için: başka bir ad eklenince ya da `ccxt` çıkınca kırmızı olur; `ccxt` sürüm aralığı değişince kırmızı olmaz.
- [x] CB-4 — `docs/security.md`, "Dependencies" bölümünde tek satırlık istisna taşır: dolaylı bağımlılıkta MPL-2.0, kod değiştirilmeden kullanım kabul (spec 0018). Bölümün diğer satırları aynı kalır.
- [x] CB-5 — CI'daki `pip-audit` (`--strict`, hash'li kilit çıktısı) `ccxt` ve dolaylı bağımlılıklarıyla yeşildir. Açık bulunursa ship durur: açık yok sayılmaz, bu spec içinde istisna tanımlanmaz, çözüm ayrı karar olarak sahibine gelir. Kanıt ship PR'ının `audit` işidir: VERIFY tablosu bunu "PR'da bekleniyor" diye gösterir, iş yeşil olmadan merge olmaz.

## Preserved behavior
- [x] PB-1 — Geliştirme araçları listesi aynen kalır (`hypothesis`, `import-linter`, `mypy`, `pytest`, `pytest-cov`, `pytest-socket`, `ruff`); tek grup `dev`'dir; `optional-dependencies` yoktur. Bunları zorlayan assert'ler değişmez.
- [x] PB-2 — Kilitte bugün bulunan paketlerin sürümleri ve hash'leri değişmez; fark yalnız yeni paketler ve proje girdisidir.
- [x] PB-3 — 0001/AC-10'un ikinci yarısı geçerlidir: `check` kilit dosyasını değiştirmez, koşu sonrası `git status` temizdir.
- [x] PB-4 — `src/`, `tools/`, `scripts/` ve `.github/` değişmez; `src` içinde `ccxt` import eden kod yoktur. Testler ağa çıkmaz (`--disable-socket`). `./scripts/doctor --strict` geçer.
- [x] PB-5 — `uv sync --locked` hem bu makinede (Windows) hem CI'da (`ubuntu-latest`) başarılı olur; `check` iki ortamda da yeşildir.

## Constraints
- Sensitive area: yok; `docs/domain.md`'deki hassas alanlara dokunulmaz.
- Yeni runtime bağımlılığı onayı: Galip Badem, 2026-11-05 (spec 0017, Constraints); sürüm kısıtı ve MPL-2.0 kararı: Galip Badem, 2026-11-05 (bu spec'in ANALYZE'ı).
- Denetim kaydı (2026-11-05):
  - Kimlik: `ccxt`, PyPI; ana sayfa `ccxt.com`.
  - Lisans (PyPI üst verisi, her paketin son sürümü): `ccxt` MIT. Dolaylı bağımlılıklar MIT, MIT-0, BSD-3-Clause, Apache-2.0 ve PSF-2.0; istisna `certifi` (MPL-2.0) ve `orjson` (MPL-2.0 ile Apache-2.0/MIT).
  - MPL-2.0 gerekçesi: lisans dosya düzeyindedir, kod değiştirilmez ve dağıtılmaz, proje kişiseldir.
  - PSF-2.0 (`aiohappyeyeballs`, `zlib-ng`, `typing-extensions`) ve MIT-0 (`cffi`) izinli lisanstır, paylaşım koşulu yoktur; "MIT/BSD/Apache uyumlu" kapsamında sayılır, istisna gerekmez.
  - Bakım ve CVE: `ccxt` 4.5.92, son sürüm 2026-11-04, son 6 sürüm üç haftada; `pip-audit` bilinen açık bulmadı (plan 0017, Risk 16).
  - Kilit denemesi (repo dışı kopya): `ccxt` 4.5.92 çözülür, paket sayısı 25'ten 48'e çıkar, mevcut sürümler değişmez.
- Dolaylı paket yükseltmesi `ccxt`'ye bağlıdır: `ccxt` bazı dolaylı paketleri son sürümün gerisinde tutar (deneme: `multidict` 6.9.1, son 7.2.1; `cffi` 2.0.0, son 2.1.1; neden plan 0017, Risk 16). Dolaylı bir pakette açık çıkarsa düzeltme `ccxt` yükseltmesi gerektirebilir; bu CB-5'teki gibi ayrı karardır.
- Korunan testler: `test_only_approved_dev_dependencies` ve `test_lockfile_direct_dependencies_are_only_approved_dev_tools` adlarını korur, yalnız dosya başındaki açıklama cümlesi güncellenir. `ccxt` için ayrı ve adlı test eklenir; `== []` assert'lerinin yerini bu `{ccxt}` kontrolü alır (dayanak: `Supersedes: 0001/AC-10`). Diğer assert'ler değişmez.

## Out of scope
- `ccxt` kullanan kod, `market_data`, mypy override'ı, `ccxt` import sınırı testi, `docs/security.md`'nin borsa yanıtı satırı: hepsi spec 0017'de.
- `docs/conventions.md`'nin "Ana kütüphaneler" satırı ve `pydantic`, `anthropic` gibi diğer kütüphaneler.
- `ccxt` sürümünü yükseltme düzeni; 0017'nin spec ve plan dosyaları; `scripts/check.conf`, CI ve `specs/done/`.

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [x] Spec moved to `specs/done/` (immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 onay sonrası; plan: A-1 |
| Fix rounds | 1 (fix-1, yalnız doküman; re-review gerekmedi) |
| Review findings: real / noise / deferred | 1 / 2 / 0 (L-1; I-1, I-2). VERIFY bulgusu yok |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (henüz üretim yok) |

CB-5, PB-4'ün `doctor` işi, PB-5'in Ubuntu `check` işi ve DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `audit`, `doctor` ve `check` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10).
