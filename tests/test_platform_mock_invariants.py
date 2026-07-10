"""Meta-tests pinning the platform-library test-double contract.

These lock in the invariants whose absence caused the long-running class of
order-dependent, cross-file failures documented in ``.githooks/skips.log``
(telegram group chats mis-classified as "dm"; discord ``AllowedMentions``
coming back a bare ``MagicMock``). They fail loudly the moment a future edit
re-introduces a divergent or incomplete platform mock.

The mock-content checks run inside ``_fresh_modules`` — they snapshot the
relevant ``sys.modules`` entries, force a clean install, assert, then restore.
That keeps them deterministic under ``pytest-xdist``, where dozens of gateway
telegram test files install their own module-level mocks in an order this
process does not control.

See ``tests/_platform_mocks.py`` for the full rationale.
"""

from __future__ import annotations

import contextlib
import sys

from tests._platform_mocks import (
    install_all_platform_mocks,
    install_discord_mock,
    install_slack_mock,
    install_telegram_mock,
)


@contextlib.contextmanager
def _fresh_modules(*names):
    """Remove the given sys.modules entries for the block, then restore them.

    Lets a test force a from-scratch installer run and assert on the result
    without depending on — or corrupting — whatever ambient mock another test
    left behind on this worker.
    """
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        sys.modules.pop(name, None)
    try:
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


_TELEGRAM_NAMES = (
    "telegram",
    "telegram.constants",
    "telegram.ext",
    "telegram.ext.filters",
    "telegram.request",
    "telegram.error",
)
_DISCORD_NAMES = ("discord", "discord.ext", "discord.ext.commands", "discord.opus")
_SLACK_NAMES = (
    "slack_bolt",
    "slack_bolt.async_app",
    "slack_bolt.adapter",
    "slack_bolt.adapter.socket_mode",
    "slack_bolt.adapter.socket_mode.async_handler",
    "slack_sdk",
    "slack_sdk.web",
    "slack_sdk.web.async_client",
)


def test_telegram_chattype_values_live_on_the_path_the_adapter_reads():
    """``from telegram.constants import ChatType`` must yield real strings.

    The adapter classifies chats via ``str(chat.type).lower() == "supergroup"``.
    Because ``mod`` is registered as ``telegram.constants``, that resolves to
    ``mod.ChatType`` — NOT ``mod.constants.ChatType``. Setting the strings on
    the wrong path is a silent no-op that made every group chat classify as
    "dm" once this mock won the adapter-import race.
    """
    with _fresh_modules(*_TELEGRAM_NAMES):
        install_telegram_mock()
        chat_type = sys.modules["telegram.constants"].ChatType
        assert chat_type.PRIVATE == "private"
        assert chat_type.GROUP == "group"
        assert chat_type.SUPERGROUP == "supergroup"
        assert chat_type.CHANNEL == "channel"


def test_telegram_constants_submodules_share_the_canonical_object():
    """All telegram submodule names resolve to the one canonical mock object.

    ``from telegram.ext import filters`` and ``from telegram.constants import
    ChatType`` must read the same object the adapter's ``from telegram import
    ...`` bound, or the flat-attribute resolution the adapter relies on breaks.
    """
    with _fresh_modules(*_TELEGRAM_NAMES):
        install_telegram_mock()
        canonical = sys.modules["telegram"]
        for name in ("telegram.constants", "telegram.ext", "telegram.request"):
            assert sys.modules[name] is canonical


def test_discord_mock_ships_allowed_mentions_and_app_command():
    """The discord double must expose a real ``AllowedMentions`` + ``Command``.

    ``test_discord_connect`` asserts ``am.everyone is False``; that only holds
    when ``discord.AllowedMentions`` is a real class rather than a bare
    ``MagicMock`` auto-attribute. Slash-command auto-registration needs
    ``app_commands.Command`` / ``Group``.
    """
    with _fresh_modules(*_DISCORD_NAMES):
        install_discord_mock()
        discord_mod = sys.modules["discord"]
        am = discord_mod.AllowedMentions(everyone=False, roles=False, users=True)
        assert am.everyone is False
        assert am.users is True
        assert discord_mod.app_commands.Command is not None
        assert discord_mod.app_commands.Group is not None


def test_discord_messagetype_stays_open_for_arbitrary_members():
    """``MessageType`` must not be pinned to a fixed member set.

    Gateway tests reference arbitrary members (``new_member``, ``pins_add``,
    ``thread_rename`` …). Pinning ``MessageType`` to a ``SimpleNamespace`` with
    only ``default``/``reply`` would raise AttributeError on the rest — the
    regression that briefly broke test_discord_system_messages.
    """
    with _fresh_modules(*_DISCORD_NAMES):
        install_discord_mock()
        message_type = sys.modules["discord"].MessageType
        # Arbitrary members must resolve (to distinct auto-children).
        assert message_type.new_member is not message_type.pins_add
        assert message_type.default is not message_type.thread_rename


def test_installers_are_idempotent_single_canonical_object():
    """Repeated installs must preserve one object per library.

    The adapters freeze their ``import telegram`` / ``import discord`` /
    ``import slack_bolt`` bindings at first import. If a later installer
    replaced the object, the adapter would keep referencing the old one while
    tests mutated the new one — the exact two-objects-one-binding split that
    made ``AllowedMentions`` patches never reach the adapter.
    """
    with _fresh_modules(*_TELEGRAM_NAMES, *_DISCORD_NAMES, *_SLACK_NAMES):
        install_all_platform_mocks()
        telegram_obj = sys.modules["telegram"]
        discord_obj = sys.modules["discord"]
        slack_obj = sys.modules["slack_bolt"]

        install_telegram_mock()
        install_discord_mock()
        install_slack_mock()

        assert sys.modules["telegram"] is telegram_obj
        assert sys.modules["discord"] is discord_obj
        assert sys.modules["slack_bolt"] is slack_obj


def test_telegram_adapter_sees_string_valued_chattype():
    """The frozen adapter global must carry string-valued ChatType.

    This is the behavioural invariant behind ``test_telegram_thread_fallback``:
    whatever mock won this worker's adapter-import race, ``str(ChatType.
    SUPERGROUP).lower()`` must equal ``"supergroup"`` so the supergroup branch
    fires instead of falling through to "dm". Reads the process-global the
    adapter froze (stable regardless of later sys.modules churn).
    """
    install_telegram_mock()
    from gateway.platforms import telegram as telegram_mod

    assert str(telegram_mod.ChatType.SUPERGROUP).lower() == "supergroup"
    assert str(telegram_mod.ChatType.GROUP).lower() == "group"
    assert str(telegram_mod.ChatType.PRIVATE).lower() == "private"
