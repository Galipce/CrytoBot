"""Süreç denetimi ve IPC kilit/bayrak yönetimi (spec 0030 R-4)."""

import sys
from contextlib import suppress
from pathlib import Path


def stop_flag_path(store_path: str | Path) -> Path:
    """<depo>.stop bayrak dosyasının yolu."""
    p = Path(store_path)
    return p.with_suffix(p.suffix + ".stop")


def set_stop_flag(store_path: str | Path) -> Path:
    """<depo>.stop bayrak dosyasını oluşturur."""
    flag = stop_flag_path(store_path)
    flag.write_text("stop", encoding="utf-8")
    return flag


def clear_stop_flag(store_path: str | Path) -> None:
    """<depo>.stop bayrak dosyasını sessizce siler."""
    with suppress(OSError):
        stop_flag_path(store_path).unlink(missing_ok=True)


def is_lock_held(store_path: str | Path) -> bool:
    """<depo>.lock dosyasının çalışan bir süreç tarafından tutulup tutulmadığını yoklar."""
    p = Path(store_path)
    lock_path = p.with_suffix(p.suffix + ".lock")
    if not lock_path.exists():
        return False
    try:
        with open(lock_path, "a+b") as handle:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    return False
                except OSError:
                    return True
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    return False
                except OSError:
                    return True
    except OSError:
        return True
