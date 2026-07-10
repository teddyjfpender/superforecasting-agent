"""Single source of truth for the platform-library test doubles.

Rationale (the class of bug this kills)
----------------------------------------
The gateway adapters (``gateway.platforms.telegram`` / ``.discord`` /
``.slack``) do a module-level ``import telegram`` / ``import discord`` /
``import slack_bolt``. Those bindings are frozen at *first import* of the
adapter module — a process-global singleton. Whichever test conftest first
imports an adapter decides, for the entire worker, which mock object the
adapter is wired to.

Historically two conftests (``tests/gateway/conftest.py`` and
``tests/e2e/conftest.py``) each installed their *own*, *divergent* mocks:

* ``tests/e2e/conftest.py`` sorts before ``tests/gateway/`` and imports the
  adapters eagerly at collection time — so in any wide selection it won the
  race and froze the adapters to its **incomplete** mocks.
* Its telegram mock never set ``ChatType.SUPERGROUP = "supergroup"``, so
  production code doing ``str(chat.type).lower() == "supergroup"`` silently
  fell through and classified every group chat as ``"dm"``.
* Its discord mock lacked ``AllowedMentions`` / ``app_commands.Command``,
  and because ``test_discord_connect`` later patched ``AllowedMentions`` onto
  a *different* (gateway) mock object, the already-bound adapter never saw
  it — ``am.everyone`` came back a ``MagicMock`` instead of ``False``.

Both were the same disease: **two mock objects for one process-global
binding.** The cure is a single canonical, *complete* mock object per
library, installed idempotently so the first installer wins and every later
one is a no-op that preserves the same object. Adapter bindings, and any
per-test augmentation of ``sys.modules[...]`` attributes, then always refer
to the one object the adapter holds.

Every mock here is the **superset** of what the gateway and e2e suites need,
so it does not matter which suite imports the adapter first.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

# Sentinel attribute stamped onto every canonical mock module object. Its
# presence means "our complete test double is already installed" — the
# installers below short-circuit on it so there is exactly one object per
# library for the lifetime of the worker process.
_SENTINEL = "_hermes_test_platform_mock"


def _already_installed(top_name: str) -> bool:
    """True if a real library OR our canonical mock is already present."""
    existing = sys.modules.get(top_name)
    if existing is None:
        return False
    if hasattr(existing, "__file__"):
        return True  # the real library is installed — never shadow it
    return bool(getattr(existing, _SENTINEL, False))


class FakeAllowedMentions:
    """Stand-in for ``discord.AllowedMentions``.

    Exposes the same four boolean flags as real attributes so tests can
    assert on the safe defaults the adapter passes to ``commands.Bot``.
    """

    def __init__(self, *, everyone=True, roles=True, users=True, replied_user=True):
        self.everyone = everyone
        self.roles = roles
        self.users = users
        self.replied_user = replied_user


def install_telegram_mock() -> None:
    """Install the canonical telegram test double (idempotent).

    Superset of every attribute the gateway + e2e suites read. The
    ``constants.ChatType.*`` string values are load-bearing: production code
    classifies chats via ``str(chat.type).lower()``, so these must equal the
    real python-telegram-bot enum ``.value`` strings.
    """
    if _already_installed("telegram"):
        return

    mod = MagicMock()
    setattr(mod, _SENTINEL, True)

    # The same ``mod`` object is registered in sys.modules under "telegram",
    # "telegram.constants", "telegram.ext" and "telegram.request". The adapter
    # reaches its symbols via ``from telegram.constants import ChatType`` /
    # ``from telegram.ext import filters`` etc., which resolves to
    # ``sys.modules["telegram.constants"].ChatType`` == ``mod.ChatType`` — the
    # FLAT attribute on ``mod``, NOT ``mod.constants.ChatType``.
    #
    # DELIBERATELY MINIMAL. This mirrors the mock the gateway suite was written
    # against, where most attributes are left as value-less ``MagicMock``
    # auto-children ON PURPOSE: several telegram tests assert on
    # ``repr(parse_mode)`` containing the enum *name* (e.g. "MARKDOWN_V2"),
    # which only holds for a value-less mock. The single value that MUST be a
    # real string is ``ChatType``, because production code classifies chats via
    # ``str(chat.type).lower() == "supergroup"``. Historically this string was
    # set on the dead ``mod.constants.ChatType`` path, so once this mock won the
    # adapter-import race every group chat mis-classified as "dm". Setting it on
    # the live flat ``mod.ChatType`` path is the whole fix — do NOT "complete"
    # the other constants or you will break the repr-based escaping tests.

    # Update.ALL_TYPES is iterated by start_polling().
    mod.Update.ALL_TYPES = []

    # ext.ContextTypes / constants.ParseMode kept on the (dead) nested paths for
    # parity with the historical mock; the adapter reads value-less flat mocks
    # for these, which the escaping tests rely on.
    mod.ext.ContextTypes.DEFAULT_TYPE = type(None)
    mod.constants.ParseMode.MARKDOWN = "Markdown"
    mod.constants.ParseMode.MARKDOWN_V2 = "MarkdownV2"
    mod.constants.ParseMode.HTML = "HTML"

    # ChatType — the ONLY load-bearing string values, on the LIVE flat path.
    mod.ChatType.PRIVATE = "private"
    mod.ChatType.GROUP = "group"
    mod.ChatType.SUPERGROUP = "supergroup"
    mod.ChatType.CHANNEL = "channel"

    # Real exception classes so ``except (NetworkError, ...)`` clauses in
    # production code don't blow up with TypeError. Set on ``mod.error`` which
    # is registered as the "telegram.error" submodule below.
    mod.error.NetworkError = type("NetworkError", (OSError,), {})
    mod.error.TimedOut = type("TimedOut", (OSError,), {})
    mod.error.BadRequest = type("BadRequest", (Exception,), {})
    mod.error.Forbidden = type("Forbidden", (Exception,), {})
    mod.error.InvalidToken = type("InvalidToken", (Exception,), {})
    mod.error.RetryAfter = type("RetryAfter", (Exception,), {"retry_after": 1})
    mod.error.Conflict = type("Conflict", (Exception,), {})

    for name in (
        "telegram",
        "telegram.constants",
        "telegram.ext",
        "telegram.ext.filters",
        "telegram.request",
    ):
        sys.modules[name] = mod
    sys.modules["telegram.error"] = mod.error


def install_discord_mock() -> None:
    """Install the canonical discord test double (idempotent).

    Superset of the gateway + e2e suites. Ships a real ``AllowedMentions``
    class and a full ``app_commands`` namespace (incl. ``Group``/``Command``)
    so the adapter's connect() and slash-command auto-registration work no
    matter which suite imported the adapter first.
    """
    if _already_installed("discord"):
        return

    discord_mod = MagicMock()
    setattr(discord_mod, _SENTINEL, True)

    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.Forbidden = type("Forbidden", (Exception,), {})
    discord_mod.Interaction = object
    discord_mod.Message = type("Message", (), {})
    discord_mod.AllowedMentions = FakeAllowedMentions
    discord_mod.opus.is_loaded.return_value = True

    # NOTE: ``MessageType`` and ``Object`` are DELIBERATELY left as value-less
    # MagicMock auto-children (not a SimpleNamespace with a fixed member set).
    # Gateway tests such as test_discord_system_messages reference arbitrary
    # members (``MessageType.new_member``, ``.pins_add``, ``.thread_rename`` …)
    # and rely on each resolving to a distinct auto-child; pinning MessageType
    # to ``SimpleNamespace(default=…, reply=…)`` would raise AttributeError on
    # every other member. The e2e suite only ever reads ``MessageType.default``,
    # which the auto-child satisfies.

    # Embed: accept the kwargs production code / tests use and expose them.
    class _FakeEmbed:
        def __init__(self, *, title=None, description=None, color=None, **_):
            self.title = title
            self.description = description
            self.color = color
            self.fields = []
            self.footer = None

        def add_field(self, *, name=None, value=None, inline=False, **_):
            self.fields.append({"name": name, "value": value, "inline": inline})
            return self

        def set_footer(self, *, text=None, icon_url=None, **_):
            self.footer = {"text": text, "icon_url": icon_url}
            return self

    discord_mod.Embed = _FakeEmbed

    # ui.View / Select / Button: real classes (not MagicMock) so tests that
    # subclass views / iterate .children / clear items work.
    class _FakeView:
        def __init__(self, timeout=None):
            self.timeout = timeout
            self.children = []

        def add_item(self, item):
            self.children.append(item)

        def clear_items(self):
            self.children.clear()

    class _FakeSelect:
        def __init__(self, *, placeholder=None, options=None, custom_id=None, **_):
            self.placeholder = placeholder
            self.options = options or []
            self.custom_id = custom_id
            self.callback = None
            self.disabled = False

    class _FakeButton:
        def __init__(self, *, label=None, style=None, custom_id=None, emoji=None,
                     url=None, disabled=False, row=None, sku_id=None, **_):
            self.label = label
            self.style = style
            self.custom_id = custom_id
            self.emoji = emoji
            self.url = url
            self.disabled = disabled
            self.row = row
            self.sku_id = sku_id
            self.callback = None

    class _FakeSelectOption:
        def __init__(self, *, label=None, value=None, description=None, **_):
            self.label = label
            self.value = value
            self.description = description

    discord_mod.SelectOption = _FakeSelectOption
    discord_mod.ui = SimpleNamespace(
        View=_FakeView,
        Select=_FakeSelect,
        Button=_FakeButton,
        button=lambda *a, **k: (lambda fn: fn),
    )
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3,
        green=1, grey=2, blurple=2, red=3,
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3,
        red=lambda: 4, purple=lambda: 5, greyple=lambda: 6,
    )

    # app_commands — needed by _register_slash_commands auto-registration.
    class _FakeGroup:
        def __init__(self, *, name, description, parent=None):
            self.name = name
            self.description = description
            self.parent = parent
            self._children: dict = {}
            if parent is not None:
                parent.add_command(self)

        def add_command(self, cmd):
            self._children[cmd.name] = cmd

    class _FakeCommand:
        def __init__(self, *, name, description, callback, parent=None):
            self.name = name
            self.description = description
            self.callback = callback
            self.parent = parent

    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
        Group=_FakeGroup,
        Command=_FakeCommand,
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules["discord"] = discord_mod
    sys.modules["discord.ext"] = ext_mod
    sys.modules["discord.ext.commands"] = commands_mod
    sys.modules["discord.opus"] = discord_mod.opus


def install_slack_mock() -> None:
    """Install the canonical slack test double (idempotent)."""
    if _already_installed("slack_bolt"):
        return

    slack_bolt = MagicMock()
    setattr(slack_bolt, _SENTINEL, True)
    slack_bolt.async_app.AsyncApp = MagicMock
    slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler = MagicMock

    slack_sdk = MagicMock()
    setattr(slack_sdk, _SENTINEL, True)
    slack_sdk.web.async_client.AsyncWebClient = MagicMock

    for name, mod in (
        ("slack_bolt", slack_bolt),
        ("slack_bolt.async_app", slack_bolt.async_app),
        ("slack_bolt.adapter", slack_bolt.adapter),
        ("slack_bolt.adapter.socket_mode", slack_bolt.adapter.socket_mode),
        ("slack_bolt.adapter.socket_mode.async_handler",
         slack_bolt.adapter.socket_mode.async_handler),
        ("slack_sdk", slack_sdk),
        ("slack_sdk.web", slack_sdk.web),
        ("slack_sdk.web.async_client", slack_sdk.web.async_client),
    ):
        sys.modules[name] = mod


def install_all_platform_mocks() -> None:
    """Install every canonical platform test double (idempotent)."""
    install_telegram_mock()
    install_discord_mock()
    install_slack_mock()
