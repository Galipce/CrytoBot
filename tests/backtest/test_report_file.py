"""Spec 0025 AC-10 (dosya kısmı), R-4, R-13: rapor dosyası `.part` üzerinden, üzerine yazmadan."""

import os
from pathlib import Path

import pytest

from crytobot.backtest import PART_SUFFIX, report_exists, write_report

TEXT = "CrytoBot backtest raporu\nçiftler: BTC/USDT\n"


def names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def test_writes_exact_bytes(tmp_path: Path) -> None:
    path = tmp_path / "rapor.txt"
    assert write_report(str(path), TEXT)
    assert path.read_bytes() == TEXT.encode("utf-8")
    assert names(tmp_path) == ["rapor.txt"]


@pytest.mark.parametrize("existing", ["rapor.txt", "rapor.txt" + PART_SUFFIX])
def test_report_exists_sees_file_or_part(tmp_path: Path, existing: str) -> None:
    path = tmp_path / "rapor.txt"
    assert not report_exists(str(path))
    (tmp_path / existing).write_bytes(b"\xff bozuk")
    assert report_exists(str(path))


def test_report_exists_sees_a_directory(tmp_path: Path) -> None:
    (tmp_path / "rapor.txt").mkdir()
    assert report_exists(str(tmp_path / "rapor.txt"))


def test_never_writes_over_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "rapor.txt"
    path.write_text("eski", encoding="utf-8")
    assert not write_report(str(path), TEXT)
    assert path.read_text(encoding="utf-8") == "eski"
    assert names(tmp_path) == ["rapor.txt"]


def test_another_part_is_left_alone(tmp_path: Path) -> None:
    path = tmp_path / "rapor.txt"
    other = tmp_path / ("rapor.txt" + PART_SUFFIX)
    other.write_text("başka koşu", encoding="utf-8")
    assert not write_report(str(path), TEXT)
    assert other.read_text(encoding="utf-8") == "başka koşu"
    assert names(tmp_path) == ["rapor.txt" + PART_SUFFIX]


def test_missing_directory_leaves_nothing(tmp_path: Path) -> None:
    assert not write_report(str(tmp_path / "yok" / "rapor.txt"), TEXT)
    assert names(tmp_path) == []


def test_failed_link_removes_part(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_source: str, _target: str) -> None:
        raise OSError("bağlanamadı")

    monkeypatch.setattr(os, "link", refuse)
    assert not write_report(str(tmp_path / "rapor.txt"), TEXT)
    assert names(tmp_path) == []


class Forced(BaseException):
    pass


def test_forced_stop_while_writing_removes_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-13: ikinci durdurma isteği yazma sırasında gelse de tamamlanmış görünen dosya kalmaz."""

    def interrupted(_source: str, _target: str) -> None:
        raise Forced

    monkeypatch.setattr(os, "link", interrupted)
    with pytest.raises(Forced):
        write_report(str(tmp_path / "rapor.txt"), TEXT)
    assert names(tmp_path) == []
