"""Spec 0051 AC-4, AC-5 (plan Risk 3, 4): yalıtılmış argv ve ortam, sonuç sınıflama. Süreç
başlatılmaz."""

import json

import pytest

from crytobot.llm import CallOutcome, classify, claude_argv, claude_env


def test_isolated_argv_and_env() -> None:
    argv = claude_argv(["claude"], "claude-sonnet-5-5", "Score the news.")
    assert argv == [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--model",
        "claude-sonnet-5-5",
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        "Score the news.",
    ]
    # --bare reads no subscription login; a fallback model would change the scored model
    assert "--bare" not in argv
    assert not any(
        flag.startswith(("--fallback-model", "--json-schema", "--resume")) for flag in argv
    )
    assert not any(flag in ("-c", "--continue", "--mcp-config", "--add-dir") for flag in argv)

    parent = {
        "PATH": "/bin",
        "USERPROFILE": "C:/Users/me",
        "ANTHROPIC_API_KEY": "sk-ant-x",
        "OPENAI_api_key": "x",
        "GITHUB_TOKEN": "x",
        "DB_PASSWORD": "x",
        "my_secret": "x",
        "TELEGRAM_BOT_TOKEN": "x",
        "LANG": "C.UTF-8",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_GIT_BASH_PATH": "C:/Git/bin/bash.exe",
    }
    assert claude_env(parent) == {
        "PATH": "/bin",
        "USERPROFILE": "C:/Users/me",
        "LANG": "C.UTF-8",
        "CLAUDE_CODE_GIT_BASH_PATH": "C:/Git/bin/bash.exe",  # needed on Windows: kept
    }


def envelope(result: object, *, is_error: bool = False) -> bytes:
    return json.dumps({"type": "result", "is_error": is_error, "result": result}).encode()


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr", "expected"),
    [
        (0, envelope('{"events": []}'), b"", CallOutcome.OK),
        (
            1,
            envelope("Claude AI usage limit reached|1700000000", is_error=True),
            b"",
            CallOutcome.QUOTA,
        ),
        (1, envelope("You've hit your limit · resets 5pm", is_error=True), b"", CallOutcome.QUOTA),
        (1, envelope("API Error: Rate limit exceeded", is_error=True), b"", CallOutcome.QUOTA),
        (
            1,
            envelope("Invalid API key · Please run /login", is_error=True),
            b"",
            CallOutcome.NO_SESSION,
        ),
        (1, b"", b"Not logged in. Please run /login", CallOutcome.NO_SESSION),
        (1, envelope("Something broke", is_error=True), b"", CallOutcome.UNKNOWN),
        (0, envelope("text", is_error=True), b"", CallOutcome.UNKNOWN),
        (0, b"not json at all", b"", CallOutcome.UNKNOWN),
        (0, b"\xff\xfe", b"", CallOutcome.UNKNOWN),
        (0, json.dumps([1, 2]).encode(), b"", CallOutcome.UNKNOWN),
        (0, json.dumps({"is_error": False, "result": 5}).encode(), b"", CallOutcome.UNKNOWN),
        (3, b"", b"", CallOutcome.UNKNOWN),
    ],
)
def test_outcome_classification(
    returncode: int, stdout: bytes, stderr: bytes, expected: CallOutcome
) -> None:
    outcome, text = classify(returncode, stdout, stderr)
    assert outcome is expected
    assert text == ('{"events": []}' if expected is CallOutcome.OK else None)
