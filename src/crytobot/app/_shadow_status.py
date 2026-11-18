"""Gölge kaydın durumu (spec 0052 R-9; plan step 5, Risk 5, A-1).

Girdi ayrıştırılmış satırlardır: giriş noktası dosyayı yalnız okur, her satırı JSON olarak çözer,
çözülemeyeni (çökmede yarım kalan son satır) `None` verir. Beklenen alanları taşımayan satır da
bozuk sayılır. Son kayıt hatası bot kayıt dosyasının satırlarından okunur (döngünün `hata` satırı).
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime

from crytobot.app._shadow import BUY_YES, STEP

NO_SHADOW = "henüz gölge kayıt yok"
STATES = ("bastırılırdı", "bastırılmazdı", "bastırılmazdı — eksik bilgi", "filtre yok")
_ERROR_MARK = f" hata döngü hatası: {STEP} "


def _valid(row: object) -> Mapping[str, object] | None:
    if not isinstance(row, Mapping):
        return None
    texts = ("turn_at", "pair", "state", "reason", "technical_buy")
    if any(not isinstance(row.get(key), str) for key in texts):
        return None
    if row["state"] not in STATES:
        return None
    try:
        moment = datetime.fromisoformat(str(row["turn_at"]))
    except ValueError:
        return None
    if moment.utcoffset() is None:
        return None
    return row


def last_shadow_error(log_lines: Iterable[str]) -> str | None:
    """Bot kayıt dosyasındaki son gölge kayıt hatasının tip adı."""
    last: str | None = None
    for text in log_lines:
        at = text.find(_ERROR_MARK)
        if at >= 0:
            last = text[at + len(_ERROR_MARK) :].strip() or None
    return last


def _counts(counter: Mapping[str, int], names: Sequence[str]) -> str:
    return " ".join(f"{name}={counter.get(name, 0)}" for name in names)


def shadow_status_lines(
    path: str, rows: Sequence[object] | None, last_error: str | None
) -> list[str]:
    """R-9: ilk ve son tur anı, tur sayısı, çift başına durum sayıları, `filtre yok` nedenleri,
    teknik al ve durumlara dağılımı, bozuk satır, son kayıt hatası."""
    if rows is None:
        return [NO_SHADOW]
    valid = [row for row in (_valid(each) for each in rows) if row is not None]
    broken = len(rows) - len(valid)
    error = f"son kayıt hatası: {last_error or 'yok'}"
    if not valid:
        return [NO_SHADOW, f"bozuk satır={broken}", error]
    moments = sorted({datetime.fromisoformat(str(row["turn_at"])) for row in valid})
    pairs: dict[str, dict[str, int]] = {}
    reasons: dict[str, int] = {}
    buys: dict[str, int] = {}
    for row in valid:
        state, pair = str(row["state"]), str(row["pair"])
        counter = pairs.setdefault(pair, {})
        counter[state] = counter.get(state, 0) + 1
        if state == "filtre yok":
            reasons[str(row["reason"])] = reasons.get(str(row["reason"]), 0) + 1
        if row["technical_buy"] == BUY_YES:
            buys[state] = buys.get(state, 0) + 1
    lines = [
        f"gölge kayıt: {path}",
        f"ilk tur: {moments[0].isoformat()}",
        f"son tur: {moments[-1].isoformat()}",
        f"tur sayısı: {len(moments)}",
    ]
    lines += [f"{pair}: {_counts(pairs[pair], STATES)}" for pair in sorted(pairs)]
    named = " ".join(f"{reason}={count}" for reason, count in sorted(reasons.items()))
    lines.append(f"filtre yok nedenleri: {named or 'yok'}")
    lines.append(f"teknik al: toplam={sum(buys.values())} {_counts(buys, STATES)}")
    lines.append(f"bozuk satır={broken}")
    lines.append(error)
    return lines
