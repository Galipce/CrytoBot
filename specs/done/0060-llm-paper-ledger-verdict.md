# Spec 0060 — LLM paper defteri, karşılaştırma ve ön kayıtlı hüküm

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0060-plan.md`
- Self-critique: done
- Source: ADR 0005 kural 4–7 (liste ADR 0006); spec 0059'un karar kaydı; sahip isteği 2026-11-20

## Intent
Sahip, Claude'un saatlik `al` kararlarının gerçekten kâr getirip getirmediğini para riski olmadan görmek istiyor
(ADR 0005). Bu spec, 0059'un karar kaydındaki geçerli `al` kararlarını giriş bölgesi, stop, hedef ve geçerlilikle ayrı
bir paper defterinde uygular; her işlem bugünkü risk kurallarından geçer. Sonuç aynı dönemde eşlenik rastgele girişle
karşılaştırılır, ADR 0004'ün S0 koşusu bilgi olarak yanına konur. Hüküm, ölçüm başlamadan bu spec'e yazılan sayılarla
verilir ve sonradan gevşetilmez. Başarı: 90 günün sonunda tekrarlanabilir bir rapor ve tek anlamlı bir hüküm. Bilerek
yapılmayan: live, Claude'un çıkış kararı, liste ya da sıklık değişikliği; olumlu hüküm bile live'a geçirmez (ayrı ADR,
BR-10, ADR 0003).

Clarify kararları (Galip Badem, 2026-11-20, "evet" — bütün öneriler kabul):
- **C-1:** Defter rapor anında, kayıtlı kararların sonradan indirilen 1h mumlarla oynatılmasıdır (belirlenimli,
  tekrarlanabilir; ayrı canlı süreç yok). Risk kuralları aynen uygulanır.
- **C-2:** Giriş: kararın geçerlilik süresi içinde bir 1h mumun aralığı giriş bölgesine değerse, bölgenin üst ucundan
  dolar (kötümser). Çıkış yalnız stop ya da hedefle; aynı mumda ikisine de değerse stop sayılır. Maliyet ADR 0004 ile
  aynı: komisyon %0,1, kayma %0,1 (her yönde).
- **C-3:** Üst süre: dolumdan 7 gün sonra stop ya da hedef görülmediyse o mumun kapanışından çıkılır ("süre").
- **C-4:** Kasa 100 USDT ve bugünkü risk ayarları S0 ile aynı (işlem başına risk, günlük zarar %3, drawdown %15, en çok 5
  açık pozisyon, maliyet katı 2); pozisyon büyüklüğü stop mesafesinden.
- **C-5:** Eşlenik rastgele: LLM'in her işlemi için aynı turda listeden düzgün rastgele bir coin; giriş o turun son
  kapanmış 1h mumunun kapanışından; stop ve hedef LLM işleminin yüzde mesafeleriyle; aynı risk kuralları; sabit tohumla
  1000 tekrar; LLM net kârının bu dağılımdaki yüzdeliği.
- **C-6:** Ölçüm bu spec'in onay anından sonraki ilk 1h sınırında başlar; öncesindeki kararlar ölçüme girmez. Süre 90
  gün. Model ya da istem parmak izi değişirse ölçüm o turdan yeniden başlar (0053 deseni).
- **C-7:** Olumlu hüküm için hepsi: en az 30 kapanmış işlem; maliyetlerden sonra net kâr > 0; kâr faktörü ≥ 1,2; en büyük
  drawdown ≤ %15; LLM net kârı eşlenik rastgelenin 95. yüzdeliğinin üstünde. 30 işlem dolmazsa "yetersiz örnek". S0
  karşılaştırması bilgi, hükme girmez.
- **C-6 kesin an (G-1):** Spec onayı 2026-11-20T02:19:37Z (Galip Badem, "onaylıyorum"); ölçüm başlangıcı
  **2026-11-20T03:00:00Z** (tur anı bu andan küçük kararlar girmez); süre 90 gün: bitiş **2027-02-18T03:00:00Z**.
- **C-8:** Kararsız turların `bekle` satırları ölçüme girmez; Claude'un kendi `bekle`si (`action='bekle'`) yalnız oran
  olarak raporlanır.

Self-critique kararları (Galip Badem, 2026-11-20, "onaylıyorum" — bütün öneriler kabul):
- **G-2:** Risk denetimi dolum anında, kasanın ve açık pozisyonların o anki durumuyla; maliyet katı (BR-8) giriş
  bölgesinin üst ucu, stop ve hedefle hesaplanır.
- **G-3:** Aynı coinde açık pozisyon ya da dolmamış karar varken gelen yeni `al` atlanır, "aynı coinde açık" sayılır.
- **G-4:** En çok açık pozisyon sınırına (BR-7) yalnız dolan pozisyonlar sayılır.
- **G-5:** Risk modülünün reddettiği LLM kararına rastgele ikiz kurulmaz; her tekrarın kendi 100 USDT kasası vardır;
  ikiz giriş bölgesine bakmadan turun son kapanmış 1h mumunun kapanışından girer; rastgele coin aynı coin olabilir.
- **G-6:** Ölçüm sonunda açık kalan pozisyon son mumun kapanışından "ölçüm sonu" türüyle kapanır ve kapanmış işlem
  sayılır; hüküm bitiş anındadır. Bitişten sonraki kararlar ölçüme girmez.
- **G-7:** Günlük zarar sınırının (BR-5) günü UTC günüdür.
- **G-8:** İndirme borsa kurallarını (en küçük tutar, miktar adımı) da alır; kurala göre en küçük tutarın altında kalan
  pozisyon "en küçük tutar" adıyla reddedilir.
- **G-9:** S0 karşılaştırmasına S0 paper deposunda girişi ölçüm penceresine düşen işlemler girer.

## Requirements
1. Ayar ayrı dosyadadır: karar kaydının, S0 paper deposunun yolu ve çıktı yolları (fiyat verisi, rapor, işlem dosyası);
   ölçüm başlangıcı, süre, tohum ve hüküm eşikleri ayardan değil bu spec'ten gelir (ayarlanamaz). Çıktı yolları hiçbir
   girdi kaydı, kayıt dosyası, bot ya da paper deposu ve ayar dosyası olamaz, birbirlerinden de farklıdır.
2. İndirme komutu, ölçüm penceresindeki kararların coinleri için gereken 1h mumları (kararın turundan çıkışa ya da
   üst süreye kadar) herkese açık uçlardan anahtarsız indirir; yeniden çalıştırılınca yalnız eksikleri ister.
3. Rapor komutu ağa ve LLM'e çıkmaz, kilit almaz; girdileri yalnız okur. Her geçerli `al` kararı için C-2 ve C-3'e göre
   dolum ve çıkış bulur; risk kurallarını (BR-3…BR-8, BR-11) kararların zaman sırasıyla, kasanın o anki durumuyla
   uygular. Reddedilen karar reddin adıyla, dolmayan karar "dolmadı" olarak sayılır; mum verisi eksik olan karar
   "ölçülemedi" (nedenli) olur ve hükme girmez.
4. Drawdown sınırı (BR-6) aşılırsa defter o andan sonra yeni işlem açmaz; açık işlemler kurallarına göre kapanır. Bu
   durum raporda an ve kasayla yazılır.
5. Eşlenik rastgele (C-5) LLM'in dolan her işlemi için kurulur ve aynı kurallarla oynatılır; aynı girdilerle iki rapor
   birebir aynı sayıları verir.
6. Rapor: ölçüm penceresi ve parmak izi dönemleri; tur, çağrı, şema dışı, tutarsız, `al`, Claude'un `bekle` sayıları
   ve oranları; işlemler (dolan, dolmadı, reddedildi — nedenle, ölçülemedi), kapanış türleri (hedef, stop, süre);
   maliyetlerden sonra net kâr, kâr faktörü, kazanma oranı, en büyük drawdown, ortalama süre; coin başına özet; eşlenik
   rastgelenin dağılımı (5., 50., 95. yüzdelik) ve LLM'in yüzdeliği; S0'ın aynı dönemdeki sonucu (bilgi). İşlem dosyası
   her işlemi (karar anı, coin, seviyeler, dolum, çıkış, sonuç) satır satır taşır. İkisi de her raporda baştan, atomik
   yazılır.
7. Hüküm (C-7) yalnız ölçüm süresi dolduktan sonra verilir; öncesinde "ölçüm sürüyor" yazılır, sayılar bilgi
   amaçlıdır. Hüküm `olumlu`, `olumsuz` ya da `yetersiz örnek`tir; olumsuzun hangi eşik(ler)den olduğu adıyla yazılır.
   Şema dışı ve tutarsız kararlar karar istenen coinlerin %20'sini aşarsa "karar kalitesi düşük" yazılır ve hüküm
   olumlu olamaz (ADR 0005 revisit trigger).
8. Hüküm bilgi verir: hiçbir emir, mod, liste ya da ayar değişmez; bot, S0 koşusu ve karar turu etkilenmez.

## User experience
none — no user interface (komut satırı; rapor ve işlem dosyası metindir, satır biçimleri kriterlerde).

## Constraints & out of scope
- ADR 0005 kural 4–7, ADR 0006 listesi; ADR 0003 live için aynen; ADR 0004 koşusu değişmez.
- Kapsam dışı: canlı (sürekli) LLM paper süreci; live; Claude'un çıkış kararı; 1h altı mumla dolum; liste, sıklık, model
  ya da istem değişikliği (yeni ön kayıt); hükmün otomatik bir aksiyonu.
- Sensitive area: risk (BR-3…BR-8 ve BR-11'in kararlara uygulanması) — domain.md.
- Split: önerilmedi (tek yetenek: ölçüm; 10 kriter).

## Acceptance criteria
- [x] AC-1 — Ayar: eksik ya da geçersiz alan, çakışan ya da aynı çıktı yolları, okunamayan karar kaydı her iki komutta
  ağa ve dosyaya dokunmadan alan adıyla reddedilir; ölçüm başlangıcı, süre, tohum ve eşikler ayarda verilirse ret.
- [x] AC-2 — İndirme: ölçüm penceresindeki `al` kararlarının coinleri için gereken 1h mumlar indirilir; ikinci çalıştırma
  yalnız eksikleri ister; ağ hatası adıyla raporlanır, önceki veri bozulmaz.
- [x] AC-3 — Dolum: geçerlilik süresi içinde giriş bölgesine değen ilk mumda bölgenin üst ucundan dolar; değmezse
  "dolmadı"; geçerlilik sınırındaki mum (son dahil, sonrası hariç) doğru sayılır.
- [x] AC-4 — Çıkış ve maliyet: hedef, stop ve aynı mumda ikisi (stop sayılır), dolumdan 7 gün sonra "süre" kapanışı,
  bitişte açık pozisyon "ölçüm sonu" kapanışı; komisyon ve kayma her yönde uygulanır; net kâr bunlardan sonradır.
- [x] AC-5 — Risk: işlem başına risk, en çok açık pozisyon (yalnız dolanlar), günlük zarar (UTC günü), maliyet katı,
  en küçük tutar ve drawdown kuralları dolum anında, zaman sırasıyla uygulanır; aynı coinde açık iken gelen `al`
  atlanır; her ret adıyla sayılır; drawdown aşılınca yeni işlem açılmaz ve an raporda yazılır.
- [x] AC-6 — Pencere: 2026-11-20T03:00:00Z'den önceki ve 2027-02-18T03:00:00Z'den sonraki kararlar ve kararsız turların `bekle` satırları ölçüme girmez; model
  ya da istem parmak izi değişince ölçüm o turdan yeniden başlar ve rapor dönemleri ayrı gösterir.
- [x] AC-7 — Rastgele: eşlenik rastgele (G-5) sabit tohumla 1000 tekrar, her tekrar kendi kasasıyla; aynı girdilerle iki rapor birebir aynı; LLM'in
  yüzdeliği ve 5./50./95. yüzdelikler raporda.
- [x] AC-8 — Rapor ve işlem dosyası: R-6'daki bütün alanlar; S0 deposu yoksa ya da okunamıyorsa "S0 yok" yazılır ve
  rapor yine üretilir; eksik mumlu karar "ölçülemedi" olarak nedeniyle sayılır.
- [x] AC-9 — Hüküm: süre dolmadan "ölçüm sürüyor"; dolunca 30 işlemin altında "yetersiz örnek"; her eşik ayrı ayrı
  bozulduğunda `olumsuz` ve bozan eşiğin adı; hepsi tutunca `olumlu`; şema dışı + tutarsız > %20 iken olumlu olmaz.
- [x] AC-10 — Yalıtım: rapor ağa ve LLM'e çıkmaz, kilit almaz (karar turu ve bot çalışırken de); girdiler raporlardan
  sonra bayt bayt aynı; bot ve S0 deposuna yazılmaz; rapor ve işlem dosyası atomik yazılır.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed (`docs/commands.md`, `docs/architecture.md`, örnek ayar)
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 (plan A-8: dolum mumunda hedef kuralı sıkılaştı; A-9: rapor süresi hedefi) |
| Fix rounds | 3 (review turu 1 ve 2; VERIFY test turu) |
| Review findings: real / noise / deferred | 26 / 8 / 1 (B-105) |
| Regressions introduced | 0 |
| Bugs escaped to production | 0 (ship anında) |

## Handoff
Shipped — Galip Badem, 2026-11-20. Uygulanışta iki plan değişikliği: A-8 (C-2'yi sıkılaştırır: dolum mumunda
hedef yalnız dolum açılışta olduysa sayılır) ve A-9 (rapor süresi < 3 dk; hızlandırma B-105). Ölçüm
2026-11-20T03:00Z → 2027-02-18T03:00Z; karar turunun (`decide`) zamanlanmış görevi sahipte.
