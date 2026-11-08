"""Spec 0022 AC-7 (R-6), iki gerçek süreç: ikinci başlatma reddedilir, ilki çalışmayı sürdürür.

Çalışan bot gerçek giriş noktasıdır (`run`, gerçek saat, gerçek bekleme, gerçek sinyaller); yalnız
okuması ağsızdır: veri vermeyen bir okuma. İkinci süreç gerçek `python -m crytobot start`'tır ve
kilit depodan ve borsadan önce alındığı için ağa çıkmadan reddedilir. Bot gerçek bir durdurma
sinyaliyle (Windows'ta Ctrl+Break, Unix'te SIGTERM) temiz durur. `slow`: yalnız full koşuda.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from crytobot.__main__ import EXIT_OK, EXIT_REFUSED, run
from tests.main.test_entry import config_text

CHILD = """\
import sys
from pathlib import Path

from crytobot.__main__ import install_signals, make_wait, run, utc_now
from crytobot.app import StopRequest
from crytobot.market_data import MarketRead


def read(pairs, settings):
    return MarketRead((), utc_now(), None)  # no data, no network


stop = StopRequest()
install_signals(stop)
sys.exit(run(["start", "--trial"], config_path=Path("crytobot.toml"), stop=stop, read=read,
             wait=make_wait(stop)))
"""
SETTINGS = {
    "turn_interval": '"1m"',
    "candle_interval": '"1m"',
    "read_budget": "30",
    "call_timeout": "5",
    "max_candle_age": "60",
}
# Ctrl+Break reaches only a process with its own group (Windows); POSIX gets SIGTERM
if sys.platform == "win32":
    FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP
else:
    FLAGS = 0


def _wait_for(path: Path, text: str, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and text in path.read_text(encoding="utf-8"):
            return True
        time.sleep(0.1)
    return False


def _stop(process: subprocess.Popen[bytes]) -> None:
    if sys.platform == "win32":
        os.kill(process.pid, signal.CTRL_BREAK_EVENT)
    else:
        process.send_signal(signal.SIGTERM)


@pytest.mark.slow
def test_second_process_is_refused_and_first_keeps_running(tmp_path: Path) -> None:
    (tmp_path / "crytobot.toml").write_text(config_text(tmp_path, **SETTINGS), encoding="utf-8")
    (tmp_path / "child.py").write_text(CHILD, encoding="utf-8")
    assert run(["prepare"], config_path=tmp_path / "crytobot.toml") == EXIT_OK
    log = tmp_path / "bot.log"
    with (tmp_path / "child.out").open("wb") as out:
        first = subprocess.Popen(
            [sys.executable, "child.py"], cwd=tmp_path, stdout=out, stderr=out, creationflags=FLAGS
        )
        try:
            assert _wait_for(log, "tur: ", 60), "the first bot made no turn"
            second = subprocess.run(
                [sys.executable, "-m", "crytobot", "start", "--trial"],
                cwd=tmp_path,
                capture_output=True,
                timeout=60,
                check=False,
            )
            assert second.returncode == EXIT_REFUSED
            # the pipe uses the console code page; the log file is UTF-8 (R-13)
            refusal = "start reddedildi: depo başka bir bot sürecinde kullanılıyor"
            assert refusal in log.read_text(encoding="utf-8")
            assert first.poll() is None, "the running bot was affected"
            _stop(first)
            assert first.wait(timeout=30) == EXIT_OK
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=10)
    text = log.read_text(encoding="utf-8")
    assert text.count("başlatma başladı") == 1
    assert "durdu: neden=durdurma isteği (SIG" in text
