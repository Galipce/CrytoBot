# Spec 0022 — Giriş noktası ve paper döngüsü

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0022-plan.md`
- Self-critique: done

## Intent
Sistemin sahibi, botun tek komutla paper modda başlamasını ve gerçek Binance spot verisiyle turlarını kendi atmasını istiyor. Bu iş, ADR 0002'deki Faz 1 bitiş tanımının ilk parçası: bot tek komutla başlar, turları kendi atar, yeniden başlamada durumunu korur, durdurulabilir. Başarı şöyle görünür: sahibi bir kez hazırlık adımıyla paper deposunu açar. Sonra başlatma komutunu verir. Bot her aralık sınırında taze piyasa okumasıyla mevcut paper turunu çalıştırır. Yeniden başladığında defteri, emirleri ve risk durumunu depodan aynen yükler, süren bir durdurma kaybolmaz. Ctrl+C ile durdurulduğunda turu yarıda bırakmaz. Backtest olmadığı için bu koşular BR-10 anlamında strateji kanıtı sayılmaz ve öyle işaretlenir. Bilerek yapılmayanlar: live mod, API anahtarı, CLI komut takımı (durum, kill switch, durdur), Telegram bildirimi, rapor ve backtest.

## Requirements
Terimler:
- **Hazırlık:** paper deposunu oluşturan ve açılış bakiyesini yazan, tek seferlik, açık adım.
- **Başlatma:** botu ayar dosyasıyla başlatıp döngüyü çalıştıran tek komut.
- **Ayar dosyası:** sabit konumda duran, insanın düzenlediği tek dosya. Turun ve okumanın bütün ayarlarını, tur aralığını, depo yolunu, kayıt dosyasının yerini ve hazırlık için açılış bakiyesini taşır.
- **Tur aralığı:** iki turun başlangıçları arasındaki süre.
- **Aralık sınırı:** UTC'de, tur aralığının tam katına denk gelen an (ör. 1 saatlik aralıkta her saat başı).
- **Deneme koşusu:** backtest sonucu ve insan onayı kaydı olmadan yapılan paper koşusu (BR-10).
- **Borsa yasağı:** borsanın HTTP 418 ile bildirdiği istek yasağı; varsa `Retry-After` ile bitiş anı.

Davranış:
- R-1: **Yalnız paper.** Hazırlık ve başlatma yalnız paper modda çalışır, mod seçeneği yoktur. API anahtarı okunmaz ve kullanılmaz; ortamda anahtar bulunsa bile davranış değişmez. Live modda oluşturulmuş bir depoyla başlatma reddedilir.
- R-2: **Ayarlar.** Ayarların hiçbirinin varsayılanı yoktur. Başlatma, borsaya ve depoya dokunmadan önce ayar dosyasını denetler. Dosya yoksa, okunamıyorsa ya da bir ayar eksik veya geçersizse bot başlamaz, ilk sorunlu ayarı adıyla söyler. Denetim, turun ve okumanın bugün reddettiği her ayarı kapsar (spec 0016 ayarları, spec 0017 okuma ayarları, çift listesi). Okuma bütçesi tur aralığından kısa olmak zorundadır. Ayarlar çalışırken yeniden okunmaz.
- R-3: **Hazırlık.** Hazırlık, depo yolunda depo yoksa paper deposunu oluşturur ve açılış bakiyesini ayardan yazar. Depo zaten varsa (okunabilir olsun ya da olmasın) hiçbir şey yazmadan reddeder. Açılış bakiyesi USDT cinsindendir ve defterin kabul ettiği basamak sınırları geçerlidir. Bakiye eksikse, pozitif değilse, sayı değilse ya da defter onu reddederse hazırlık hiçbir şey yazmadan reddeder. Hazırlık tur atmaz ve borsaya çıkmaz.
- R-4: **Depo yoksa başlamaz.** Başlatma depoyu asla kendiliğinden oluşturmaz. Depo yoksa, okunamıyorsa, meşgulse, modu uyuşmuyorsa ya da defter açılmamışsa bot başlamaz, nedeni adıyla söyler ve hazırlığı ancak depo yokken önerir.
- R-5: **Yeniden başlama.** Her başlatma durumu depodan yükler. Yeniden başlatma; defteri, açık pozisyonları, emirleri (durumu bilinmeyenler dahil) ve risk durumunu (süren drawdown durdurması, gün başı kasası, zirve dahil) önceki süreçte kaydedildiği gibi kullanır. Hiçbiri sıfırlanmaz.
- R-6: **Tek süreç.** Aynı depoyla çalışan bir bot varken ikinci başlatma reddedilir, nedeni adıyla söylenir ve çalışan bot etkilenmez.
- R-7: **Tur aralığı.** Tur aralığı, okumanın kabul ettiği mum aralıklarından biri olmak zorundadır, aksi hâlde R-2 uygular. Mum aralığından kısa olamaz.
- R-8: **Zamanlama.** İlk tur başlatmadan hemen sonra atılır. Sonraki turlar UTC'de bir sonraki aralık sınırında başlar. Turlar üst üste binmez. Bir tur bir ya da daha fazla sınırı aşarsa kaçan sınırlar telafi edilmez: bir sonraki gelecek sınır beklenir ve kaçan sınır sayısı kayda geçer. Her sınır için en fazla bir tur atılır. Sistem saati geri giderse geçilmiş bir sınır için ikinci tur atılmaz. Makine uykudan uyanınca kaçan sınırlar da telafi edilmeden sayılır.
- R-9: **Tur.** Her turda önce beyaz liste ve açık pozisyonların çiftleri için piyasa okunur. Ardından okuma, okumanın saatiyle ve aynı süreç belleğiyle tura verilir. Turun kendi davranışı (sıra, kapılar, kayıt, durum bildirimleri) değişmez.
- R-10: **Okuma reddi (B-50).** Okuma ayar, girdi ya da saat nedeniyle reddedilirse (adı konmuş her girdi sorunu, saat reddi dahil) o tur başlatılmaz: ne geçersiz zaman ne geçersiz veri sonucu üretilir. Ret nedeni adıyla kaydedilip bildirilir ve döngü durur; yeniden başlatmayı insan yapar.
- R-11: **Borsa yasağı (B-48).** Bir okuma borsa yasağıyla karşılaşırsa, yasak bilgisi sonraki okumalara taşınır. Bitiş anına kadar borsaya hiç istek atılmaz. `Retry-After` yoksa bir sonraki okuma en erken bir tur aralığı sonra yapılır. `Retry-After`'ın üst sınırı yoktur, saatler ya da günler sürse de olduğu gibi uygulanır. Yasak süresince turlar atılmaya devam eder ama piyasa verisi verilmez: veri eksik sayılır, alım durur, fiyatsız kapanış yapılmaz (BR-11). Yasağın başlangıcı ve bitiş anı bildirilir. Yasak bilgisi yalnız süreç boyunca tutulur.
- R-12: **Temiz durdurma.** Bot Ctrl+C ile durur (Windows'ta Ctrl+Break de; Unix'te SIGTERM de). Bot beklemedeyse hemen çıkar. Tur sürüyorsa tur biter, sonra çıkılır; bu arada yeni tur başlamaz. İkinci bir durdurma isteği anında çıkarır. Çıkışta durdurma nedeni ve son turun sonucu kayda geçer.
- R-13: **Durumlar ve çıktı.** Turun durum bildirimleri, her turun özeti (an, sonuç, kaçan sınır), başlatma ve durdurma olayları, ret ve yasak olayları hem konsola hem ayardaki kayıt dosyasına yazılır. Kayıt dosyası yalnız sona eklenir ve UTF-8'dir. Konsol bir karakteri basamıyorsa o karakter yer tutucuyla yazılır, bot çökmez. Süreç belleği kalıcı değildir: yeniden başlamada süren durumlar yeniden "başladı" olarak bildirilir.
- R-14: **Deneme koşusu (BR-10).** Bu spec'te her başlatma bir deneme koşusudur. Başlatma çıktısı, kayıt dosyasındaki başlatma kaydı ve her tur özeti "BR-10 öncesi deneme, strateji kanıtı değil" işaretini taşır. Kapı ("backtest sonucu ve insan onayı yoksa başlatma") backtest spec'ine aittir.
- R-15: **Beklenmeyen hata.** Döngünün kendisi (tur dışı adımlar: okuma, bekleme, kayıt yazımı) beklenmeyen bir hatayla karşılaşırsa çökmez. Hata tip adıyla kaydedilir, istisna metni sır taşıyabileceği için yazılmaz. Döngü sonraki sınırda sürer. Kayıt dosyası yazılamıyorsa konsola yazılır ve bot durur.

## User experience
none — no user interface. Kullanıcı yalnız konsol komutlarını ve konsol/kayıt çıktısını görür; çıktı biçimi plana aittir, metinleri Türkçedir.
- Flow: ayar dosyasını düzenle → hazırlık (bir kez) → başlatma → bot turları atar → Ctrl+C → çıkış.
- States: başlatma reddedildi (ayar, depo, mod, ikinci süreç), çalışıyor/beklemede, tur sürüyor, borsa yasağı, okuma reddi ile durdu, temiz durdu.
- Design reference: none — the flow above is the design.
- Accessibility: yalnız klavye; renk bilgi taşımaz.

## Constraints & out of scope
- Sensitive area: Paper ↔ live mod anahtarı; Kalıcı durum (`persistence`) — `docs/domain.md`. Mod hiçbir yoldan live olamaz (R-1). Depo yalnız hazırlıkla oluşur, başlatma onu asla oluşturmaz (R-3, R-4), böylece silinmiş bir depo drawdown durdurmasını sessizce sıfırlayamaz (BR-6).
- BR-10 yorumu (S1, Galip Badem, 2026-11-06): paper'da para riski yoktur. Döngü backtest'ten önce çalışır ama sonuçları strateji kanıtı sayılmaz (R-14). Başlatma kapısı backtest spec'ine kalır. ADR 0002'deki "ilk gözetimsiz koşu" (kanıt sayılan koşu) backtest'i bekler.
- Turun, okumanın, defterin, risk kurallarının ve kalıcı durum biçiminin davranışı değişmez. Shipped testlerin beklentileri değişmez.
- B-48 (borsa yasağının yeniden başlamada kaybolması): bilinen risktir. Yasak süresinde yeniden başlatılan bot tekrar istek atabilir ve Binance yasağı uzatabilir. Bilgiyi kalıcı yapmak depo biçimini değiştirmek demektir ve kapsam dışıdır.
- B-29: bot, bu geliştirme makinesinde çalışır (Windows 10 Pro, fişe takılı). Spec 0011 R-11'in 1 s sınırı değişmez ve kapısı CI koşusu olarak kalır. Bu makinede pille ölçülen 0,95–1,12 s değerleri bilinen yerel durumdur. En kısa tur aralığı dakikalar mertebesinde olduğu için sınır döngüye bol pay bırakır. Karar: Galip Badem, 2026-11-06 (S8).
- Out of scope: live mod, API anahtarı ve anahtar yönetimi; CLI komut takımı (durum, durdur, kill switch, limit değiştirme, BR-13); ayarları çalışırken değiştirme; Telegram ve başka dış bildirim (B-42, B-45 bildirim spec'inde); günlük rapor ve metrikler; backtest ve BR-10 kapısı; servis olarak kurulum ya da otomatik yeniden başlatma; kayıt dosyası döndürme; yasak bilgisinin kalıcı olması.
- Coverage: `app` için modül başına %90 branch eşiği sürer (`docs/testing.md`).
- Testler gerçek borsaya çıkmaz; gerçek borsa yalnız VERIFY'daki tek gözlemde kullanılır (AC-14).
- Boyut: iki yetenek, 14 kriter. Split: proposed 0022 hazırlık ve ayar dosyası; 0023 başlatma ve döngü; kept as one — Galip Badem, 2026-11-06, hazırlık tek başına kullanılabilir bir yetenek değil, ayar dosyası iki parçada ortak, bölmek ADR 0002'nin spec bütçesinden bir spec harcar.
- Backlog: B-48 ve B-50 bu spec'le kapanır. B-29 bu spec'te makine adlandırılarak karara bağlanır.

## Acceptance criteria
- [x] AC-1 — Mutlu yol (R-8, R-9, R-13): hazırlanmış depo ve sahte borsayla başlatma ilk turu hemen atar, sonraki turları aralık sınırlarında atar. Her tur o anın okumasını ve aynı süreç belleğini kullanır, tur özetleri konsola ve kayıt dosyasına yazılır.
- [x] AC-2 — Yalnız paper (R-1): ortamda anahtar varken bile hazırlık ve başlatma anahtar okumaz, sahte borsa emir ve hesap çağrısı kaydetmez. Live modlu depoyla başlatma adıyla reddedilir ve tur atılmaz.
- [x] AC-3 — Ayarlar (R-2, R-7): dosya yok, okunamıyor, her eksik ayar, her geçersiz ayar mum aralığından kısa ya da kabul edilmeyen tur aralığı ve tur aralığına eşit ya da ondan uzun okuma bütçesi için bot başlamaz, ilk sorunlu ayar adıyla söylenir, borsaya ve depoya dokunulmaz.
- [x] AC-4 — Hazırlık (R-3): depo yokken paper deposu oluşur, açılış bakiyesi ayardaki değerdir ve tur atılmaz. Depo varken (okunabilir ya da bozuk) hazırlık hiçbir şey yazmadan reddeder. Eksik, sıfır, negatif, sayı olmayan ve defterin basamak sınırını aşan açılış bakiyesi depo oluşturmadan reddedilir.
- [x] AC-5 — Depo yoksa başlamaz (R-4): depo yok, okunamıyor, meşgul ve defter açılmamış durumlarının her birinde başlatma adıyla reddeder ve depo oluşmaz. Hazırlık önerisi yalnız depo yokken çıkar.
- [x] AC-6 — Yeniden başlama (R-5): açık pozisyonu, durumu bilinmeyen emri ve süren drawdown durdurması olan bir koşu durdurulup yeniden başlatılınca hepsi aynen yüklenir. Durdurma sürer, alım olmaz, bilinmeyen emir sorgulanır.
- [x] AC-7 — Tek süreç (R-6): aynı depoyla çalışan bot varken ikinci başlatma adıyla reddedilir ve çalışan botun turları ve deposu etkilenmez.
- [x] AC-8 — Zamanlama sınırları (R-8): sınıra tam denk gelen başlatmada ilk tur hemen atılır ve aynı sınır için ikinci tur atılmaz. Bir sınırı aşan turdan sonra kaçan sınır telafi edilmez, kaçan sınır sayısı (1 ve 2 vakaları) kayda geçer, turlar üst üste binmez. Saat geri alınınca geçilmiş sınır için ikinci tur atılmaz. Uykudan uyanmayı taklit eden saat sıçramasında kaçan sınırlar telafi edilmeden sayılır.
- [x] AC-9 — Okuma reddi (R-10, B-50): reddedilen okumada tur başlatılmaz, ne geçersiz zaman ne geçersiz veri sonucu oluşur, depo değişmez. Ret nedeni adıyla kaydedilir ve döngü durur. Saat reddi (`CLOCK`) da aynı yoldan geçer.
- [x] AC-10 — Borsa yasağı (R-11, B-48): `Retry-After`'lı 418'den sonra bitiş anından önceki turlarda sahte borsaya istek gitmez. Bu turlarda alım olmaz ve fiyatsız kapanış yapılmaz. Bitiş anından sonraki ilk turda okuma yeniden yapılır. `Retry-After`'sız 418'de sonraki okuma bir tur aralığından önce yapılmaz. Günler süren bir `Retry-After` kırpılmadan uygulanır. Yasağın başlangıcı ve bitiş anı bildirilir.
- [x] AC-11 — Temiz durdurma (R-12): beklemedeyken gelen durdurma isteği hemen çıkarır. Tur sırasında gelen istek turun bitmesini bekler, yeni tur başlamaz, depo turun kaydettiği hâldedir. İkinci istek anında çıkarır. Durdurma nedeni ve son tur sonucu kayda geçer.
- [x] AC-12 — Deneme işareti (R-14): başlatma çıktısı, kayıt dosyasındaki başlatma kaydı ve her tur özeti "BR-10 öncesi deneme" işaretini taşır.
- [x] AC-13 — Beklenmeyen hata ve çıktı (R-13, R-15): döngü adımında bir hata atılınca bot çökmez, hata tip adıyla kaydedilir, istisna metni ve sır biçimli metin kayıtta yoktur, sonraki sınırda tur atılır. Kayıt dosyası yazılamıyorsa konsola yazılır ve bot durur. Türkçe karakter basamayan konsolda bot çökmez, kayıt dosyası UTF-8 tam metni taşır. Yeniden başlamada süren durum yeniden "başladı" olarak bildirilir.
- [x] AC-14 — Gerçek borsa (R-1, R-9): VERIFY'da, `check` dışında, bu makinede hazırlık ve başlatmayla Binance spot'a karşı anahtarsız en az iki tur atan, sonra Ctrl+C ile temiz duran tek bir gözlem kanıtla belgelenir.

## Definition of Done
- [x] Every acceptance criterion mapped to proof (test or reproducible observation)
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Docs / ADRs updated if behavior or architecture changed
- [x] Spec moved to `specs/done/` (it becomes immutable there)

## Scorecard (fill at ship — honest numbers make the process improvable)
| Metric | Value |
|---|---|
| Spec revisions | 0 |
| Fix rounds | 4 (review round 1, review round 2, VERIFY round 1, review round 3) |
| Review findings: real / noise / deferred | 10 / 4 / 2 (real: R1 L-1, L-2, I-1, L-3 (R-05 → VERIFY 1), R2 L-1, V-1, V-3, V-4, R3 L-2, I-2; noise: R1 I-2, V-5, R3 L-1, V-6; deferred: V-2 → B-52, R3 I-1 → B-53; investigate açık: I-1 R-03) |
| Regressions introduced | 0 bilinen (I-1, R-03: @9e1571a'daki adsız `test-unit` hatası açık; kanıt bu PR'ın full CI koşusu) |
| Bugs escaped to production | 0 (henüz üretim yok) |

DoD'nin `scripts/check` kutusu koşullu işaretlendi (`doctor`, `specs/done/`'da işaretsiz kriteri reddediyor); koşul bu PR'ın `check` ve `doctor` işleridir, yeşil olmadan merge yapılmaz (`docs/testing.md`, Two speeds, rule 10). Full kanıt: CI run 42198843822, `29660fa`, `CHECK GREEN (full, 7 steps, 478 s)`: 2857 passed + 28 full-only passed, 0 failed. AC-14 gözlemi (V-1): 2026-11-06, bu makinede, Binance spot'a anahtarsız 3 tur, gerçek Ctrl+C (`SIGINT`), çıkış kodu 0; çıktı bu PR'ın açıklamasında (Evidence policy 3).
