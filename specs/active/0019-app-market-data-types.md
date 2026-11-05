# Spec 0019 — `app`'in `market_data` tiplerini import etmesi (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0019-plan.md`
- Self-critique: done
- Source: plan 0017, A-1
- Supersedes: 0016/AC-13

## Intent
Sistemin sahibi, gerçek piyasa okumasının sonucunun `app` içinde tur girdisine çevrilebilmesini istiyor (0017, R-10). Bugün 0016/AC-13'ün izin
listesi `app`'in `market_data` import etmesini reddediyor, bu yüzden 0017'nin 6. ve 7. adımları duruyor. Başarı: `app` `market_data`'nın public
tiplerini import edebilir, okuma işlevini kullanamaz ve izin listesi başka her şeyi reddetmeyi sürdürür. Bu iş çeviri kodu yazmaz, borsaya
bağlanmaz, turun davranışını değiştirmez.

## Changed behavior
- [ ] CB-1 — `app` import denetimi `crytobot.market_data` kökünden yapılan import'u kabul eder (`import crytobot.market_data`, `from crytobot.market_data import MarketRead`). İzin listesine bundan başka modül eklenmez.
- [ ] CB-2 — `app` import denetimi `market_data`'nın okuma işlevini her biçimde reddeder: adıyla import (`from crytobot.market_data import read_market_data`), takma adla import (`... import read_market_data as r`), yıldızlı import (`from crytobot.market_data import *`) ve modül üzerinden erişim (`crytobot.market_data.read_market_data`). Her biçim testte ayrı bir örnektir.
- [ ] CB-3 — `read_market_data` adı `app` kaynağındaki hiçbir `.py` dosyasında geçmez; yorum, docstring ve metin değerleri dahildir. Denetim klasördeki her dosyaya uygulanır, sonradan eklenen dosya da kapsamdadır.

## Preserved behavior
- [ ] PB-1 — `test_import_guard_catches_forbidden_code`'un kalan örnekleri reddedilmeyi sürdürür: `import ccxt`, `import socket`, `from crytobot.reporting import x`, `from crytobot.control import x`, `from . import x`, işlev içindeki `import sqlite3`. Listeden yalnız CB-1'in kabul ettiği `from crytobot.market_data import x` çıkar.
- [ ] PB-2 — `market_data`'nın iç alt modülünü `app`'ten import etmek `boundaries` adımında kırmızıdır (R-3d): `from crytobot.market_data._client import x` ve `from crytobot.market_data import _client`.
- [ ] PB-3 — `tests/app/test_boundaries.py`'nin saat ve `global` denetimi, düz `dict`, kâr girdisi ve `.realized` testleri ile bunların assert'leri aynen kalır.
- [ ] PB-4 — `src/`, `tools/`, `pyproject.toml`'un `import-linter` sözleşmeleri, `scripts/check.conf` ve `.github/` değişmez; `run_turn` davranışı değişmez. `./scripts/doctor --strict` geçer.

## Constraints
- Sensitive area: yok; `docs/domain.md`'deki hassas alanlara dokunulmaz. `app` yalnız coverage kapısındaki hassas modüllerdendir, üretim kodu değişmediği için kapı etkilenmez.
- Supersedes kapsamı: 0016/AC-13'ün yalnız `app` import sınırı bölümü. Aynı kriterin B-6, B-16 ve BR-1 bölümleri geçerlidir. Dayanak: `docs/testing.md`, "Lists that grow" (izin listesi, kendi mini-spec'i); emsal 0018.
- Korunan testler: `test_app_imports_only_allowed_modules` ve `test_import_guard_catches_forbidden_code` adlarını korur. Tek kaldırılan beklenti PB-1'deki örnektir; yerine CB-1'in kabul testi gelir. Dosya başı açıklaması yeni kuralı anlatacak biçimde güncellenir.
- CB-2 ve CB-3'ün gerekçesi: bugünkü import yasağı `app`'in borsaya çıkmamasını da dolaylı olarak güvenceye alıyor (0016, Out of scope: `market_data`, ağ, ccxt). Karar (A seçeneği): Galip Badem, 2026-11-05.
- CB-3 yorum ve docstring'i de kapsar: böylece metin üzerinden erişim de kapanır, ölçüt tek ve basit kalır (emsal: aynı dosyadaki `.realized` testi). Bedel: 0017'nin 6. adımında `app` docstring'i işlevi adıyla anamaz.

## Out of scope
- Çeviri kodu (`to_turn_market`), `app/_market.py` ve 0017'nin geri kalanı; 0017'nin spec ve plan dosyaları.
- `app`'in okumayı çağırması. Giriş noktası spec'i bunu isterse CB-2 ve CB-3'ü kendi mini-spec'iyle kaldırır.
- `crytobot.app` import edilince `ccxt`'nin yüklenmemesini kanıtlamak: bugün `app` `market_data` import etmediği için burada sınanamaz; 0017'nin 6. adımına aittir.
- `docs/architecture.md`: `app`'in modülleri bağlaması zaten yazılıdır, değişmez. Yeni `import-linter` sözleşmesi eklenmez (`test_clean_tree_passes`'in "5 kept" assert'i değişmesin diye).
- `specs/done/`.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [ ] Spec moved to `specs/done/` (immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | |
| Fix rounds | |
| Review findings: real / noise / deferred | |
| Regressions introduced | |
| Bugs escaped to production | |
