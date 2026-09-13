"""Summary-only diagnostic sharing for messaging adapters."""

from superforecasting_agent.application.diagnostics import diagnostic_payload


def share_debug_summary(*, log_lines: int = 200) -> str:
    """Upload one sanitized, versioned summary; never upload full conversation logs."""
    # Call-time access preserves the shared capture/upload owner and its test seams.
    from superforecasting_agent.runtime import debug

    debug._best_effort_sweep_expired_pastes()
    report = debug.collect_debug_report(
        log_lines=log_lines, dump_text=debug._capture_dump()
    )
    payload = diagnostic_payload(report, sanitize=debug._redact_log_text)
    url = debug.upload_to_pastebin(payload)
    debug._schedule_auto_delete([url])
    return url
