# Spec 0061 — LLM karar listesi 20 coin, tur özeti Telegram'da, ölçüm yeniden başlar (mini)

- Status: In progress
- Mode: strict
- Plan: `specs/plans/0061-plan.md`
- Self-critique: done
- Source: ADR 0007; sahip isteği 2026-11-20 ("her çalışma sonucu bunları bana telegramdan göndersin", "coin sayısını
  arttıralım mı" → 20)
- Supersedes: 0059/R-2, AC-2 (48 adet 1h ve 30 adet 4h mum gösterimi), 0059/R-6, AC-6 (yalnız `al` bildirilir),
  0059/R-1, AC-1 (liste ADR 0005/0006'daki on coin); 0060/C-6, AC-6 (ölçüm anları 2026-11-20T03:00Z → 2027-02-18T03:00Z)

## Intent
Sahip karar turunun her sonucunu Telegram'dan görmek ve Claude'a daha çok fırsat tanımak istiyor: liste ADR 0007 ile
20 coine çıkar, her tur tek satırlık bir özet bildirir, günlük ölçüm raporu da bir özet satırı gönderebilir. Liste
değiştiği için ölçüm yeni ve sabit bir andan 90 gün yeniden başlar; eşikler ve kurallar değişmez.

Clarify kararları (Galip Badem, 2026-11-20): her tur tek kısa özet; `al` olduğunda bugünkü ayrıntılı mesaj da gider;
başarısız tur da bildirilir; günlük `llm-paper` özeti; S0 ve skorlayıcı kapsam dışı; liste 20 coin (öneri kabul);
Telegram ve liste değişikliği tek spec'te — karar turunu tek yeniden başlatmayla yüklemek için.

Self-critique kararları (Galip Badem, 2026-11-20, "onaylıyorum" — bütün öneriler kabul):
- **G-1:** Yeni başlangıç: ship'ten sonra gelen ve merge'den en az 2 saat sonraki ilk 00:00 UTC; sahip `decide`
  görevini bu andan önce yeniden başlatır. Kesin an ship'te bu spec'e ve koda yazılır.
- **G-2:** Geç kalındığı için atlanan tur (kayda yazılmaz) için de tek satırlık "tur atlandı" mesajı gider.
- **G-3:** Kota beklemesi ya da veri yok turları dahil her yazılan tur bir mesajdır (günde en çok 24).
- **G-4:** Rapor özeti iletilemezse rapor yine başarılı biter (çıkış 0); "bildirim iletilemedi" satırı yazılır.
- **G-5:** On coinlik dönemin kayıtları dosyada kalır, başlangıçtan önce oldukları için ölçüme girmez; istemin parmak
  izi değişmez, ölçümü sabit başlangıç anı ayırır.

## Changed behavior
- [ ] CB-1 — Liste: `decide` ve `llm-paper` ADR 0007'nin 20 coinini kullanır (BTC ETH SOL BNB XRP ADA DOGE AVAX LINK
  TRX BCH LTC SUI XLM HBAR DOT SHIB UNI NEAR APT); başka liste ret (adıyla, çağrısız).
- [ ] CB-2 — İstem boyutu: 20 coinin verisi kısaltılmadan sınıra sığar: coin başına son 24 adet 1h ve son 12 adet 4h mum
  gösterilir; indikatörler (EMA 20/50/200, RSI 14, ATR 14), değişimler, 48 mumun en yüksek/en düşüğü (doğrulama
  aralığı) ve olay skorları aynen kalır. Gerçek 20 coinlik bir turda veri bölümü 64 KB'ın altındadır.
- [ ] CB-3 — Tur özeti: kayda yazılan her tur için Telegram'a tek mesaj: tur anı, sonuç sınıfı (ok, şema dışı, sınır,
  kota bekleniyor, veri yok, zaman aşımı…), `al`/`bekle`/tutarsız/şema dışı/veri yok sayıları ve `al` coinleri;
  "paper öncesi — uygulanmıyor" işaretli. Geçerli `al` için bugünkü ayrıntılı mesaj ayrıca gider. Telegram kapalıysa
  yalnız satır; iletilemezse tur durmaz.
- [ ] CB-4 — Rapor özeti: `llm-paper report --notify` raporu yazdıktan sonra Telegram'a tek özet satırı gönderir
  (ufuk, kapanmış işlem, net kâr, drawdown, hüküm); `--notify`'sız `report` ağa hiç çıkmaz. Günlük görev `--notify`
  kullanır.
- [ ] CB-5 — Ölçüm anları: başlangıç ship'te bu spec'e yazılan, yeni kodun dağıtımından sonra gelen sabit bir 1h
  sınırıdır, bitiş başlangıç + 90 gün; kodda sabittir, ayardan verilemez. Başlangıçtan önceki kayıtlar (on coinlik
  dönem dahil) ölçüme girmez.

## Preserved behavior
- [ ] PB-1 — Tur başına tek Claude çağrısı, günlük sınır, kota beklemesi, geç kalınan turun atlanması, yalıtım (0059).
- [ ] PB-2 — Yanıt doğrulaması ve tutarlılık kuralları (±%20 aralığı 48 adet 1h mumun en yüksek/en düşüğünden),
  yalnız eklenen kayıt, ham yanıtın yazılmaması (0059 AC-4, AC-5).
- [ ] PB-3 — `llm-paper` oynatması, eşlenik rastgele, risk kuralları ve hükmün eşikleri aynen (0060 C-1…C-5, C-7,
  C-8); `--notify`'sız rapor ağsız, kilitsiz, girdileri değiştirmez (0060 AC-10).
- [ ] PB-4 — Bot ve S0 koşusu (ADR 0004) etkilenmez; bot karar kaydını okumaz (R-3k, R-3m).

## Out of scope
- Hükmün eşikleri, kasa, risk ayarları, sıklık, model, istemin talimat metni (yalnız gösterilen mum sayısı değişir).
- S0 botunun, skorlayıcının ve toplayıcının bildirimleri; Telegram'dan komut.
- Split: liste ve Telegram ayrı yetenekler; tek spec olarak tutuldu — Galip Badem, karar turunu tek yeniden
  başlatmayla yüklemek için.

## Definition of Done
- [ ] `scripts/check` green
- [ ] Independent review done; real findings fixed, noise rejected with written rationale, deferred ones in `specs/backlog.md`
- [ ] Criterion ↔ evidence table complete for CB-* **and** PB-* (UI: before/after screenshots, agent-captured, judged at SHIP)
- [ ] Spec moved to `specs/done/` (immutable there)

## Handoff
Next: PLAN — Developer runs /plan 0061
