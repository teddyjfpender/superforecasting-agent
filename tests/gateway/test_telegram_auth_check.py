"""Tests for the Telegram adapter early authorization check.

Ports upstream security fix #40863: an unauthorized Telegram sender must be
rejected BEFORE any text batching, event construction, or response generation
occurs, so a removed/blocked user cannot inject prompt content into the agent
path or the observed transcript.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform, PlatformConfig


def _make_adapter(allow_from=None, callback_auth=None, **extra_overrides):
    from gateway.platforms.telegram import TelegramAdapter

    extra = {}
    if allow_from is not None:
        extra["allow_from"] = allow_from
    extra.update(extra_overrides)

    adapter = object.__new__(TelegramAdapter)
    adapter._platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="fake-token", extra=extra)
    adapter._bot = SimpleNamespace(id=999, username="test_bot")
    adapter._message_handler = AsyncMock()
    adapter.handle_message = AsyncMock()
    adapter._pending_text_batches = {}
    adapter._pending_text_batch_tasks = {}
    adapter._text_batch_delay_seconds = 0.01
    adapter._text_batch_split_delay_seconds = 0.01
    adapter._active_sessions = {}
    adapter._pending_messages = {}
    # Downstream stubs so the authorized path doesn't touch real Telegram I/O.
    adapter._should_process_message = lambda *a, **kw: True
    adapter._ensure_forum_commands = AsyncMock()
    adapter._clean_bot_trigger_text = lambda text: text
    adapter._enqueue_text_event = lambda event: None
    if callback_auth is not None:
        adapter._is_callback_user_authorized = callback_auth
    return adapter


def _make_message(text="hello", *, from_user_id=111, chat_id=-100, chat_type="group"):
    return SimpleNamespace(
        message_id=42,
        text=text,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=SimpleNamespace(id=chat_id, type=chat_type, title="Test", is_forum=False),
        from_user=SimpleNamespace(id=from_user_id, full_name="Test User", first_name="Test", username="tester"),
        sender_chat=None,
        reply_to_message=None,
        date=None,
        location=None,
        photo=None,
        video=None,
        audio=None,
        voice=None,
        document=None,
        sticker=None,
        media_group_id=None,
    )


@pytest.mark.asyncio
async def test_unauthorized_user_blocked_before_event_building():
    """Unauthorized user's text must be blocked before _build_message_event."""
    adapter = _make_adapter(allow_from=["222"])  # Only user 222 allowed

    def boom(*_a, **_kw):
        raise AssertionError("build_message_event called for unauthorized user")

    adapter._build_message_event = boom

    update = SimpleNamespace(
        update_id=1,
        message=_make_message(from_user_id=111),  # 111 NOT in allow_from
        effective_message=None,
    )

    await adapter._handle_text_message(update, SimpleNamespace())  # must not raise


@pytest.mark.asyncio
async def test_authorized_user_processed_normally():
    """Authorized user's message passes the auth check and builds an event."""
    adapter = _make_adapter(allow_from=["111"])

    built = []
    adapter._build_message_event = lambda msg, mtype, **kw: built.append(mtype) or SimpleNamespace(text="hello")

    update = SimpleNamespace(
        update_id=1,
        message=_make_message(from_user_id=111),
        effective_message=None,
    )

    await adapter._handle_text_message(update, SimpleNamespace())

    assert built, "build_message_event should be called for authorized user"


@pytest.mark.asyncio
async def test_channel_post_passes_auth():
    """Messages with no from_user (channel posts) pass user-level auth."""
    adapter = _make_adapter(allow_from=["111"])

    built = []
    adapter._build_message_event = lambda msg, mtype, **kw: built.append(mtype) or SimpleNamespace(text="hi")

    msg = _make_message()
    msg.from_user = None  # Channel post has no sender

    update = SimpleNamespace(update_id=1, message=msg, effective_message=None)

    await adapter._handle_text_message(update, SimpleNamespace())

    assert built, "channel posts should pass user-level auth"


