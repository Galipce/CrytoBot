"""Spec 0052 R-9, AC-10 (plan step 5, Risk 5, A-1): gölge kaydın durum satırları — R-9'un bütün
kalemleri, kayıt yokken "henüz gölge kayıt yok", yarım kalan ve bozuk satır sayılır, son kayıt
hatası bot kayıt dosyasından okunur."""

from datetime import UTC, datetime, timedelta

from crytobot.app import NO_SHADOW, last_shadow_error, shadow_status_lines

T = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def row(at: datetime, pair: str, state: str, reason: str, buy: str = "yok") -> dict[str, object]:
    return {
        "version": "1",
        "turn_at": at.isoformat(),
        "pair": pair,
        "state": state,
        "reason": reason,
        "technical_buy": buy,
    }


def test_all_items() -> None:
    later = T + timedelta(hours=1)
    last = T + timedelta(hours=2)
    rows: list[object] = [
        row(T, "BTC/USDT", "filtre yok", "skorlayıcı durmuş"),
        row(T, "ETH/USDT", "filtre yok", "skorlayıcı durmuş", "var"),
        row(later, "BTC/USDT", "bastırılırdı", "olumsuz olay", "var"),
        row(later, "ETH/USDT", "bastırılmazdı — eksik bilgi", "eksik bilgi"),
        row(last, "BTC/USDT", "bastırılmazdı", "olumsuz olay yok", "var"),
        row(last, "ETH/USDT", "filtre yok", "haber kaydı yok"),
    ]
    lines = shadow_status_lines("shadow.jsonl", rows, "OSError")
    assert lines == [
        "gölge kayıt: shadow.jsonl",
        f"ilk tur: {T.isoformat()}",
        f"son tur: {last.isoformat()}",
        "tur sayısı: 3",
        "BTC/USDT: bastırılırdı=1 bastırılmazdı=1 bastırılmazdı — eksik bilgi=0 filtre yok=1",
        "ETH/USDT: bastırılırdı=0 bastırılmazdı=0 bastırılmazdı — eksik bilgi=1 filtre yok=2",
        "filtre yok nedenleri: haber kaydı yok=1 skorlayıcı durmuş=2",
        "teknik al: toplam=3 bastırılırdı=1 bastırılmazdı=1 bastırılmazdı — eksik bilgi=0"
        " filtre yok=1",
        "bozuk satır=0",
        "son kayıt hatası: OSError",
    ]


def test_no_record() -> None:
    assert shadow_status_lines("shadow.jsonl", None, None) == [NO_SHADOW]
    assert NO_SHADOW == "henüz gölge kayıt yok"
    assert shadow_status_lines("shadow.jsonl", [], None) == [
        NO_SHADOW,
        "bozuk satır=0",
        "son kayıt hatası: yok",
    ]


def test_torn_line_counted() -> None:
    good = row(T, "BTC/USDT", "bastırılmazdı", "olumsuz olay yok")
    rows: list[object] = [
        good,
        None,  # a torn last line: not JSON
        {**good, "state": "bilinmiyor"},
        {**good, "turn_at": "2026-11-18T12:00:00"},  # no time zone
        {**good, "turn_at": "dün"},
        {**good, "pair": 3},
        ["not", "a", "row"],
    ]
    lines = shadow_status_lines("shadow.jsonl", rows, None)
    assert "tur sayısı: 1" in lines
    assert "bozuk satır=6" in lines
    assert lines[-1] == "son kayıt hatası: yok"


def test_last_shadow_error_from_the_bot_log() -> None:
    log = [
        "2026-11-18T12:00:00+00:00 başlatma başladı: mod=paper",
        "2026-11-18T12:00:02+00:00 hata döngü hatası: gölge kayıt PermissionError",
        "2026-11-18T12:00:02+00:00 tur tur: sonuç=completed",
        "2026-11-18T13:00:02+00:00 hata döngü hatası: okuma TimeoutError",
        "2026-11-18T14:00:02+00:00 hata döngü hatası: gölge kayıt KeyError",
        "2026-11-18T15:00:02+00:00 tur tur: sonuç=completed",
    ]
    assert last_shadow_error(log) == "KeyError"
    assert last_shadow_error(log[:3]) == "PermissionError"
    assert last_shadow_error(log[:1]) is None
