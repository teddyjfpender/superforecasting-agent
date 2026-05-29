"""Shared threat-pattern library for context-window security scanning.

Single source of truth for prompt-injection / promptware / exfiltration
patterns used across the context-assembly scanners (``agent/prompt_builder.py``,
``tools/memory_tool.py``) and the tool-result delimiter system in
``agent/tool_dispatch_helpers.py``.

Ported from upstream hermes-agent PR #32269 (promptware defense). Paths that
referenced the legacy ``~/.hermes`` home are widened to also match this fork's
``~/.superforecasting-agent`` home.

Pattern philosophy
------------------
Patterns are organized by ATTACK CLASS, not by source file. Each is a
``(regex, pattern_id, scope)`` tuple where ``scope`` controls which scanners
use it:

- ``"all"``     — applied everywhere (classic injection, exfiltration)
- ``"context"`` — adds promptware / C2 / role-play (context files, memory,
                  tool results; broader detection)
- ``"strict"``  — adds persistence / SSH-backdoor (memory writes, skill
                  installs only — aggressive checks acceptable for
                  user-curated content but too noisy for tool results)

New patterns anchor on C2-specific vocabulary or unambiguous attack behavior,
NOT on bossy English ("you must X" alone is too common to flag). Multi-word
bypass is prevented with ``(?:\\w+\\s+)*`` between key tokens.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# Each entry: (regex, pattern_id, scope), scope in {"all", "context", "strict"}
_PATTERNS: List[Tuple[str, str, str]] = [
    # ── Classic prompt injection (applies everywhere) ────────────────
    (r'ignore\s+(?:\w+\s+)*(previous|all|above|prior)\s+(?:\w+\s+)*instructions', "prompt_injection", "all"),
    (r'system\s+prompt\s+override', "sys_prompt_override", "all"),
    (r'disregard\s+(?:\w+\s+)*(your|all|any)\s+(?:\w+\s+)*(instructions|rules|guidelines)', "disregard_rules", "all"),
    (r'act\s+as\s+(if|though)\s+(?:\w+\s+)*you\s+(?:\w+\s+)*(have\s+no|don\'t\s+have)\s+(?:\w+\s+)*(restrictions|limits|rules)', "bypass_restrictions", "all"),
    (r'<!--[^>]*(?:ignore|override|system|secret|hidden)[^>]*-->', "html_comment_injection", "all"),
    (r'<\s*div\s+style\s*=\s*["\'][\s\S]*?display\s*:\s*none', "hidden_div", "all"),
    (r'translate\s+.*\s+into\s+.*\s+and\s+(execute|run|eval)', "translate_execute", "all"),
    (r'do\s+not\s+(?:\w+\s+)*tell\s+(?:\w+\s+)*the\s+user', "deception_hide", "all"),

    # ── Role-play / identity hijack (context scope) ──────────────────
    (r'you\s+are\s+(?:\w+\s+)*now\s+(?:a|an|the)\s+', "role_hijack", "context"),
    (r'pretend\s+(?:\w+\s+)*(you\s+are|to\s+be)\s+', "role_pretend", "context"),
    (r'output\s+(?:\w+\s+)*(system|initial)\s+prompt', "leak_system_prompt", "context"),
    (r'(respond|answer|reply)\s+without\s+(?:\w+\s+)*(restrictions|limitations|filters|safety)', "remove_filters", "context"),
    (r'you\s+have\s+been\s+(?:\w+\s+)*(updated|upgraded|patched)\s+to', "fake_update", "context"),
    (r'\bname\s+yourself\s+\w+', "identity_override", "context"),

    # ── C2 / Brainworm-style promptware (context scope) ──────────────
    (r'register\s+(as\s+)?a?\s*node', "c2_node_registration", "context"),
    (r'(heartbeat|beacon|check[\s\-]?in)\s+(to|with)\s+', "c2_heartbeat", "context"),
    (r'pull\s+(down\s+)?(?:new\s+)?task(?:ing|s)?\b', "c2_task_pull", "context"),
    (r'connect\s+to\s+the\s+network\b', "c2_network_connect", "context"),
    (r'you\s+must\s+(?:\w+\s+){0,3}(register|connect|report|beacon)\b', "forced_action", "context"),
    (r'only\s+use\s+one[\s\-]?liners?\b', "anti_forensic_oneliner", "context"),
    (r'never\s+(?:\w+\s+)*(?:create|write)\s+(?:\w+\s+)*(?:script|file)\s+(?:\w+\s+)*disk', "anti_forensic_disk", "context"),
    # Env-var unset targeting known agent runtimes. ``AGENT`` covers this
    # fork's SUPERFORECASTING_AGENT_* vars (substring match).
    (r'unset\s+\w*(?:CLAUDE|CODEX|HERMES|AGENT|OPENAI|ANTHROPIC)\w*', "env_var_unset_agent", "context"),

    # ── Known C2 / red-team framework names ──────────────────────────
    (r'\b(?:praxis|cobalt\s*strike|sliver|havoc|mythic|metasploit|brainworm)\b', "known_c2_framework", "context"),
    (r'\bc2\s+(?:server|channel|infrastructure|beacon)\b', "c2_explicit", "context"),
    (r'\bcommand\s+and\s+control\b', "c2_explicit_long", "context"),

    # ── Exfiltration via curl/wget/cat with secrets ──────────────────
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl", "all"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget", "all"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets", "all"),
    (r'(send|post|upload|transmit)\s+.*\s+(to|at)\s+https?://', "send_to_url", "strict"),
    (r'(include|output|print|share)\s+(?:\w+\s+)*(conversation|chat\s+history|previous\s+messages|full\s+context|entire\s+context)', "context_exfil", "strict"),

    # ── Persistence / SSH backdoor (strict scope — memory + skills) ──
    (r'authorized_keys', "ssh_backdoor", "strict"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access", "strict"),
    # Both this fork's home and the legacy ~/.hermes home.
    (r'(?:\$HOME|\~)/\.(?:hermes|superforecasting-agent)/\.env', "agent_env", "strict"),
    (r'(update|modify|edit|write|change|append|add\s+to)\s+.*(?:AGENTS\.md|CLAUDE\.md|\.cursorrules|\.clinerules)', "agent_config_mod", "strict"),
    (r'(update|modify|edit|write|change|append|add\s+to)\s+.*\.(?:hermes|superforecasting-agent)/(config\.yaml|SOUL\.md)', "agent_config_home_mod", "strict"),

    # ── Hardcoded secrets ────────────────────────────────────────────
    (r'(?:api[_-]?key|token|secret|password)\s*[=:]\s*["\'][A-Za-z0-9+/=_-]{20,}', "hardcoded_secret", "strict"),
]

# Invisible / bidirectional unicode used in injection attacks. Aligned with
# skills_guard.py — directional isolates (U+2066-U+2069) and invisible math
# operators (U+2062-U+2064) are real attack tools.
INVISIBLE_CHARS = frozenset({
    "\u200b",  # zero-width space
    "\u200c",  # zero-width non-joiner
    "\u200d",  # zero-width joiner
    "\u2060",  # word joiner
    "\u2062",  # invisible times
    "\u2063",  # invisible separator
    "\u2064",  # invisible plus
    "\ufeff",  # zero-width no-break space (BOM)
    "\u202a",  # left-to-right embedding
    "\u202b",  # right-to-left embedding
    "\u202c",  # pop directional formatting
    "\u202d",  # left-to-right override
    "\u202e",  # right-to-left override
    "\u2066",  # left-to-right isolate
    "\u2067",  # right-to-left isolate
    "\u2068",  # first strong isolate
    "\u2069",  # pop directional isolate
})

# Compiled pattern sets, indexed by scope; compiled once at import time.
_COMPILED: dict[str, List[Tuple[re.Pattern, str]]] = {}


def _compile() -> None:
    """Compile pattern sets per scope.

    scope="all" lands in every set; scope="context" lands in context+strict;
    scope="strict" lands in strict only.
    """
    global _COMPILED
    if _COMPILED:
        return

    all_patterns: List[Tuple[re.Pattern, str]] = []
    context_patterns: List[Tuple[re.Pattern, str]] = []
    strict_patterns: List[Tuple[re.Pattern, str]] = []

    for pattern, pid, scope in _PATTERNS:
        entry = (re.compile(pattern, re.IGNORECASE), pid)
        if scope == "all":
            all_patterns.append(entry)
            context_patterns.append(entry)
            strict_patterns.append(entry)
        elif scope == "context":
            context_patterns.append(entry)
            strict_patterns.append(entry)
        elif scope == "strict":
            strict_patterns.append(entry)
        else:
            raise ValueError(f"threat_patterns: unknown scope {scope!r} for pattern {pid!r}")

    _COMPILED = {"all": all_patterns, "context": context_patterns, "strict": strict_patterns}


_compile()


def scan_for_threats(content: str, scope: str = "context") -> List[str]:
    """Return matched pattern IDs in ``content`` at the given scope.

    Also checks for invisible unicode (returned as ``invisible_unicode_U+XXXX``
    so the caller can surface the offending codepoint).
    """
    if not content:
        return []

    findings: List[str] = []

    for ch in (set(content) & INVISIBLE_CHARS):
        findings.append(f"invisible_unicode_U+{ord(ch):04X}")

    patterns = _COMPILED.get(scope)
    if patterns is None:
        raise ValueError(f"scan_for_threats: unknown scope {scope!r}")
    for compiled, pid in patterns:
        if compiled.search(content):
            findings.append(pid)

    return findings


def first_threat_message(content: str, scope: str = "strict") -> Optional[str]:
    """Return a human-readable error for the first threat found, or None."""
    findings = scan_for_threats(content, scope=scope)
    if not findings:
        return None
    pid = findings[0]
    if pid.startswith("invisible_unicode_"):
        codepoint = pid.replace("invisible_unicode_", "")
        return f"Blocked: content contains invisible unicode character {codepoint} (possible injection)."
    return (
        f"Blocked: content matches threat pattern '{pid}'. Content is injected "
        f"into the system prompt and must not contain injection or "
        f"exfiltration payloads."
    )


__all__ = [
    "INVISIBLE_CHARS",
    "scan_for_threats",
    "first_threat_message",
]