@pytest.mark.asyncio
async def test_command_from_unauthorized_user_blocked():
    """Commands from unauthorized users are blocked before dispatch."""
    adapter = _make_adapter(allow_from=["222"])

    def boom(*_a, **_kw):
        raise AssertionError("build_message_event called for unauthorized command")

    adapter._build_message_event = boom

    update = SimpleNamespace(
        update_id=1,
        message=_make_message(text="/start", from_user_id=111),
        effective_message=None,
    )

    await adapter._handle_command(update, SimpleNamespace())

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_location_from_unauthorized_user_blocked():
    """Location messages from unauthorized users are blocked."""
    adapter = _make_adapter(allow_from=["222"])

    def boom(*_a, **_kw):
        raise AssertionError("build_message_event called for unauthorized location")

    adapter._build_message_event = boom

    msg = _make_message(from_user_id=111)
    msg.text = None
    msg.venue = None
    msg.location = SimpleNamespace(latitude=53.3498, longitude=-6.2603)

    update = SimpleNamespace(update_id=1, message=msg, effective_message=None)

    await adapter._handle_location_message(update, SimpleNamespace())

    adapter.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_media_from_removed_user_blocked_before_event_building(monkeypatch):
    """Removed users must not inject prompt-bearing documents via media handlers."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "222")
    adapter = _make_adapter()

    def boom(*_a, **_kw):
        raise AssertionError("media handler built an event for an unauthorized user")

    adapter._build_message_event = boom
    document = SimpleNamespace(
        file_name="payload.txt",
        mime_type="text/plain",
        file_size=42,
        get_file=AsyncMock(side_effect=AssertionError("unauthorized document was downloaded")),
    )
    msg = _make_message(text=None, from_user_id=111, chat_id=111, chat_type="private")
    msg.caption = "please process this caption"
    msg.document = document

    update = SimpleNamespace(update_id=1, message=msg, effective_message=None)

    await adapter._handle_media_message(update, SimpleNamespace())

    adapter.handle_message.assert_not_awaited()
    document.get_file.assert_not_awaited()


def test_is_user_authorized_from_message_allow_from():
    """_is_user_authorized_from_message respects adapter-level allow_from."""
    adapter = _make_adapter(allow_from=["111", "222"])

    assert adapter._is_user_authorized_from_message(_make_message(from_user_id=111)) is True
    assert adapter._is_user_authorized_from_message(_make_message(from_user_id=333)) is False


def test_is_user_authorized_from_message_wildcard():
    """_is_user_authorized_from_message accepts wildcard '*'."""
    adapter = _make_adapter(allow_from=["*"])
    assert adapter._is_user_authorized_from_message(_make_message(from_user_id=999)) is True


def test_is_user_authorized_from_message_no_from_user():
    """Messages without from_user (and no sender_chat) pass user-level auth."""
    adapter = _make_adapter(allow_from=["111"])
    msg = _make_message()
    msg.from_user = None
    assert adapter._is_user_authorized_from_message(msg) is True


def test_is_user_authorized_from_message_callback_override():
    """An instance-level callback override decides authorization in tests."""
    adapter = _make_adapter(callback_auth=lambda uid, **_kw: uid == "555")

    assert adapter._is_user_authorized_from_message(_make_message(from_user_id=555)) is True
    assert adapter._is_user_authorized_from_message(_make_message(from_user_id=666)) is False


def test_unknown_dm_with_no_allowlist_passes_to_pairing(monkeypatch):
    """Unknown DMs must still reach the pairing flow when no allowlist exists."""
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)

    adapter = _make_adapter()
    msg = _make_message(from_user_id=111, chat_id=111, chat_type="private")

    assert adapter._is_user_authorized_from_message(msg) is True


def test_runner_auth_gets_group_user_allowlist_context(monkeypatch):
    """Group user allowlists need a group-shaped source, not a DM-shaped one."""
    monkeypatch.setenv("TELEGRAM_GROUP_ALLOWED_USERS", "111")
    seen_sources = []

    class Runner:
        def _is_user_authorized(self, source):
            seen_sources.append(source)
            return source.chat_type == "group" and source.chat_id == "-100" and source.user_id == "111"

        async def handle(self, event):
            return None

    runner = Runner()
    adapter = _make_adapter()
    adapter._message_handler = runner.handle
    msg = _make_message(from_user_id=111, chat_id=-100, chat_type="group")

    assert adapter._is_user_authorized_from_message(msg) is True
    assert seen_sources
    assert seen_sources[0].chat_type == "group"
    assert seen_sources[0].chat_id == "-100"


def test_removed_dm_user_blocked_before_pairing_when_allowlist_exists(monkeypatch):
    """A user removed from TELEGRAM_ALLOWED_USERS is blocked at intake."""
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "222")
    adapter = _make_adapter()
    msg = _make_message(from_user_id=111, chat_id=111, chat_type="private")

    assert adapter._is_user_authorized_from_message(msg) is False


def test_group_only_allowlist_does_not_block_unknown_dm_before_pairing(monkeypatch):
    """A group-scoped allowlist alone must not default-deny an unknown DM.

    Regression guard: with ONLY TELEGRAM_GROUP_ALLOWED_* set, an unknown DM user
    must pass the intake prefilter through to the DM pairing flow. Gating a DM on
    a group-only allowlist (as the unscoped _telegram_auth_env_configured did)
    default-denies the unknown user at intake before pairing can run.
    """
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TELEGRAM_GROUP_ALLOWED_USERS", "222")
    monkeypatch.setenv("TELEGRAM_GROUP_ALLOWED_CHATS", "-100")

    # A runner exists (so the env-config gate is consulted) but must NOT be
    # reached for an unknown DM when only the group allowlist is configured.
    class Runner:
        def _is_user_authorized(self, source):
            raise AssertionError(
                "runner auth must not gate an unknown DM on a group-only allowlist"
            )

        async def handle(self, event):
            return None

    adapter = _make_adapter()
    adapter._message_handler = Runner().handle
    msg = _make_message(from_user_id=111, chat_id=111, chat_type="private")

    assert adapter._is_user_authorized_from_message(msg) is True


def test_dm_allowlist_still_rejects_unknown_dm(monkeypatch):
    """A DM-scoped allowlist still default-denies an unknown DM at intake."""
    for key in (
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "222")

    class Runner:
        def _is_user_authorized(self, source):
            allowed = {"222"}
            return source.user_id in allowed

        async def handle(self, event):
            return None

    adapter = _make_adapter()
    adapter._message_handler = Runner().handle
    msg = _make_message(from_user_id=111, chat_id=111, chat_type="private")

    assert adapter._is_user_authorized_from_message(msg) is False


def test_group_message_still_gates_on_group_allowlist(monkeypatch):
    """Group messages still gate on the group allowlist (unchanged behavior)."""
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TELEGRAM_GROUP_ALLOWED_USERS", "222")

    class Runner:
        def _is_user_authorized(self, source):
            allowed = {"222"}
            return source.chat_type == "group" and source.user_id in allowed

        async def handle(self, event):
            return None

    runner = Runner()
    adapter = _make_adapter()
    adapter._message_handler = runner.handle

    # Allowed group user passes; unknown group user is rejected.
    assert (
        adapter._is_user_authorized_from_message(
            _make_message(from_user_id=222, chat_id=-100, chat_type="group")
        )
        is True
    )
    assert (
        adapter._is_user_authorized_from_message(
            _make_message(from_user_id=111, chat_id=-100, chat_type="group")
        )
        is False
    )


def test_class_callback_method_not_used_as_message_shortcut(monkeypatch):
    """The real _is_callback_user_authorized class method must not gate messages.

    With no allowlist configured and no runner, an unknown DM must still pass to
    the pairing flow — the class-level callback method (which fails closed) must
    not be treated as a user-id-only shortcut for real messages.
    """
    for key in (
        "TELEGRAM_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_USERS",
        "TELEGRAM_GROUP_ALLOWED_CHATS",
        "TELEGRAM_ALLOW_ALL_USERS",
        "GATEWAY_ALLOWED_USERS",
        "GATEWAY_ALLOW_ALL_USERS",
    ):
        monkeypatch.delenv(key, raising=False)

    adapter = _make_adapter()
    adapter._message_handler = None  # no runner
    msg = _make_message(from_user_id=111, chat_id=111, chat_type="private")

    assert adapter._is_user_authorized_from_message(msg) is True
