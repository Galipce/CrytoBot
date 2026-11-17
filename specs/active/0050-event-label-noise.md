# Spec 0050 — Olay etiketlerinde gürültü temizliği (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0050-plan.md`
- Self-critique: done
- Source: B-93 (`specs/backlog.md`; spec 0049 koşu kaydının etiket denetimi)
- Design: —
- Supersedes: 0048/AC-1'in "vadeli / marjin listeleme", "listeden çıkarma" ve "spot listeleme" türlerinin başlık kuralları (davranış; `specs/done/0048-event-sample-library.md` değişmez)

## Intent
0049'daki ilk gerçek koşunun etiket denetimi üç türde gürültü gösterdi. "Vadeli / marjin listeleme" altındaki 2255 duyurunun yaklaşık 1245'i bir coin için yeni kontrat ya da marjin açılışı değil (kampanya, bonus, yarışma, limit, sistem duyurusu). "Listeden çıkarma" altına staking, kredi ve dönüştürme bildirimleri düşüyor. "Diğer"de "Binance Lists X" biçimindeki spot listelemeler kaçıyor. Sahip, LLM spec'i bu tabloya dayanmadan önce her türün yalnız o türden duyuruları ölçmesini istiyor. Ölçüm kuralı, fiyat verisi, tür listesi ve yönler değişmez; kurallar fark değerlerine bakılarak ayarlanmaz.

## Changed behavior
- [ ] CB-1 — **Vadeli / marjin listeleme (S1).** Bir başlık bu türü yalnız adı geçen bir ya da daha çok coin için yeni bir vadeli kontratın ya da marjin işleminin açıldığını duyuruyorsa alır (ör. "Binance Futures Will Launch USDⓈ-M MBL Perpetual Contract With Up to 50x Leverage", "Binance Adds ANT, CLV, MDT, MIR, NEAR & WAXP on Cross Margin and ALCX, BICO & ELF on Isolated Margin", "Margin Trading for SNX & REEF Enabled on Binance"). Başlığında futures / perpetual / margin geçen öteki duyurular — kampanya, bonus, yarışma, ödül, borçlanma limiti, faiz, ücret, teminat oranı, sistem/işlev, copy trading, coin adı taşımayan genel duyurular (ör. "Binance Launches Margin Trading Service", "Trade ONT to Win $50,000 in ONT Tokens & $15,000 in Binance Futures Vouchers!", "Binance to Fully Resume Market Order Function for All Spot and Margin Trading Pairs", "Binance Futures Launches 200,000 USDT Welcome Bonus", "Binance Margin Will Update the Collateral Ratio of Multiple Cross Margin Assets (2025-07-18)") — sonraki kurallara geçer; hiçbiri uymazsa "diğer" olur. Sınır durumları: coin adı taşıyan yeni teslimatlı kontratlar ("Binance Futures Will List BTC, ETH, ADA & LINK Coin-Margined Quarterly 0326 Futures Contracts") ve yeni bir coin'in marjin dahil birkaç ürüne eklenmesi ("Binance Will Add Kaia (KAIA) on Earn, Buy Crypto, Convert, and Margin") bu türü alır; var olan bir kontratta işlemin yeniden başlaması ("Binance Futures to Resume Trading on USDT-Margined MINA Perpetual Contract") ve "Binance Futures Copy Trading Adds New USDⓈ-M Contract (2024-08-06)" almaz.
- [ ] CB-2 — **Listeden çıkarma (S2).** Bu tür yalnız token'ların spot işlemden çıkarılmasını duyuran başlıkları alır (ör. "Binance Will Delist BEAM on 2023-01-26", "Binance Will Delist DEGO, DENT, TRU on 2026-04-28"). Staking, kredi (Flexible Rate / VIP Loan), teminat ve listeden çıkarılmış token bakiyelerinin dönüştürülmesi ya da çekimi bildirimleri (ör. "Binance Staking to Delist EZ, TRU, VITE, ANC & MIR", "Binance Flexible Loan Has Delisted PEPE as a Borrowable Asset", "Binance VIP Loan Will Delist TUSD and ALCX from Eligible Collateral Asset List - 2026-03-30", "Notice on Converting Delisted Tokens Balances to BUSD (2021-07-02)", "Notice on the Withdrawals of Delisted Tokens & Conversion of Selected Tokens to USDT (2024-04-01)") bu türü almaz; sonraki kurallara geçer, hiçbiri uymazsa "diğer" olur.
- [ ] CB-3 — **Spot listeleme (S3, S4).** "Binance Lists X" biçimindeki başlıklar (ör. "Binance Lists LINK", "Binance Lists SNGLS") bugünkü "Binance Will List …" başlıkları gibi spot listeleme türünü ve coin'i alır. Zaten listelenmiş bir coin'e yeni işlem çifti ekleyen başlıklar (ör. "Binance Adds NEO/ETH Trading Pair", "Binance Will Add MCO/BTC Trading Pair On August 24", "Binance Adds XLM/BUSD and ADA/BUSD Trading Pairs", "Notice on New Trading Pairs & Trading Bots Services on Binance Spot - 2024-12-19") spot listeleme olmaz, "diğer"de kalır.
- [ ] CB-4 — **Kural seti parmak izi değişir.** Yeni kurallar yeni bir kural seti parmak izi üretir; tür listesi, sıraları ve beklenen yönler 0048'deki gibidir.
- [ ] CB-5 — **Tek yeniden ölçüm ve kaydı (S5, S6).** Kural değişikliği commit'lendikten sonra `events measure` aynı fiyat verisi, aynı kaynak kayıtlar, aynı model kesim anı (2026-07-01) ve aynı maliyetlerle bir kez koşar. Planın `## Build evidence` bölümü 0049 kaydının bütün kalemlerini yeni koşu için taşır (aynı kaynaklardan, türetilmiş değerler işaretli) ve ek olarak her türün duyuru sayısını eski kural setiyle ve yeni kural setiyle yan yana verir. Eski sayılar 0049 kaydında yoktur; eski rapordan (`E:/CrytoBot/data/events-report.txt`) alınır ve o dosyanın sha256'sı 0049 kaydındaki rapor parmak iziyle eşleşmelidir. Yeni koşu, ayarları kopyalanmış ayrı bir klasörden (`E:/CrytoBot/events-run-0050`) koşar ve kütüphaneyle raporu yeni dosyalara yazar (`E:/CrytoBot/data/events-library-0050.jsonl`, `E:/CrytoBot/data/events-report-0050.txt`); fiyat deposu ve arşiv deposu aynıdır. Kayıt betimleyicidir ve hüküm, eşik ya da öneri içermez (0049 CB-3 ile aynı not). Kurallar ölçüm çıktısına bakılarak bu spec'te değiştirilmez: yeni koşunun kaynak okuma anı kural commit'inden sonradır ve dalda o andan sonra kural dosyasına commit yoktur.
- [ ] CB-6 — **Etiket denetimi (S7).** Yeni koşunun raporundaki etiket denetimi bölümü (tür başına en çok 20 başlık ve "diğer"in en sık 20 kalıbı) SHIP'te sahibin gözüyle denetlenir; sahibin tür dışı bulduğu başlık SHIP kapısında bulgu olur. `specs/backlog.md`'den B-93 silinir.

