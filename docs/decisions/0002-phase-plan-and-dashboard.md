# ADR 0002 — Faz planı ve salt okunur pano

- Status: Accepted
- Date: 2026-11-06

## Context
Spec 0001–0020 sonunda risk, paper execution, defter, kalıcılık, indikatörler, teknik öneri, gerçek piyasa okuması ve
tek paper turu hazırdır; ama bot kendi başına çalışmaz. `news`, `research`, `llm`, `backtest`, `control` ve `reporting`
yalnız iskelettir. "Ürün ne zaman tam olur?" sorusunun cevabı yoktu: hangi spec'in neye hizmet ettiği ve sıranın
neden böyle olduğu yazılı değildi. Kısıtlar:
- BR-10: strateji paper'a ancak komisyon ve slippage dahil out-of-sample backtest sonucuyla geçer; aşama geçişi metrik
  eşiği ve insan onayı ister.
- Live, anahtarlar, mod anahtarı ve Telegram yetkilendirmesi hassas alandır (`docs/domain.md`).
- `docs/architecture.md` web dashboard'u "kapsam dışı (sonraki feature)" sayıyordu, zamanı belirsizdi.
- Tek kişilik proje: her faz tek sahibin gözetimiyle ilerler, spec'ler sırayla gelir.

## Decision
Ürün üç fazda tamamlanır. **Faz 1:** bot gerçek veriyle, gözetimsiz paper modda çalışır: giriş noktası ve döngü,
config ve CLI (başlat, durdur, kill switch, durum), yalnız gönderen Telegram bildirimi, günlük rapor ve metrikler,
out-of-sample backtest. Live açılmaz, API anahtarı kullanılmaz. **Faz 2:** önce localhost'ta, salt okunur bir pano;
ardından küçük sermayeyle live (live adaptörü, anahtar yönetimi, TOTP onaylı mod geçişi, bakiye mutabakatı, borsada
stop emri, Telegram komutları). **Faz 3:** `llm`, `news`, `research` ve sinyallerin `strategy`'de birleşmesi.
Pano hiçbir kontrol komutu taşımaz; kontrol CLI ve Telegram'da kalır.

## Consequences
- Faz 1'in bitişi tek cümleyle ölçülür: bot tek komutla başlar, turları kendi atar, yeniden başlamada durumunu korur,
  durdurulabilir, sorunda haber verir. Tahmin 6–8 spec, 1–2 hafta; tahmin, ölçüm değil. Bedeli: bu tanıma girmeyen her istek
  (ekran, live, LLM) Faz 1 bitene kadar bekler ya da bu ADR'ı yeniden açar.
- Backtest Faz 1'de olduğu için paper koşusu BR-10'un backtest şartını karşılar ve sonuçları strateji kanıtı sayılır;
  metrik eşiği ve insan onayı aşama geçişinde ayrıca aranır. Bedeli: botun ilk gözetimsiz koşusu 2 spec kadar gecikir.
- Pano Faz 1'i uzatmaz ve live kararından önce hazır olur: paper sonuçları (kâr/zarar, drawdown, işlemler, ret
  nedenleri) live geçiş kararı için okunur hale gelir. Bedeli: Faz 1 boyunca gözlem yalnız CLI, Telegram ve rapordan
  olur; live 2–3 spec daha geç başlar.
- Salt okunur ve localhost olduğu için pano kontrol yüzeyi (oturum, CSRF, komut) açmaz, emir ya da limit değiştiremez.
  Bedeli: kill switch ya da limit için ekrandan değil CLI veya Telegram'dan işlem yapılır; pano yine de bir okuma yüzeyi
  açar: yerel süreçler ve tarayıcı üzerinden DNS rebinding kasa ve işlem verisini okuyabilir. Bu yüzden pano spec'i
  şunları şart koşar: yalnız 127.0.0.1'e bağlanma, Host başlığı denetimi; `docs/architecture.md`'ye modül satırı ve
  yasak bağımlılık kuralı (pano `control` ve `execution`'ı import etmez).
- LLM sinyalleri en sona kalır: teknik strateji onlarsız çalışır, LLM harcaması ve güvenilmeyen girdi riski live
  oturmadan eklenmez. Bedeli: botun ilk live dönemi yalnız teknik sinyalle işlem yapar.
- B-29, B-42, B-45, B-48, B-50 Faz 1 spec'lerine, B-51 Faz 2'nin stop emri spec'ine bağlanır: açık kayıtların hangi
  işte kapanacağı bellidir. Bedeli: B-51 paper boyunca açık kalır. Risk kapıları ve boyutlama işlem riskini stop
  fiyatında, satış slippage'ı ve boşluklu düşüş olmadan hesaplar; gerçekleşen zarar BR-4'teki sınırı aşabilir
  (backlog örneğinde kasanın ~%0,004'ü kadar, boşluklu düşüşte sınırsız). Paper'ın gerçekleşen sonuçları bundan
  etkilenmez: kapanış güncel fiyat ve slippage'la dolar.

## Alternatives considered
- **Backtest'i Faz 1'den çıkarmak:** bot birkaç gün önce gözetimsiz çalışırdı, ama paper'a BR-10'u çiğneyerek geçilirdi
  ve o dönemin sonuçları strateji kanıtı sayılamazdı; kural için bir istisna yazmak gerekirdi.
- **Ekranları Faz 1'de yapmak:** gözlem daha rahat olurdu, ama Faz 1'in amacı (gözetimsiz koşu) ekrana ihtiyaç
  duymuyor; 2–3 spec, botun çalışmasına katkısız olarak öne çıkardı.
- **Ekranları live'dan sonraya bırakmak:** live geçiş kararı, panonun en çok işe yarayacağı an, Telegram mesajlarıyla
  verilirdi.
- **Kontrol komutlu pano:** tek yerden yönetim kolaylığı getirirdi, ama hassas alanda yeni bir yetkilendirme yüzeyi
  açardı; CLI ve TOTP onaylı Telegram aynı işi zaten görüyor.
- **LLM sinyallerini live'dan önce eklemek:** strateji daha zengin girerdi, ama live'a iki yeni risk (harcama,
  güvenilmeyen girdi) aynı anda girerdi ve paper sonuçları hangi sinyalin işe yaradığını ayıramazdı.

## Revisit triggers
- Faz 1, 8 spec'i ya da 2 haftayı belirgin biçimde aşarsa: kapsam yeniden kesilir.
- Out-of-sample backtest stratejinin maliyet sonrası kârsız olduğunu gösterirse: Faz 2'den önce strateji işi gelir,
  live ertelenir.
- Paper gözlemi CLI, Telegram ve raporla yetersiz kalırsa (karar için veri dışa aktarılıp elle inceleniyorsa): pano
  Faz 1'e çekilir.
- Panonun localhost dışından açılması ya da ekrandan kontrol istenirse: yeni ADR, yetkilendirme kararıyla.
- Teknik sinyal tek başına paper'da yetersiz kalırsa: Faz 3'ün bir kısmı live'dan önceye alınabilir, ayrı karar olarak.
