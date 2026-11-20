# ADR 0006 — LLM karar modunun listesi: TON yerine TRX

- Status: Accepted
- Date: 2026-11-20

## Context
ADR 0005 kural 1, LLM karar modunun coin listesini ön kayıtla sabitledi: BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX,
LINK, TON (USDT spot). Spec 0059'un VERIFY canlı turunda (2026-11-20) TON/USDT, botun veri kaynağı Binance'te
`not_trading` döndü (1h ve 4h); karar turu spec'e uygun olarak TON'u her turda "veri yok" sayar ve Claude'a sormaz.
Böylece listenin onda biri ölçüm boyunca hiç karar almaz ve ADR 0005'in ön kaydı uygulanamaz. Ölçüm (0060) henüz
başlamadı, hiçbir karar kaydı yok: liste şimdi, sonuç görülmeden değiştirilebilir.

## Decision
ADR 0005 kural 1'in listesinde TON, TRX ile değişir. Geçerli ön kayıtlı liste: BTC, ETH, SOL, BNB, XRP, ADA, DOGE,
AVAX, LINK, TRX (USDT spot); saatte bir tur, 1h mum. ADR 0005'in öteki kuralları (tek çağrı, veriye dayanma, risk
modülü, ayrı defter, ön kayıtlı ölçüm, bilgi kesimi) aynen geçerlidir. Liste ölçüm süresince değişmez; değişiklik yine
yeni ön kayıttır.

## Consequences
- Kazanılan: on coinin onu da Binance'ten okunur (TRX/USDT için 250 adet 1h mum boşluksuz geldi, 2026-11-20); liste
  piyasa değeri yüksek ve likit coinlerden oluşmaya devam eder.
- Bedeli: liste ön kayıttan sonra bir kez değişti; değişiklik ölçüm başlamadan ve hiçbir sonuç görülmeden, yalnız
  veri erişilemezliği yüzünden yapıldı (gözetleme yok). TRX, TON'dan farklı bir piyasa davranışı taşır; ölçüm bu
  listeyle yorumlanır.

## Alternatives considered
- **TON'u bırakıp dokuz coinle devam:** ölçümün kapsamı daralır, ADR 0005'in "on coin" kurgusu ve günlük çağrı hesabı
  boşuna değişir; erişilebilir bir eşdeğer varken gerekçesiz.
- **SUI ya da LTC:** ikisi de Binance'te boşluksuz okunuyor; sahip TRX'i seçti (piyasa değeri ve geçmişin uzunluğu).
- **TON'u başka bir borsadan okumak:** ikinci veri kaynağı ve bakım; bot Binance'e bağlı, kıyas aynı kaynakta olmalı.

## Revisit triggers
- Listedeki bir coin Binance'te işlemden kalkarsa ya da sürekli "veri yok" olursa (yeni ön kayıt, ölçüm başlamışsa
  ölçümün yorumu ADR ile).