## Preserved behavior
- [ ] PB-1 — Öteki türlerin (işlem çifti kaldırma, izleme etiketi, launchpool / launchpad / HODLer, askıya alma ve bakım, ağ yükseltmesi) kuralları değişmez; 0048'in bugünkü etiket ve coin çıkarma testleri değiştirilmeden geçer.
- [ ] PB-2 — Ölçüm kuralı, fiyat indirme ve rapor biçimi değişmez: `events download` yeniden koşmaz; `E:/CrytoBot/data/events-prices.db` ve `E:/CrytoBot/data/crytobot-news-archive.db` sha256'ları yeni koşudan önce ve sonra aynıdır.
- [ ] PB-3 — 0049'un kaydı (`specs/plans/0049-plan.md`, `specs/done/0049-…`) değişmez; eski kütüphane ve rapor dosyaları üzerine yazılmadan önce sha256'ları 0049 kaydıyla eşleştirilir ve yeni koşu ayrı yollara yazar.
- [ ] PB-4 — `scripts/check` yeşil.

## Out of scope
- B-92: spot listeleme ölçüm kuralı (giriş anı, yeni coin taban oranı); bu spec'te spot listelemenin ölçülen sayısı büyük olasılıkla 0 kalır ve kayıtta öyle görünür.
- Yeni olay türü (ör. "işlem çifti ekleme"); kaldıraçlı token, launchpool ve öteki türlerin kuralları.
- Ölçüm sonucuna göre kural, eşik, model kesim anı ya da maliyet ayarı; ikinci bir yeniden ölçüm.
- Fiyat verisini yeniden indirmek; arşivi yeniden toplamak.
- Sensitive area: yok — para, emir, risk, kimlik bilgisi ya da live moda dokunmaz.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-*
- [ ] Spec moved to `specs/done/` (immutable there)
