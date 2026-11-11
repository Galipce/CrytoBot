# Spec 0039 — Telegram güvenilirliği (mini)

- Status: Shipped
- Mode: strict
- Plan: `specs/plans/0039-plan.md`
- Self-critique: done
- Source: `specs/audit-0028-0033.md` A-7, A-8
- Design: —
- Supersedes: 0029/AC-7 (kısmen: "hatalı kimlikte Telegram devre dışı" ve "iletilemeyen mesajlar kuyrukta saklanıp sonraki turlarda denenir" kısımları); 0029 R-7 G-5 ("yalnız ilk çağrıda 401/400")

## Intent
Botun sahibi, Telegram yanlış ayarlandığında ya da ağ bozulduğunda bot döngüsünün — özellikle live modda — yavaşlamamasını ve kalıcı bir hatanın sonsuz yeniden deneme ve çift istek üretmemesini istiyor. Başarı: kalıcı hatalarda Telegram bir kez ve görünür biçimde kapanır; hiç iletilemeyecek mesaj kuyruğu işgal etmez; bir turda Telegram'a harcanan toplam süre ağ ne durumda olursa olsun 5 saniyeyi aşmaz. Clarify kararları (1–7) Galip Badem, 2026-11-11 tarihinde onayladı.

Terimler:
- **Kalıcı hata:** Telegram'ın 401 (geçersiz token), 403 (bot engellendi / sohbetten çıkarıldı) ya da açıklaması "chat not found" veya "chat_id is empty" olan 400 cevabı (G-4). Yeniden denemeyle düzelmez.
- **Geçici hata:** ağ hatası, zaman aşımı ve 5xx cevapları (500, 502, 503 …) (G-1). Telegram'ı kapatmaz.
- **Biçim hatası:** Telegram'ın mesaj biçimlendirmesini ayrıştıramadığını bildiren 400 cevabı.
- **Tur Telegram süresi:** Bir tur içinde Telegram gönderimleri için geçen toplam duvar saati süresi (ad çözümleme, bağlantı, yanıt bekleme dahil).

## Changed behavior
- [x] CB-1 — Kalıcı hata, çalışmanın hangi anında görülürse görülsün (yalnız ilk çağrıda değil), Telegram'ı o çalışma boyunca kapatır: aynı tur ve sonraki turlarda Telegram'a hiç istek gitmez, kuyruk boşaltılır. Süreç yeniden başlatılana kadar kendiliğinden açılmaz.
- [x] CB-2 — Telegram kapandığında konsola ve loga gerekçesinin adıyla (ör. `telegram devre dışı (chat bulunamadı)`, `(yetkisiz token)`, `(bot engellendi)`) **tek** bir satır yazılır; sonraki turlarda bu konuda tekrar satır yazılmaz. Satır token ya da başka sır içermez.
- [x] CB-3 — Biçim hatasında mesaj aynı turda düz metin olarak tek bir kez yeniden denenir. Düz metin denemesi başarılıysa mesaj iletilmiş sayılır; o da 400 dönerse mesaj atılır, kuyruğa girmez ve hata adı tur hatalarına/loga yazılır. Kalıcı hata ve biçim hatası dışındaki 400 cevapları da yeniden denenmez, kuyruğa girmez ve Telegram'ı kapatmaz (G-4). Bir mesaj için en fazla 2 istek gider. Atılan mesaj kritik bir bildirim (ör. drawdown) olsa da ayrı bir alarm üretilmez; hata adıyla log satırı yeterlidir (G-6).
- [x] CB-4 — Bir turun Telegram süresi en fazla 5 saniyedir; ad çözümlemenin takılması da dahil hiçbir ağ durumu bu sınırı aşamaz. Süre dolduğunda o turda kalan mesajlar denenmeden, üretildikleri sırayla kuyruğa girer; döngü turun geri kalanına geçer. Bu 5 saniyeyi turdaki bütün gönderimler paylaşır: turun başında kuyruğun iletilmesi, durum ve risk bildirimleri, dolum ve kapanış bildirimleri ve günlük özet (G-3). Süre bir isteğin ortasında dolarsa o istek zaman aşımı sayılır ve mesajı kuyruğa girer; Telegram mesajı almışsa doğabilecek mükerrer iletim kabul edilir (G-2).
- [x] CB-5 — Bir turda ilk geçici hata (ağ hatası, zaman aşımı ya da 5xx, G-1) görüldükten sonra o turda Telegram'a başka istek gitmez; o turda üretilen kalan mesajlar sırayla kuyruğa girer. Sonraki turda kuyruk yeniden denenir.
- [x] CB-6 — Telegram hız sınırı (429) bildirip bir bekleme süresi verdiğinde, bu süre — üst sınır uygulanmadan, verildiği kadar (G-5) — dolana kadar (turlar arasında da) Telegram'a istek gitmez; bu sürede üretilen mesajlar kuyruğa girer. Süre dolduktan sonraki ilk gönderim fırsatında kuyruk sırayla iletilir. 429 Telegram'ı kapatmaz. Bekleme süresi verilmemiş bir 429 bu turun geri kalanı için CB-5 gibi işlem görür.

## Preserved behavior
- [x] PB-1 — Token hiçbir hata yolunda (kalıcı hata, biçim hatası, zaman aşımı, 429, kapanma satırı) loga, konsola, tur hatalarına ya da Telegram mesajına açık yazılmaz (0029 AC-2).
- [x] PB-2 — Kuyruk en fazla 10 mesaj tutar; taşınca en eski mesaj atılır; ağ geri geldiğinde kuyruk üretim sırasıyla iletilir ve yeni mesaj kuyruktakilerin önüne geçmez (0029 AC-7).
- [x] PB-3 — Durum giriş/çıkış bildirimleri tekil kalır: süren durum için ara turlarda mükerrer bildirim gitmez (0029 AC-3); günlük özet aynı UTC günü için bir kez üretilir (0029 AC-6).
- [x] PB-4 — `enabled = false` ya da token/chat ID eksikken Telegram'a hiçbir istek gitmez ve bot hata vermeden başlar (0029 AC-1).
- [x] PB-5 — Telegram'ın hiçbir hatası (kalıcı, biçim, ağ, zaman aşımı, 429) turu düşürmez; alım-satım, defter kaydı ve tur sonucu Telegram yokmuş gibi aynı çıkar.
- [x] PB-6 — Normal durumda (Telegram 200 dönüyor) her mesaj tek istekle, HTML biçiminde iletilir.

## Out of scope
- Sensitive area: API anahtarları / sırlar (`docs/domain.md`) — hata yollarında token redaksiyonu (PB-1). Telegram komut yetkilendirmesine dokunulmaz.
- Telegram'dan komut almak, kuyruğu yeniden başlatmadan sonra korumak, panoda (0031) Telegram durumu göstergesi.
- Kapanmış Telegram'ı süreç yeniden başlatılmadan yeniden açmak.
- Mesaj içerikleri ve biçimleri (0029 formatlayıcıları) değişmez.
- A-9…A-12 (rapor kapısı), A-14 ve backlog B-57, B-58, B-59.
- Split: önerilmedi; 6 CB mini sınırını (3–5) aşıyor ama tek yetenek (Telegram gönderim güvenilirliği), bölmek aynı test düzenini iki kez kurar — Galip Badem, 2026-11-11 (G-7).
- Self-critique kararları G-1…G-7 (Galip Badem, 2026-11-11) Terimler, CB-3, CB-4, CB-5, CB-6 ve bu bölüme işlendi.

## Definition of Done
- [x] `scripts/check` green
- [x] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [x] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [x] Spec moved to `specs/done/` (immutable there)
