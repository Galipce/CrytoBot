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


def kill_flag_path(store_path: str | Path) -> Path:
    """<depo>.kill: çalışan bota kill switch isteği bayrağı (spec 0035, plan Risk 1)."""
    p = Path(store_path)
    return p.with_suffix(p.suffix + ".kill")


def set_kill_flag(store_path: str | Path) -> Path:
    """Kill switch isteğini yazar. Bayrak kalıcıdır: bot onu kendi kaydıyla işleyene kadar durur."""
    flag = kill_flag_path(store_path)
    flag.write_text("kill-switch", encoding="utf-8")
    return flag


def kill_flag_set(store_path: str | Path) -> bool:
    """Bekleyen kill switch isteği var mı?"""
    return kill_flag_path(store_path).exists()


def clear_kill_flag(store_path: str | Path) -> None:
    """İstek bot tarafından depoya işlendikten sonra silinir; silinemezse bir sonraki tur yeniden
    dener (kill switch zaten devrede olduğu için tekrar yazmaz)."""
    with suppress(OSError):
        kill_flag_path(store_path).unlink(missing_ok=True)
