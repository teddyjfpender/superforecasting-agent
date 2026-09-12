"""Gateway RPCs for the voice family (+ insights.get) — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``voice.toggle`` / ``voice.record`` /
``voice.tts`` / ``voice.stop`` and the contiguous ``insights.get`` RPC moved here
here originally. Insights now shares query validation and reporting with command consumers.
The local ``rpc_validated`` / ``method`` decorators capture handlers
into ``_REGISTRARS``; ``server.py`` calls :func:`register` (at load AND on
``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract), replaying them
through the REAL ``server.rpc_validated`` / ``server.method`` so registration
lands in the same ``tui_gateway.server._methods`` dispatch dict — byte-identical.

Reached via the ``_core.`` call-time hop: the monkeypatched ``_emit`` / ``_get_db``
/ ``_store_session_toggle``, AND the mutable voice module state
``_voice_event_sid`` / ``_voice_sid_lock`` — because the STAYING helpers
``_voice_emit`` / ``_voice_session_key`` also read/lock them in core, both sides
must share the one live object (and ``voice.record``'s ``global`` write becomes a
``_core._voice_event_sid = …`` attribute assignment). The pure staying helpers
(``_voice_emit`` / ``_voice_flag`` / ``_voice_mode_enabled`` / ``_voice_record_key``
/ ``_voice_session_key`` / ``_voice_cfg_dict`` / ``_speak_with_status`` /
``_db_unavailable_error``) and ``_ok`` / ``_err`` / ``logger`` are imported bare.
"""
from __future__ import annotations

import threading  # noqa: F401  (voice.record spawns a recorder thread)

import tui_gateway.server as _core
from tui_gateway.server import (
    _db_unavailable_error,
    _err,
    _ok,
    _speak_with_status,
    _voice_cfg_dict,
    _voice_emit,
    _voice_flag,
    _voice_mode_enabled,
    _voice_record_key,
    _voice_session_key,
    logger,
)

