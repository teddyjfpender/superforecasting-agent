"""Tests for tui_gateway.render — rendering bridge fallback behavior."""

from unittest.mock import MagicMock, patch

from tui_gateway.render import make_stream_renderer, render_diff, render_message


def _stub_rich(mock_mod):
    return patch.dict("sys.modules", {"agent.rich_output": mock_mod})


def _no_rich():
    return patch.dict("sys.modules", {"agent.rich_output": None})


# ── render_message ───────────────────────────────────────────────────


def test_render_message_none_without_module():
    with _no_rich():
        assert render_message("hello") is None


def test_render_message_formatted():
    mod = MagicMock()
    mod.format_response.return_value = "<b>hi</b>"

    with _stub_rich(mod):
        assert render_message("hi", 100) == "<b>hi</b>"


def test_render_message_type_error_fallback():
    mod = MagicMock()
    mod.format_response.side_effect = [TypeError, "fallback"]

    with _stub_rich(mod):
        assert render_message("hi") == "fallback"


def test_render_message_exception_returns_none():
    mod = MagicMock()
    mod.format_response.side_effect = RuntimeError

    with _stub_rich(mod):
        assert render_message("hi") is None


# ── render_diff / make_stream_renderer ───────────────────────────────


def test_render_diff_none_without_module():
    with _no_rich():
        assert render_diff("+line") is None


def test_stream_renderer_none_without_module():
    with _no_rich():
        assert make_stream_renderer() is None


def test_stream_renderer_returns_instance():
    renderer = MagicMock()
    mod = MagicMock()
    mod.StreamingRenderer.return_value = renderer

    with _stub_rich(mod):
        assert make_stream_renderer(120) is renderer


# ── defensive fallback: drifted-signature retry must not crash ─────────


def test_render_message_double_type_error_degrades_to_plain_text():
    # Both the kw form and the positional retry raise TypeError (signature
    # drifted past both call shapes) — must degrade to the input text, not
    # propagate and crash the gateway.
    mod = MagicMock()
    mod.format_response.side_effect = TypeError

    with _stub_rich(mod):
        assert render_message("plain payload", 100) == "plain payload"


def test_render_diff_double_type_error_degrades_to_plain_text():
    mod = MagicMock()
    mod.render_diff.side_effect = TypeError

    with _stub_rich(mod):
        assert render_diff("+added", 100) == "+added"


def test_stream_renderer_double_type_error_returns_none():
    mod = MagicMock()
    mod.StreamingRenderer.side_effect = TypeError

    with _stub_rich(mod):
        assert make_stream_renderer(120) is None
