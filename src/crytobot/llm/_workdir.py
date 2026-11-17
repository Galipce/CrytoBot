"""Çağrı başına boş çalışma klasörü (spec 0051 R-5, AC-4).

Klasör sistemin geçici dizininde açılır, çağrıdan sonra boş mu diye bakılır ve her durumda silinir.
Boş değilse çağrı yine sonuçlanır; boş olmadığı yanıtta işaretlidir (kayda ve duman koşusuna girer).
"""

import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

PREFIX = "crytobot-llm-"


@dataclass
class Workdir:
    path: Path
    clean: bool = True


def is_empty(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except OSError:
        return False


@contextmanager
def call_workdir() -> Iterator[Workdir]:
    """Boş klasör verir; çıkışta `clean` doldurulur ve klasör silinir."""
    workdir = Workdir(Path(tempfile.mkdtemp(prefix=PREFIX)))
    try:
        yield workdir
    finally:
        workdir.clean = is_empty(workdir.path)
        shutil.rmtree(workdir.path, ignore_errors=True)
