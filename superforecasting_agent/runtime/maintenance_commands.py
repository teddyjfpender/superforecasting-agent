"""Classic CLI entry points for profile, curator, debug, and update services."""

def _handle_profile_command(self):
    """Display active profile name and home directory."""
    from superforecasting_agent.constants import display_agent_home
    from superforecasting_agent.runtime.profiles import get_active_profile_name

    display = display_agent_home()
    profile_name = get_active_profile_name()

    print()
    print(f"  Profile: {profile_name}")
    print(f"  Home:    {display}")
    print()


def _handle_curator_command(self, cmd: str):
    """Handle /curator slash command.

        Delegates to superforecasting_agent.runtime.curator so the CLI and the `superforecasting-agent curator`
        subcommand share the same handler set.
        """
    import shlex

    try:
        tokens = shlex.split(cmd)[1:] if cmd else []
        if not tokens:
            tokens = ["status"]
        from superforecasting_agent.runtime.curator import cli_main
        cli_main(tokens)
    except SystemExit:
        # argparse calls sys.exit() on --help or errors; swallow so we
        # don't kill the interactive session.
        pass
    except Exception as exc:
        print(f"curator: {exc}")


def _handle_debug_command(self):
    """Handle /debug — upload debug report + logs and print paste URLs."""
    from superforecasting_agent.runtime.debug import run_debug_share
    from types import SimpleNamespace

    args = SimpleNamespace(lines=200, expire=7, local=False)
    run_debug_share(args)


def _handle_update_command(self) -> bool:
    """Handle /update — update Superforecasting Agent to the latest version.

        In the classic CLI this exits the session and relaunches as
        ``superforecasting-agent update`` so the user sees update output directly and gets
        the new version on next launch.

        Returns ``True`` when the update was confirmed (caller should trigger
        app exit so the relaunch is deferred to the main thread after
        prompt_toolkit cleans up terminal modes).  Returns ``False`` / falsy
        when cancelled.
        """
    from superforecasting_agent.runtime.config import is_managed, format_managed_message

    if is_managed():
        print(f"  ✗ {format_managed_message('update Superforecasting Agent')}")
        return False

    # Use the prompt_toolkit-native modal so the confirmation panel
    # renders properly above the composer and avoids raw input() races
    # with the prompt_toolkit event loop (same pattern as
    # _confirm_destructive_slash).
    choices = [
        (
            "once",
            "Update Now",
            "exit the current session and update Superforecasting Agent",
        ),
        ("cancel", "Cancel", "keep the current session"),
    ]
    raw = self._prompt_text_input_modal(
        title="Update Superforecasting Agent",
        detail="This will exit the current session and run `superforecasting-agent update`.",
        choices=choices,
    )
    if raw is None:
        print("  🟡 /update cancelled.")
        return False
    choice = self._normalize_slash_confirm_choice(raw, choices)
    if choice != "once":
        print("  🟡 /update cancelled.")
        return False

    print()
    print("  Launching update...")
    print()

    # Store the relaunch args so run() can exec them from the main thread
    # after prompt_toolkit exits and restores terminal modes.  Calling
    # relaunch() directly here (from the process_loop daemon thread) would
    # skip terminal cleanup on POSIX (execvp replaces the process mid-TUI)
    # and only exit the worker thread on Windows (subprocess.run +
    # sys.exit inside a non-main thread does not exit the process).
    self._pending_relaunch = ["update"]
    return True
