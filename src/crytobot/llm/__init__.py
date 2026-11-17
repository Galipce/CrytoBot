"""LLM'e tek erişim noktası: sahibin Claude aboneliğiyle `claude -p` alt süreci (spec 0051).

Ayrı ücretli API ve API anahtarı kullanılmaz (ADR 0003). Her çağrı yalıtılmış ayrı bir süreçtir:
araçsız, ayarsız, oturumsuz, boş bir çalışma klasöründe; zaman aşımında ağacıyla sonlanır. Modül
hiçbir proje modülünü import etmez (R-3j); yanıtı yorumlamaz — doğrulama çağıranındır.
"""

from crytobot.llm._claude import (
    NO_SESSION_MARKS,
    OUTPUT_LIMIT,
    QUOTA_MARKS,
    CallOutcome,
    ClaudeReply,
    ClaudeRequest,
    call_claude,
    classify,
    claude_argv,
    claude_env,
    kill_tree,
)
from crytobot.llm._workdir import PREFIX as WORKDIR_PREFIX

__all__: list[str] = [
    "NO_SESSION_MARKS",
    "OUTPUT_LIMIT",
    "QUOTA_MARKS",
    "WORKDIR_PREFIX",
    "CallOutcome",
    "ClaudeReply",
    "ClaudeRequest",
    "call_claude",
    "classify",
    "claude_argv",
    "claude_env",
    "kill_tree",
]
