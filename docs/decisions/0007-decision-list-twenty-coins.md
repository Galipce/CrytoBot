# ADR 0007 — LLM karar modunun listesi 20 coin; ölçüm yeniden başlar

- Status: Accepted
- Date: 2026-11-20

## Context
ADR 0005 kural 1 (liste ADR 0006 ile TON yerine TRX) on coinlik bir listeyi ön kaydetti; spec 0060 ölçümü
2026-11-20T03:00Z'de başlattı. İlk turlarda (11:00–14:00Z) Claude on coinin hepsine `bekle` dedi: liste toplu bir
düşüşte (7 günde %-10…-20), `al` için dönüş teyidi yok. Spec 0060'ın olumlu hükmü en az 30 kapanmış işlem ister;
yalnız on, birlikte hareket eden coinle 90 günde bu sayıya ulaşmamak ("yetersiz örnek") hükmü en çok tehdit eden
risktir. Ölçüm başlayalı birkaç saat oldu ve hiçbir işlem yok: liste şimdi, sonuç görülmeden değiştirilebilir.

## Decision
ADR 0005 kural 1'in listesi 20 coindir (USDT spot): BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, TRX, BCH, LTC,
SUI, XLM, HBAR, DOT, SHIB, UNI, NEAR, APT. Saatte bir tur ve tek Claude çağrısı (kural 2) korunur. Ölçüm (spec 0060)
yeniden başlar: yeni liste ile çalışan karar turunun ilk 1h sınırı yeni başlangıçtır, süre yine 90 gündür; kesin an
değişikliğin spec'ine (0061) ship'te yazılır. Önceki on coinlik dönemin kayıtları ölçüme girmez. ADR 0005'in öteki
kuralları ve spec 0060'ın eşikleri değişmez.

## Consequences
- Kazanılan: daha çok ve daha az ilişkili fırsat (ayrı ekosistemler, ayrı haber olayları); "yetersiz örnek" riski
  azalır. Eklenen on coinin hepsi Binance'te 250 adet 1h mumla boşluksuz okunuyor (2026-11-20).
- Bedeli: istem iki katına yaklaşır (on coinde ≈43 KB); 64 KB sınırı coin başına özetin kısaltılmasıyla ya da sınırın
  yükseltilmesiyle çözülmelidir (0061). Tek çağrıda 20 coin kararın kalitesini düşürebilir; şema dışı ve tutarsız oranı
  (eşik %20) bunu ölçer. 100 USDT ve en çok 5 açık pozisyonla daha çok `al`, daha çok "açık pozisyon sınırı" reddi
  demektir; rapor bunu sayar. Ön kayıt ikinci kez değişti; değişiklik hiçbir işlem görülmeden yapıldı.

## Alternatives considered
- **On coinle devam:** ön kayıt korunur ama "yetersiz örnek" riski yüksek kalır; ölçüm başlayalı saatler olmuşken
  değiştirmenin bedeli en düşüktür.
- **15 coin:** istem sınıra yakın, fırsat artışı yarım; sahip 20'yi seçti.
- **Coin başına ayrı çağrı:** günde 480 çağrı, abonelik ve günlük sınırın üstünde (ADR 0005 alternatifleri).
- **ETC, ATOM, ICP, PEPE:** okunuyorlar; daha düşük öncelik ve listede zaten iki meme coin (DOGE, SHIB) var.

## Revisit triggers
- Şema dışı + tutarsız oranı %20'ye yaklaşırsa (tek çağrıda 20 coin fazla gelmiş olabilir).
- Bir coin Binance'te işlemden kalkarsa ya da sürekli "veri yok" olursa (yeni ön kayıt).
