# Spec 0052 — Gölge filtre: "bastırılırdı" kaydı

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0052-plan.md`
- Self-critique: done

## Intent
Sahip, LLM filtresinin işe yarayıp yaramadığını ölçmeden önce (ADR 0003, sıranın beşinci işi), filtre açık olsaydı
botun hangi teknik "al"larını bastıracağını parasız ve dürüst biçimde görmek istiyor. Bu spec'te paper bot her turunda,
o ana kadar üretilmiş olay skorlarını (spec 0051) yalnız okuyarak beyaz listedeki her coin için filtre durumunu —
bastırılırdı / bastırılmazdı / eksik bilgiyle bastırılmazdı / filtre yok (nedeniyle) — ve o coinde teknik "al" çıkıp
çıkmadığını ayrı bir kayda yazar. Başarı: kayıt botun hiçbir kararını değiştirmeden birikir, sonradan öğrenilen bilgi
kayda girmez ve 0053'ün ileriye dönük ölçümüne girdi olur. Bilerek yapılmayan: alım gerçekten bastırılmaz; LLM hiçbir
karara karışmaz; ölçüm ve hüküm verilmez (0053); live ve backtest değişmez; beyaz liste genişletilmez. Clarify
kararları S-1…S-7 Galip Badem, 2026-11-18 tarihinde kabul etti ("önerilerini kabul ediyorum"); öz eleştiri kararları
G-1…G-8 Galip Badem, 2026-11-18 tarihinde kabul etti ("kabul ediyorum").

Terimler:
- **Tur anı:** paper turunun başladığı an (botun o tur için kullandığı saat).
- **Olumsuz olay (0051'de sabit, gevşetilemez):** yönü olumsuz, şiddeti ≥ 2 olan, haberinin ilk görme anı tur anından
  en çok 24 saat önce (ya da eşit) olan ve coini beyaz listede olan olay skoru.
- **Bilinen skor:** "skorlandı" sonucunun skor anı tur anından önce ya da eşit olan olay skoru. Tur anından sonra
  üretilen skor o tur için hiç yokmuş sayılır (look-ahead yok).
- **Pencere:** ilk görme anı [tur anı − 24 saat, tur anı] aralığında olan haberler.
- **Filtre durumu:** bir tur ve bir coin için tek değer (R-3).
- **Teknik al:** paper turunda stratejinin o coin için ürettiği alım önerisi, risk onayından önceki haliyle (S-3).
- **Gölge kayıt:** bu spec'in yazdığı, yalnız eklenen kayıt; bot deposundan ayrıdır.

## Requirements
- R-1 — **Ne zaman, nerede (S-1, S-5).** Gölge kayıt yalnız paper modda ve yalnız ayarda açıkça istenmişse tutulur.
  Ayar yoksa paper bot bugünkü gibi çalışır ve hiçbir kayıt yazılmaz. Live ve backtest'te gölge kayıt yoktur; ayar
  varken de bu modlar bugünkü gibi çalışır. Paper bot ve skorlayıcı aynı makinede çalışır (0051 G-1).
- R-2 — **Satırlar (S-2).** Tamamlanan her paper turunda beyaz listedeki her coin için tam bir satır yazılır, teknik al
  çıksın çıkmasın. Satır şunları taşır: tur anı, çift, o turdaki beyaz liste, filtre durumu ve nedeni, eşleşen olumsuz
  olayların referansları (haber kimliği, şiddet), penceredeki eksik bilgi sayıları (R-4), teknik al (var / yok ve
  stratejinin nedeni / değerlendirilmedi ve nedeni, G-2) ve teknik al varsa risk sonucu (onay ya da ret nedeni, S-3).
  Turun kendisi reddedilir ya da tamamlanmazsa (ayar reddi, depo reddi, beklenmeyen hata) o tur için satır yazılmaz.
- R-3 — **Filtre durumu (S-4).** Sırayla:
  1. `filtre yok: <neden>` — skor kaydı yok ya da okunamıyor; skor kaydının başlangıç anı tur anından sonra; haber
     kaydı yok ya da okunamıyor; skorlayıcı durmuş (son tur anı tur anından 30 dakikadan eski ya da hiç yok, G-3).
  2. `bastırılırdı` — bilinen skorlar arasında o coin için en az bir olumsuz olay var. Coin eşleşmesi: olay skorunun
     coin sembolü çiftin taban varlığına (`BTC/USDT` → `BTC`) birebir eşittir (G-6).
  3. `bastırılmazdı — eksik bilgi` — olumsuz olay yok, ama pencerede tur anında henüz bilinen bir "skorlandı" sonucu
     olmayan haber var (R-4).
  4. `bastırılmazdı` — olumsuz olay yok ve penceredeki her haberin bilinen bir "skorlandı" sonucu var (ya da pencere
     boş).
  Eksik bilgi bastırma kararını değiştirmez: olumsuz olay varsa durum, eksik bilgi olsa da `bastırılırdı` olur;
  eksik sayılar yine yazılır.
- R-4 — **Eksik bilgi sayıları (G-4, G-5).** Penceredeki haberlerden tur anında bilinen "skorlandı" sonucu olmayanlar,
  türüne göre ayrı sayılır: bekleyen (sonucu yok), şema dışı, bayat. Satıra, skorlayıcının tur anındaki engeli de
  yazılır: kota beklemesi, günlük sınır dolu ya da yok. Bu bilgiler yalnız kayda geçer; filtre durumunu R-3'teki
  sıradan başka biçimde değiştirmez.
- R-5 — **Skorlayıcının canlılık izi (G-3).** 0051 skorlayıcısı her turun anını skor kaydına yazar; tur hiç çağrı
  yapmasa da (kota beklemesi, günlük sınır, bekleyen haber yok) yazar. Skorlayıcının tur aralığı ayarının üst sınırı
  15 dakika olur (varsayılan 5 dk ve alt sınır 1 dk değişmez); aralık bu sınırı aşarsa skorlayıcı başlamayı adıyla
  reddeder. 0051'in diğer bütün davranışı değişmez.
- R-6 — **Gölge mod: karar değişmez (ADR 0003 ilke 3 ve 5).** Gölge kaydın tutulması, tutulamaması, skor kaydının ya
  da haber kaydının durumu, paper turunun hiçbir kararını (alım, kapanış, risk onayı, durdurma, bildirim, tur sonucu)
  ve bot deposunu değiştirmez. Bot deposu ve paper kanıt deposu (BR-10, spec 0038) gölge kayıttan ve skorlardan hiçbir
  şey içermez. Skor kaydı ve haber kaydı yalnız okunur; skorlayıcı ve toplayıcı çalışırken okunabilir ve onları
  beklemez ya da durdurmaz.
- R-7 — **Kayıt hatası (G-1).** Gölge kayıt bir turda yazılamazsa tur sonucu değişmez; bot kayıt dosyasına hatanın adı
  tek satır yazılır; o turun satırları sonradan tamamlanmaz (boşluk olarak kalır). Sonraki tur yine yazmayı dener.
- R-8 — **Kayıt ve ayar (G-8).** Gölge kayıt yalnız eklenir; var olan satır değiştirilmez ya da silinmez. Ayar bot
  ayar dosyasında ayrı bir bölümdür: gölge kaydın yolu, skor kaydının yolu, haber kaydının yolu. Gölge kayıt yolu bot
  deposu, paper kanıt deposu, haber kaydı, skor kaydı, arşiv ya da herhangi bir kayıt dosyasıyla (çözülmüş mutlak
  yollarla) aynıysa, ya da skor ve haber kaydı yolları bot deposuyla aynıysa, bot başlamayı adıyla reddeder ve hiçbir
  yere yazmaz. Skor ya da haber kaydının bulunmaması başlamayı engellemez (R-3: `filtre yok`).
- R-9 — **Durum (S-7).** Ağa ve LLM'e çıkmayan, kilit almayan ve gölge kaydı yalnız okuyan bir durum çıktısı şunları
  gösterir: ilk ve son satırın tur anı, tur sayısı, filtre durumuna göre satır sayısı (çift başına), `filtre yok`
  nedenlerinin dağılımı, teknik al sayısı ve bunların filtre durumuna göre dağılımı, son kayıt hatasının adı. Kayıt
  yoksa "henüz gölge kayıt yok" der.

## User experience
none — no user interface (CLI). Akış: sahip bot ayarına gölge bölümünü yazar → `python -m crytobot start --trial` (ya
da kanıtlı paper başlatma) her turda satırları yazar → durum komutu sayıları gösterir. Durumlar: ayar yok (bugünkü
davranış, kayıt yok), ayar hatası (başlamaz, adıyla), kayıt sürüyor, skorlayıcı yok ya da durmuş (`filtre yok`
satırları), kayıt yok ("henüz gölge kayıt yok"). Komut ve bölüm adları plan aşamasında belirlenir; davranış değişmez.

## Constraints & out of scope
- **Sabit ölçüm şartları:** "olumsuz olay" tanımı ve 24 saatlik pencere 0051'de sabitlendi (ADR 0003 Consequences);
  bu spec onları değiştirmez ya da ayarlanabilir yapmaz.
- **Risk — beyaz liste darlığı (S-6):** bugünkü beyaz liste yalnız `BTC/USDT` ve `ETH/USDT`. Bu listeyle 0053'ün "90
  günde en az 30 olumsuz olay skoru (beyaz liste coinleri)" şartı dolmayabilir. Beyaz listeyi genişletmek ayrı bir
  insan kararıdır; bu spec'in kapsamı dışındadır. Her satır o turun beyaz listesini taşıdığı için değişiklik kayıtta
  görünür.
- **Çalışma koşulu (S-1):** kayıt, paper botun sahibin makinesinde skorlayıcıyla birlikte sürekli çalışmasını ister;
  aday olmadığı için bu bir `--trial` deneme koşusudur ve paper kanıtı sayılmaz (BR-10 değişmez). Makine uyurken tur
  olmaz; boşluklar kayıtta görünür.
- **Bağımlılık:** yeni Python bağımlılığı yok. Strateji, risk, execution ve portföy kodu değişmez.
- **Split:** yok — tek yetenek (gölge filtre kaydı). 0053 (ölçüm raporu ve hüküm) ayrı spec olarak kalır.
- OUT OF SCOPE: alımı gerçekten bastırmak (ayrı spec, ADR 0003 ölçüm hükmünden sonra); ölçüm, isabet ve hüküm (0053);
  live ve backtest'te kayıt; LLM'in "al" üretmesi ya da olumlu olayın alım açtırması; beyaz liste değişikliği;
  Telegram bildirimi ve pano; skorlayıcının prompt'u, doğrulaması ve sınırları (0051 R-5 dışında değişmez); B-92,
  B-94, B-95.
- Sensitive area: yok — emir, risk limitleri, defter, bot deposu (kalıcı durum), sırlar, mod anahtarı ve Telegram
  yetkisine dokunmaz. Paper turunun kararlarının değişmediği testle kanıtlanır (AC-7); güvenlik kuralları
  (`docs/security.md`: LLM çıktısı aksiyon tetiklemez) geçerlidir.

## Acceptance criteria
- [ ] AC-1 — Ayar varken tamamlanan bir paper turunda beyaz listedeki her coin için R-2'nin bütün alanlarıyla tam bir
  satır yazılır; teknik al çıkan coinde risk sonucu da yazılır; ayar yokken hiçbir satır yazılmaz ve tur bugünkü gibi
  geçer.
- [ ] AC-2 — Filtre durumu: olumsuz olay (yön olumsuz, şiddet 2 ve 3) → `bastırılırdı`; şiddet 1, yön olumlu ya da
  belirsiz, beyaz liste dışı coin, başka coin ya da ilk görme anı tur anından 24 saatten fazla önce olan haber →
  bastırmaz; tam 24 saat sınırı sayılır; coin eşleşmesi taban varlığa birebirdir.
- [ ] AC-3 — Look-ahead yok: skor anı tur anından sonra olan olumsuz olay o turda sayılmaz, eşit olan sayılır; ilk
  görme anı tur anından sonra olan haber pencereye girmez.
- [ ] AC-4 — Eksik bilgi: penceredeki bekleyen, şema dışı ve bayat haberler ayrı sayılır; olumsuz olay yokken durum
  `bastırılmazdı — eksik bilgi`, olumsuz olay varken `bastırılırdı` olur; kota beklemesi ve günlük sınır engeli
  satırda görünür.
- [ ] AC-5 — `filtre yok`: skor kaydı yok, okunamıyor, başlangıç anı tur anından sonra, haber kaydı yok ya da
  okunamıyor, skorlayıcının son tur anı 30 dakikadan eski ya da yok — her biri ayrı örnekte adıyla `filtre yok` olur;
  tam 30 dakika `filtre yok` değildir; bu durumlarda tur kararları değişmez.
- [ ] AC-6 — Canlılık izi: skorlayıcı çağrı yapmayan turda da tur anını yazar; tur aralığı 15 dakikayı aşan ayarla
  başlamayı adıyla reddeder, tam 15 dakika kabul edilir; 0051'in bugünkü testleri değiştirilmeden geçer.
- [ ] AC-7 — Gölge mod: aynı girdilerle gölge ayarlı ve ayarsız paper turları aynı alımları, kapanışları, risk
  kararlarını, bildirimleri, tur sonucunu ve bot deposu içeriğini üretir — `bastırılırdı` durumunda da; live ve
  backtest ayar varken değişmeden geçer (bugünkü testleri değiştirilmeden); skor ve haber kaydı turdan sonra
  değişmemiştir.
- [ ] AC-8 — Alım aşamasına gelmeyen turda (güvenli mod, bayat veri) satırlar yazılır ve teknik al "değerlendirilmedi"
  ile nedenini taşır; kill switch ve günlük zarar limitinde alım yolu durmaz (strateji koşar): satır stratejinin
  sonucunu, öneri varsa risk ret nedenini taşır; reddedilen ya da tamamlanmayan turda satır yazılmaz. (Plan 0052
  Risk 1, R-10 kararı (a): Galip Badem, 2026-11-18 — kodda kill switch bilgi amaçlıdır, günlük zarar limiti risk
  reddidir.)
- [ ] AC-9 — Kayıt hatası: gölge kayıt yazılamayınca tur sonucu ve bot deposu değişmez, bot kayıt dosyasına hatanın
  adı yazılır, sonraki tur yeniden dener; kayıt yalnız eklenir (var olan satır değişmez).
- [ ] AC-10 — Ayar ve durum: R-8'deki her yol çakışması adıyla reddeder ve hiçbir yere yazmaz; durum çıktısı ağa ve
  LLM'e çıkmadan, kilit almadan R-9'un bütün kalemlerini gösterir, kayıt yokken "henüz gölge kayıt yok" der.

## Definition of Done
- [ ] Every acceptance criterion mapped to proof (test or reproducible observation)
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Docs / ADRs updated if behavior or architecture changed (`docs/architecture.md`: `app` turunun skor ve haber
      kaydını yalnız okuması, gölge kayıt ve import kuralı; `crytobot.example.toml`, `crytobot-news.example.toml`
      tur aralığı üst sınırı)
- [ ] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | |
| Fix rounds | |
| Review findings: real / noise / deferred | |
| Regressions introduced | |
| Bugs escaped to production | |
