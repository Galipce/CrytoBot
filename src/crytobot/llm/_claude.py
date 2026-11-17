"""`claude -p` alt süreci: yalıtılmış tek çağrı (spec 0051 R-5, R-6; plan Risk 3, 4, 8).

Argv sabittir ve kullanıcı verisi taşımaz: talimat tek satır ASCII'dir (Windows'ta `claude` bir
`.cmd` sarmalayıcısıdır, argv cmd.exe'den geçer), prompt stdin'den gider. `--bare` kullanılmaz
(abonelik girişini okumaz); araçlar, MCP, ayar kaynakları, slash komutları ve oturum saklama
kapalıdır; `--fallback-model` ve `--json-schema` verilmez. Ortam üst süreçten gelir, eksi
`ANTHROPIC_API_KEY` ve adında KEY, TOKEN, SECRET ya da PASSWORD geçen değişkenler.

Süreç kendi süreç grubunda başlar (Windows `CREATE_NEW_PROCESS_GROUP`, POSIX `start_new_session`);
zaman aşımında, durdurmada ya da çıktı sınırı aşılınca bütün ağacıyla sonlandırılır (conventions,
Known traps). stdout en çok `OUTPUT_LIMIT` bayt okunur. Sonuç sınıfları: `ok`, `timeout`,
`no_session`, `quota`, `unknown`, `stopped`; hata metni sonuca girmez, yalnız sınıfı.
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO

from crytobot.llm._workdir import call_workdir

OUTPUT_LIMIT = 64 * 1024
_ERROR_LIMIT = 16 * 1024
_POLL_S = 0.1
_KILL_WAIT_S = 10.0
_SECRET_MARKS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
QUOTA_MARKS = ("usage limit", "rate limit", "hit your limit")
NO_SESSION_MARKS = ("not logged in", "/login", "invalid api key")


class CallOutcome(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    NO_SESSION = "no_session"
    QUOTA = "quota"
    UNKNOWN = "unknown"
    STOPPED = "stopped"


@dataclass(frozen=True)
class ClaudeRequest:
    model: str
    system_prompt: str
    prompt: str
    timeout_s: float


@dataclass(frozen=True)
class ClaudeReply:
    """`text`: yalnız `ok`'ta, zarfın `result` metni; çıktı sınırı aşıldıysa `None`
    (`overflow`). `size`: okunan stdout baytı. `workdir_clean`: çalışma klasörü çağrıdan sonra
    boştu."""

    outcome: CallOutcome
    text: str | None
    size: int
    seconds: float
    workdir_clean: bool
    overflow: bool = False


def claude_argv(executable: Sequence[str], model: str, system_prompt: str) -> list[str]:
    return [
        *executable,
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        system_prompt,
    ]


def claude_env(parent: Mapping[str, str]) -> dict[str, str]:
    """Üst ortam, eksi API anahtarı ve sır adlı değişkenler (plan Risk 3)."""
    return {
        name: value
        for name, value in parent.items()
        if not any(mark in name.upper() for mark in _SECRET_MARKS)
    }


def _marked(text: str, marks: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(mark in lowered for mark in marks)


def classify(returncode: int, stdout: bytes, stderr: bytes) -> tuple[CallOutcome, str | None]:
    """Zarfı ve çıkış kodunu sonuç sınıfına çevirir (plan Risk 4)."""
    message = ""
    try:
        envelope = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        envelope = None
    if isinstance(envelope, dict):
        result, is_error = envelope.get("result"), envelope.get("is_error")
        if returncode == 0 and is_error is False and isinstance(result, str):
            return CallOutcome.OK, result
        if isinstance(result, str):
            message = result
    if not message:
        message = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
    if _marked(message, QUOTA_MARKS):
        return CallOutcome.QUOTA, None
    if _marked(message, NO_SESSION_MARKS):
        return CallOutcome.NO_SESSION, None
    return CallOutcome.UNKNOWN, None


def _drain(stream: IO[bytes], limit: int, sink: bytearray, overflow: threading.Event) -> None:
    """Sınıra kadar biriktirir; sınırı aşan çıktıda işaret koyar, gerisini atar."""
    while chunk := stream.read(8192):
        room = limit - len(sink)
        if room > 0:
            sink.extend(chunk[:room])
        if len(chunk) > room:
            overflow.set()


def _feed(stream: IO[bytes], data: bytes) -> None:
    try:
        stream.write(data)
    except OSError:
        pass  # the process left before reading its prompt; its exit code tells why
    finally:
        with contextlib.suppress(OSError):
            stream.close()


def kill_tree(process: "subprocess.Popen[bytes]") -> None:
    """Sürecin bütün ağacını sonlandırır (Windows `taskkill /T /F`, POSIX `killpg`)."""
    if process.poll() is None:
        if sys.platform == "win32":
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=_KILL_WAIT_S,
                    check=False,
                )
        else:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        process.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=_KILL_WAIT_S)


def _spawn(argv: list[str], cwd: str, env: dict[str, str]) -> "subprocess.Popen[bytes]":
    if sys.platform == "win32":
        return subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    return subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=env,
        start_new_session=True,
    )


def call_claude(
    request: ClaudeRequest,
    *,
    executable: Sequence[str] | None,
    stopped: Callable[[], bool],
    environ: Mapping[str, str] | None = None,
) -> ClaudeReply:
    """Tek çağrı. `executable` yoksa (komut bulunamadı) `no_session`."""
    start = time.monotonic()
    env = claude_env(os.environ if environ is None else environ)
    with call_workdir() as workdir:
        outcome, text, size, overflowed = _run(request, executable, stopped, env, workdir.path)
    return ClaudeReply(outcome, text, size, time.monotonic() - start, workdir.clean, overflowed)


def _run(
    request: ClaudeRequest,
    executable: Sequence[str] | None,
    stopped: Callable[[], bool],
    env: dict[str, str],
    cwd: Path,
) -> tuple[CallOutcome, str | None, int, bool]:
    if not executable:
        return CallOutcome.NO_SESSION, None, 0, False
    argv = claude_argv(executable, request.model, request.system_prompt)
    try:
        process = _spawn(argv, str(cwd), env)
    except OSError:
        return CallOutcome.NO_SESSION, None, 0, False
    assert process.stdin is not None and process.stdout is not None
    assert process.stderr is not None
    out, err = bytearray(), bytearray()
    overflow, ignored = threading.Event(), threading.Event()
    threads = [
        threading.Thread(target=_feed, args=(process.stdin, request.prompt.encode("utf-8"))),
        threading.Thread(target=_drain, args=(process.stdout, OUTPUT_LIMIT, out, overflow)),
        threading.Thread(target=_drain, args=(process.stderr, _ERROR_LIMIT, err, ignored)),
    ]
    for thread in threads:
        thread.daemon = True
        thread.start()
    deadline = time.monotonic() + request.timeout_s
    ended: CallOutcome | None = None
    try:
        while process.poll() is None:
            if stopped():
                ended = CallOutcome.STOPPED
            elif overflow.is_set():
                ended = CallOutcome.OK
            elif time.monotonic() >= deadline:
                ended = CallOutcome.TIMEOUT
            if ended is not None:
                kill_tree(process)
                break
            time.sleep(_POLL_S)
    except BaseException:  # a forced stop (second Ctrl+C) never leaves the tree running
        kill_tree(process)
        raise
    for thread in threads:
        thread.join(timeout=_KILL_WAIT_S)
    # a reader still blocked means a survivor holds the pipe: closing it under the reader blocks
    # on Windows, so the daemon thread is left with it (the reply is decided without it)
    for stream, reader in ((process.stdout, threads[1]), (process.stderr, threads[2])):
        if not reader.is_alive():
            with contextlib.suppress(OSError):
                stream.close()
    if ended in (CallOutcome.STOPPED, CallOutcome.TIMEOUT):
        return ended, None, len(out), False
    if overflow.is_set():
        return CallOutcome.OK, None, len(out), True
    outcome, text = classify(process.returncode, bytes(out), bytes(err))
    if outcome is not CallOutcome.OK and stopped():
        # Ctrl+Break reaches the child's group too on Windows: it may die before the loop sees
        # the request; a failed call under a stop request is a stopped call (review I-3)
        return CallOutcome.STOPPED, None, len(out), False
    return outcome, text, len(out), False
