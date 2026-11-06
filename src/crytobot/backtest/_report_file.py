"""Rapor dosyası (spec 0025 R-4, R-13; plan Risk 10; 0023 Risk 8'in aynı yolu).

Yolda dosya ya da `<yol>.part` varsa rapor yazılmaz: okunabilir, bozuk ya da yarım, ne olduğuna
bakılmaz. Yazma dışlayıcı açılan `.part`'a yapılır, sonra `os.link` ile son ada bağlanır: hedef
varsa bağlama reddedilir, üzerine yazılmaz. `.part` her durumda silinir (`BaseException`'da da);
`open` başarısızsa silinmez, çünkü o `.part` başkasınındır. Böylece tamamlanmış görünen ama yarım
bir rapor dosyası hiç kalmaz.
"""

import os
from contextlib import suppress
from typing import Final

PART_SUFFIX: Final = ".part"


def part_path(path: str) -> str:
    return path + PART_SUFFIX


def report_exists(path: str) -> bool:
    """R-4: yolda ya da `.part` yolunda herhangi bir şey var mı."""
    return os.path.lexists(path) or os.path.lexists(part_path(path))


def write_report(path: str, text: str) -> bool:
    """Raporu UTF-8 ve `\\n` ile yazar; tamamlandıysa `True`. İstisna fırlatmaz (`OSError`)."""
    part = part_path(path)
    try:
        handle = open(part, "x", encoding="utf-8", newline="\n")  # noqa: SIM115 - closed below
    except OSError:
        return False
    try:
        with handle:
            handle.write(text)
        os.link(part, path)
    except OSError:
        return False
    finally:
        with suppress(OSError):
            os.unlink(part)
    return True
