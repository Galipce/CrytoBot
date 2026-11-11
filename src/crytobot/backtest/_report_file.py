"""Rapor dosyası (spec 0025 R-4, R-13; plan Risk 10; 0023 Risk 8'in aynı yolu).

Yolda dosya ya da `<yol>.part` varsa rapor yazılmaz: okunabilir, bozuk ya da yarım, ne olduğuna
bakılmaz. Yazma dışlayıcı açılan `.part`'a yapılır, sonra `os.link` ile son ada bağlanır: hedef
varsa bağlama reddedilir, üzerine yazılmaz. `.part` her durumda silinir (`BaseException`'da da);
`open` başarısızsa silinmez, çünkü o `.part` başkasınındır. Böylece tamamlanmış görünen ama yarım
bir rapor dosyası hiç kalmaz.

Spec 0040 CB-1 (plan Risk 4): metin bir kez UTF-8'e çevrilir (`report_bytes`, satır sonu
dönüştürmesi yok); dosyaya o baytlar yazılır, parmak izi (`report_fingerprint`) aynı baytların
SHA-256 özetidir.
"""

import hashlib
import os
from contextlib import suppress
from typing import Final

PART_SUFFIX: Final = ".part"


def part_path(path: str) -> str:
    return path + PART_SUFFIX


def report_exists(path: str) -> bool:
    """R-4: yolda ya da `.part` yolunda herhangi bir şey var mı."""
    return os.path.lexists(path) or os.path.lexists(part_path(path))


def report_bytes(text: str) -> bytes:
    """Dosyaya yazılan baytlar: UTF-8, dönüştürmesiz."""
    return text.encode("utf-8")


def fingerprint_of(data: bytes) -> str:
    """Ham baytların SHA-256 özeti, 64 küçük onaltılık karakter (spec 0040 G-1)."""
    return hashlib.sha256(data).hexdigest()


def report_fingerprint(text: str) -> str:
    """`write_report`'un diske yazdığı baytların parmak izi."""
    return fingerprint_of(report_bytes(text))


def write_report(path: str, text: str) -> bool:
    """Raporu `report_bytes` ile yazar; tamamlandıysa `True`. İstisna fırlatmaz (`OSError`)."""
    part = part_path(path)
    data = report_bytes(text)
    try:
        handle = open(part, "xb")  # noqa: SIM115 - closed below
    except OSError:
        return False
    try:
        with handle:
            handle.write(data)
        os.link(part, path)
    except OSError:
        return False
    finally:
        with suppress(OSError):
            os.unlink(part)
    return True