_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def method(name: str):
    def _dec(fn):
        _REGISTRARS.append(("method", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved voice / insights handler into ``server._methods``."""
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]
@rpc_validated("voice.toggle")
def _(rid, params: dict) -> dict:
    """CLI parity for the ``/voice`` slash command.

    Subcommands:

    * ``status`` — report mode + TTS flags (default when action is unknown).
    * ``on`` / ``off`` — flip voice *mode* (the umbrella bit). Turning it
      off also tears down any active continuous recording loop. Does NOT
      start recording on its own; recording is driven by ``voice.record``
      (Ctrl+B) after mode is on, matching cli.py's enable/Ctrl+B split.
    * ``tts`` — toggle speech-output of agent replies. Requires mode on
      (mirrors CLI's _toggle_voice_tts guard).
    """
    action = params.get("action", "status")
    # Per-session: the voice mode/TTS flags belong to the session that owns the mic
    # (params.session_id, else the active voice-event sid), not the whole process — so a
    # second TUI session doesn't see this one's voice state.
    _vkey = _voice_session_key(params)

    if action == "status":
        # Mirror CLI's _show_voice_status: include STT/TTS provider
        # availability so the user can tell at a glance *why* voice mode
        # isn't working ("STT provider: MISSING ..." is the common case).
        # ``record_key`` mirrors the configured ``voice.record_key`` so the
        # TUI can both bind it (frontend ``isVoiceToggleKey``) and display
        # it in /voice status — previously the TUI hardcoded Ctrl+B and
        # ignored the config (#18994).
        payload: dict = {
            "enabled": _voice_flag(_vkey, "VOICE"),
            "record_key": _voice_record_key(),
            "tts": _voice_flag(_vkey, "VOICE_TTS"),
        }
        try:
            from tools.voice_mode import check_voice_requirements

            reqs = check_voice_requirements()
            payload["available"] = bool(reqs.get("available"))
            payload["audio_available"] = bool(reqs.get("audio_available"))
            payload["stt_available"] = bool(reqs.get("stt_available"))
            payload["details"] = reqs.get("details") or ""
        except Exception as e:
            # check_voice_requirements pulls optional transcription deps —
            # swallow so /voice status always returns something useful.
            logger.warning("voice.toggle status: requirements probe failed: %s", e)

        return _ok(rid, payload)

    if action in {"on", "off"}:
        enabled = action == "on"
        # Runtime-only flag (CLI parity) — no _write_config_key, so the
        # next TUI launch starts with voice OFF instead of auto-REC from a
        # persisted stale toggle. Per-session store + os.environ fallback.
        _core._store_session_toggle(_vkey, "VOICE", "1" if enabled else "0")

        if not enabled:
            # Disabling the mode must tear the continuous loop down; the
            # loop holds the microphone and would otherwise keep running.
            try:
                from superforecasting_agent.runtime.voice import stop_continuous

                stop_continuous()
            except ImportError:
                pass
            except Exception as e:
                logger.warning("voice: stop_continuous failed during toggle off: %s", e)

        return _ok(
            rid,
            {
                "enabled": enabled,
                "record_key": _voice_record_key(),
                "tts": _voice_flag(_vkey, "VOICE_TTS"),
            },
        )

    if action == "tts":
        if not _voice_flag(_vkey, "VOICE"):
            return _err(rid, 4014, "enable voice mode first: /voice on")
        new_value = not _voice_flag(_vkey, "VOICE_TTS")
        # Runtime-only flag (CLI parity) — see voice.toggle on/off above.
        _core._store_session_toggle(_vkey, "VOICE_TTS", "1" if new_value else "0")
        # Include ``record_key`` on every branch so a /voice tts toggle
        # doesn't reset the TUI's cached shortcut to the default when a
        # user has a custom binding configured (Copilot review, round 2
        # on #19835). Keeps parity with the status/on/off branches above.
        return _ok(
            rid,
            {
                "enabled": True,
                "record_key": _voice_record_key(),
                "tts": new_value,
            },
        )

    return _err(rid, 4013, f"unknown voice action: {action}")


@rpc_validated("voice.record")
def _(rid, params: dict) -> dict:
    """VAD-bounded push-to-talk capture, CLI-parity.

    ``start`` begins one VAD-bounded capture and emits ``voice.transcript``
    after silence stops the recorder. ``stop`` forces transcription of the
    active buffer, matching classic CLI push-to-talk. The voice wrapper retains
    no-speech counts across single-shot starts, so three consecutive silent
    captures emit ``voice.transcript`` with ``no_speech_limit=True``.
    """
    action = params.get("action", "start")

    if action not in {"start", "stop"}:
        return _err(rid, 4019, f"unknown voice action: {action}")

    try:
        if action == "start":
            if not _voice_mode_enabled():
                return _err(rid, 4015, "voice mode is off — enable with /voice on")

            # Auto-install the microphone capture libs (sounddevice/numpy) on
            # first record so the user never has to pip-install by hand.
            try:
                from tools.voice_mode import ensure_audio_deps

                ensure_audio_deps()
            except Exception as e:
                logger.info("voice.record: ensure_audio_deps skipped: %s", e)

            with _core._voice_sid_lock:
                _core._voice_event_sid = params.get("session_id") or _core._voice_event_sid

            from superforecasting_agent.runtime.voice import start_continuous

            # Shape-safe lookups: malformed ``voice:`` YAML (bool/scalar/list)
            # must not crash /voice with a 5025 — fall back to VAD defaults.
            #
            # Exclude ``bool`` from the numeric check since Python's bool is
            # a subclass of int — a hand-edit like ``silence_threshold: true``
            # would otherwise forward as ``1`` instead of falling back to
            # the documented 200 / 3.0 defaults (Copilot round-12 on #19835).
            voice_cfg = _voice_cfg_dict()
            threshold = voice_cfg.get("silence_threshold")
            duration = voice_cfg.get("silence_duration")
            safe_threshold = (
                threshold
                if isinstance(threshold, (int, float))
                and not isinstance(threshold, bool)
                else 200
            )
            safe_duration = (
                duration
                if isinstance(duration, (int, float)) and not isinstance(duration, bool)
                else 3.0
            )
            started = start_continuous(
                on_transcript=lambda t: _voice_emit("voice.transcript", {"text": t}),
                on_status=lambda s: _voice_emit("voice.status", {"state": s}),
                on_silent_limit=lambda: _voice_emit(
                    "voice.transcript", {"no_speech_limit": True}
                ),
                silence_threshold=safe_threshold,
                silence_duration=safe_duration,
                auto_restart=False,
            )
            if started is False:
                return _ok(rid, {"status": "busy"})
            return _ok(rid, {"status": "recording"})

        # action == "stop"
        with _core._voice_sid_lock:
            _core._voice_event_sid = params.get("session_id") or _core._voice_event_sid

        from superforecasting_agent.runtime.voice import stop_continuous

        stop_continuous(force_transcribe=True)
        return _ok(rid, {"status": "stopped"})
    except ImportError:
        return _err(
            rid, 5025, "voice module not available — install audio dependencies"
        )
    except Exception as e:
        return _err(rid, 5025, str(e))


@method("voice.tts")
def _(rid, params: dict) -> dict:
    text = params.get("text", "")
    if not text:
        return _err(rid, 4020, "text required")
    try:
        from superforecasting_agent.runtime.voice import speak_text  # noqa: F401 — availability check

        sid = _voice_session_key(params) or params.get("session_id") or _core._voice_event_sid
        threading.Thread(target=_speak_with_status, args=(text, sid or ""), daemon=True).start()
        return _ok(rid, {"status": "speaking"})
    except ImportError:
        return _err(rid, 5026, "voice module not available")
    except Exception as e:
        return _err(rid, 5026, str(e))


@rpc_validated("voice.stop")
def _(rid, params: dict) -> dict:
    """Stop any in-flight TTS playback immediately (the stop/skip hotkey). Terminates the
    audio player and clears the speaking indicator; safe to call when nothing is playing."""
    stopped = False
    try:
        from tools.voice_mode import stop_playback

        stop_playback()
        stopped = True
    except Exception as e:
        logger.debug("voice.stop: %s", e)
    sid = params.get("session_id") or _core._voice_event_sid
    if sid:
        try:
            _core._emit("voice.status", sid, {"state": "idle"})
        except Exception:
            pass
    return _ok(rid, {"stopped": stopped})


# ── Methods: insights ────────────────────────────────────────────────


@method("insights.get")
def _(rid, params: dict) -> dict:
    from agent.insights import InsightsEngine
    from superforecasting_agent.application.insights import InsightsQuery

    try:
        query = InsightsQuery(params.get("days", 30), params.get("source"))
    except ValueError as exc:
        return _err(rid, 4004, str(exc))
    db = _core._get_db()
    if db is None:
        return _db_unavailable_error(rid, code=5017)
    try:
        overview = InsightsEngine(db).generate(
            days=query.days, source=query.source,
        )["overview"]
        return _ok(
            rid,
            {
                "days": query.days,
                "sessions": overview.get("total_sessions", 0),
                "messages": overview.get("total_messages", 0),
            },
        )
    except Exception as e:
        return _err(rid, 5017, str(e))
