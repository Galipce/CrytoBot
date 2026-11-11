"""Spec 0028 AC-4 (R-2) aşama onayı ayar denetimleri (plan Adım 2); spec 0040 CB-1."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from crytobot.app import load_stage_config

SHA = "0123456789abcdef" * 4  # spec 0040: a valid report fingerprint


def valid_document() -> dict[str, Any]:
    return {
        "stage": {
            "report_path": "backtest-report.txt",
            "report_sha256": SHA,
            "approved_by": "Galip Badem",
            "approved_at": "2026-11-08T12:00:00Z",
            "min_trades": 15,
            "min_profit_factor": "1.5",
        }
    }


def test_stage_config_validation() -> None:
    """AC-4: Onay ayarları geçerliliği, eksik alanlar, tipler ve eşikler."""
    # Mutlu yol (tüm alanlar dolu)
    res = load_stage_config(valid_document())
    assert res.setting is None
    assert res.config is not None
    assert res.config.report_path == "backtest-report.txt"
    assert res.config.approved_by == "Galip Badem"
    assert res.config.approved_at == datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    assert res.config.min_trades == 15
    assert res.config.min_profit_factor == Decimal("1.5")

    # Mutlu yol (isteğe bağlı alanlar yok: min_trades varsayılan 10, min_profit_factor None)
    doc_defaults = {
        "stage": {
            "report_path": "report.txt",
            "report_sha256": SHA,
            "approved_by": "Ali",
            "approved_at": "2026-11-08T00:00:00+00:00",
        }
    }
    res_def = load_stage_config(doc_defaults)
    assert res_def.config is not None
    assert res_def.config.min_trades == 10
    assert res_def.config.min_profit_factor is None

    # [stage] bölümü yok
    res_missing_sec = load_stage_config({})
    assert res_missing_sec.setting == "stage"
    assert "ayar eksik: stage" in res_missing_sec.message

    # [stage] tablo değil
    res_bad_sec = load_stage_config({"stage": "not_a_table"})
    assert res_bad_sec.setting == "stage"
    assert "ayar geçersiz: stage" in res_bad_sec.message

    # document Mapping değil
    res_not_map = load_stage_config("string")
    assert res_not_map.setting == "stage"

    # Sırayla eksik alanlar
    # 1. report_path eksik
    d = valid_document()
    del d["stage"]["report_path"]
    res_rp = load_stage_config(d)
    assert res_rp.setting == "stage.report_path"
    assert "ayar eksik: stage.report_path" in res_rp.message

    # 1b. report_path boş veya metin dışı
    for bad_rp in ("", "   ", 123, None):
        d = valid_document()
        d["stage"]["report_path"] = bad_rp
        res_bad_rp = load_stage_config(d)
        assert res_bad_rp.setting == "stage.report_path"
        assert "ayar geçersiz: stage.report_path" in res_bad_rp.message

    # 2. approved_by eksik
    d = valid_document()
    del d["stage"]["approved_by"]
    res_ab = load_stage_config(d)
    assert res_ab.setting == "stage.approved_by"
    assert "ayar eksik: stage.approved_by" in res_ab.message

    # 2b. approved_by boş veya metin dışı
    for bad_ab in ("", "   ", 456, None):
        d = valid_document()
        d["stage"]["approved_by"] = bad_ab
        res_bad_ab = load_stage_config(d)
        assert res_bad_ab.setting == "stage.approved_by"
        assert "ayar geçersiz: stage.approved_by" in res_bad_ab.message

    # 3. approved_at eksik
    d = valid_document()
    del d["stage"]["approved_at"]
    res_at = load_stage_config(d)
    assert res_at.setting == "stage.approved_at"
    assert "ayar eksik: stage.approved_at" in res_at.message

    # 3b. approved_at ISO değil, zaman dilimsiz veya geçersiz
    for bad_at in ("invalid-date", "2026-11-08 12:00:00", "2026-11-08T12:00:00", 12345, None):
        d = valid_document()
        d["stage"]["approved_at"] = bad_at
        res_bad_at = load_stage_config(d)
        assert res_bad_at.setting == "stage.approved_at"
        assert "ayar geçersiz: stage.approved_at" in res_bad_at.message

    # 4. min_trades sıfır, negatif veya tam sayı değil
    for bad_mt in (0, -1, -10, 1.5, "10", True, False, None):
        d = valid_document()
        d["stage"]["min_trades"] = bad_mt
        res_bad_mt = load_stage_config(d)
        assert res_bad_mt.setting == "stage.min_trades"
        assert "ayar geçersiz: stage.min_trades" in res_bad_mt.message

    # 5. min_profit_factor 1'den küçük veya geçersiz tip
    for bad_pf in ("0.99", "0", "-1", "invalid", True, False, None):
        d = valid_document()
        d["stage"]["min_profit_factor"] = bad_pf
        res_bad_pf = load_stage_config(d)
        assert res_bad_pf.setting == "stage.min_profit_factor"
        assert "ayar geçersiz: stage.min_profit_factor" in res_bad_pf.message

    # 6. Bilinmeyen anahtar
    d = valid_document()
    d["stage"]["unknown_key"] = "test"
    res_unk = load_stage_config(d)
    assert res_unk.setting == "stage.unknown_key"
    assert "bilinmeyen ayar: stage.unknown_key" in res_unk.message


def test_live_stage_approval_required_for_live_mode() -> None:
    """Spec 0033 AC-3 (R-4): Canlı modda BR-10 live_approved_by ve live_approved_at zorunluluğu."""
    doc = valid_document()

    # 1. Paper modda live onay alanları olmadan geçerli
    res_paper = load_stage_config(doc, mode="paper")
    assert res_paper.config is not None
    assert res_paper.config.live_approved_by is None
    assert res_paper.config.live_approved_at is None

    # 2. Canlı modda live_approved_by eksik
    res_missing_by = load_stage_config(doc, mode="live")
    assert res_missing_by.setting == "stage.live_approved_by"
    assert "ayar eksik: stage.live_approved_by" in res_missing_by.message

    # 3. Canlı modda live_approved_by boş/geçersiz
    for bad_by in ("", "   ", 123, None):
        d_bad_by = valid_document()
        d_bad_by["stage"]["live_approved_by"] = bad_by
        res_bad_by = load_stage_config(d_bad_by, mode="live")
        assert res_bad_by.setting == "stage.live_approved_by"
        assert "ayar geçersiz: stage.live_approved_by" in res_bad_by.message

    # 4. Canlı modda live_approved_by var ama live_approved_at eksik
    doc_with_by = valid_document()
    doc_with_by["stage"]["live_approved_by"] = "Galip Badem"
    res_missing_at = load_stage_config(doc_with_by, mode="live")
    assert res_missing_at.setting == "stage.live_approved_at"
    assert "ayar eksik: stage.live_approved_at" in res_missing_at.message

    # 5. Canlı modda live_approved_at geçersiz (ISO değil, saat dilimsiz vb.)
    for bad_at in ("invalid-date", "2026-11-09 12:00:00", "2026-11-09T12:00:00", 12345, None):
        d_bad_at = valid_document()
        d_bad_at["stage"]["live_approved_by"] = "Galip Badem"
        d_bad_at["stage"]["live_approved_at"] = bad_at
        res_bad_at = load_stage_config(d_bad_at, mode="live")
        assert res_bad_at.setting == "stage.live_approved_at"
        assert "ayar geçersiz: stage.live_approved_at" in res_bad_at.message

    # 6. Mutlu yol (canlı modda her iki alan da geçerli UTC)
    doc_live = valid_document()
    doc_live["stage"]["live_approved_by"] = "Galip Badem"
    doc_live["stage"]["live_approved_at"] = "2026-11-09T20:00:00Z"
    doc_live["stage"]["paper_store_path"] = "paper.sqlite"  # spec 0038 CB-2: required in live
    res_live = load_stage_config(doc_live, mode="live")
    assert res_live.config is not None
    assert res_live.config.live_approved_by == "Galip Badem"
    assert res_live.config.live_approved_at == datetime(2026, 11, 9, 20, 0, tzinfo=UTC)

    # 7. Paper modda da dolu girilirse doğrulanır ve config'e yazılır
    res_paper_with_live = load_stage_config(doc_live, mode="paper")
    assert res_paper_with_live.config is not None
    assert res_paper_with_live.config.live_approved_by == "Galip Badem"
    assert res_paper_with_live.config.live_approved_at == datetime(2026, 11, 9, 20, 0, tzinfo=UTC)


def test_report_sha256_missing_or_invalid() -> None:
    """Spec 0040 CB-1, G-2: anahtar zorunlu, 64 onaltılık; harf büyüklüğü fark etmez."""
    d = valid_document()
    del d["stage"]["report_sha256"]
    for mode in ("paper", "live"):
        missing = load_stage_config(d, mode=mode)
        assert missing.config is None
        assert (missing.setting, missing.message) == (
            "stage.report_sha256",
            "ayar eksik: stage.report_sha256",
        )

    for bad in ("", SHA[:63], SHA + "0", "g" + SHA[1:], " " * 64, 123, None, True, ["a"]):
        d = valid_document()
        d["stage"]["report_sha256"] = bad
        invalid = load_stage_config(d)
        assert invalid.config is None
        assert (invalid.setting, invalid.message) == (
            "stage.report_sha256",
            "ayar geçersiz: stage.report_sha256",
        )

    d = valid_document()
    d["stage"]["report_sha256"] = SHA.upper()
    upper = load_stage_config(d)
    assert upper.config is not None
    assert upper.config.report_sha256 == SHA


def test_report_sha256_is_checked_right_after_report_path() -> None:
    """Dosya sırası: `report_path` sorunu önce, `report_sha256` sonra, `approved_by` en son."""
    d = valid_document()
    del d["stage"]["report_path"]
    d["stage"]["report_sha256"] = "bozuk"
    assert load_stage_config(d).setting == "stage.report_path"
    d = valid_document()
    d["stage"]["report_sha256"] = "bozuk"
    del d["stage"]["approved_by"]
    assert load_stage_config(d).setting == "stage.report_sha256"
