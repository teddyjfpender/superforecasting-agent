"""Interactive Anthropic provider setup and credential selection."""

def _run_anthropic_oauth_flow(save_env_value):
    """Run the Claude OAuth setup-token flow. Returns True if credentials were saved."""
    from agent.anthropic_adapter import (
        run_oauth_setup_token,
        read_claude_code_credentials,
        is_claude_code_token_valid,
    )
    from superforecasting_agent.runtime.config import (
        save_anthropic_oauth_token,
        use_anthropic_claude_code_credentials,
    )

    def _activate_claude_code_credentials_if_available() -> bool:
        try:
            creds = read_claude_code_credentials()
        except Exception:
            creds = None
        if creds and (
            is_claude_code_token_valid(creds) or bool(creds.get("refreshToken"))
        ):
            use_anthropic_claude_code_credentials(save_fn=save_env_value)
            print("  ✓ Claude Code credentials linked.")
            from superforecasting_agent.constants import display_agent_home as _dhh_fn

            print(
                f"    Superforecasting Agent will use Claude's credential store directly instead of copying a setup-token into {_dhh_fn()}/.env."
            )
            return True
        return False

    try:
        print()
        print("  Running 'claude setup-token' — follow the prompts below.")
        print("  A browser window will open for you to authorize access.")
        print()
        token = run_oauth_setup_token()
        if token:
            if _activate_claude_code_credentials_if_available():
                return True
            save_anthropic_oauth_token(token, save_fn=save_env_value)
            print("  ✓ OAuth credentials saved.")
            return True

        # Subprocess completed but no token auto-detected — ask user to paste
        print()
        print("  If the setup-token was displayed above, paste it here:")
        print()
        from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

        try:
            manual_token = masked_secret_prompt(
                "  Paste setup-token (or Enter to cancel): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        if manual_token:
            save_anthropic_oauth_token(manual_token, save_fn=save_env_value)
            print("  ✓ Setup-token saved.")
            return True

        print("  ⚠ Could not detect saved credentials.")
        return False

    except FileNotFoundError:
        # Claude CLI not installed — guide user through manual setup
        print()
        print("  The 'claude' CLI is required for OAuth login.")
        print()
        print("  To install and authenticate:")
        print()
        print("    1. Install Claude Code:  npm install -g @anthropic-ai/claude-code")
        print("    2. Run:                  claude setup-token")
        print("    3. Follow the browser prompts to authorize")
        print("    4. Re-run:               superforecasting-agent model")
        print()
        print("  Or paste an existing setup-token now (sk-ant-oat-...):")
        print()
        from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

        try:
            token = masked_secret_prompt("  Setup-token (or Enter to cancel): ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        if token:
            save_anthropic_oauth_token(token, save_fn=save_env_value)
            print("  ✓ Setup-token saved.")
            return True
        print("  Cancelled — install Claude Code and try again.")
        return False


def _model_flow_anthropic(config, current_model=""):
    """Flow for Anthropic provider — OAuth subscription, API key, or Claude Code creds."""
    from superforecasting_agent.runtime.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from superforecasting_agent.runtime.config import (
        save_env_value,
        load_config,
        save_config,
        save_anthropic_api_key,
    )
    from superforecasting_agent.runtime.models import _PROVIDER_MODELS

    # Check ALL credential sources
    from superforecasting_agent.runtime.auth import get_anthropic_key

    existing_key = get_anthropic_key()
    cc_available = False
    try:
        from agent.anthropic_adapter import (
            read_claude_code_credentials,
            is_claude_code_token_valid,
            _is_oauth_token,
        )

        cc_creds = read_claude_code_credentials()
        if cc_creds and is_claude_code_token_valid(cc_creds):
            cc_available = True
    except Exception:
        pass

    # Stale-OAuth guard: if the only existing cred is an expired OAuth token
    # (no valid cc_creds to fall back on), treat it as missing so the re-auth
    # path is offered instead of silently accepting a broken token.
    existing_is_stale_oauth = False
    if existing_key and _is_oauth_token(existing_key) and not cc_available:
        existing_is_stale_oauth = True

    has_creds = (bool(existing_key) and not existing_is_stale_oauth) or cc_available
    needs_auth = not has_creds

    if has_creds:
        # Show what we found
        if existing_key:
            print(f"  Anthropic credentials: {existing_key[:12]}... ✓")
        elif cc_available:
            print("  Claude Code credentials: ✓ (auto-detected)")
        print()
        print("    1. Use existing credentials")
        print("    2. Reauthenticate (new OAuth login)")
        print("    3. Cancel")
        print()
        try:
            choice = input("  Choice [1/2/3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            choice = "1"

        if choice == "2":
            needs_auth = True
        elif choice == "3":
            return
        # choice == "1" or default: use existing, proceed to model selection

    if needs_auth:
        # Show auth method choice
        print()
        print("  Choose authentication method:")
        print()
        print("    1. Claude Pro/Max subscription (OAuth login)")
        print("    2. Anthropic API key (pay-per-token)")
        print("    3. Cancel")
        print()
        try:
            choice = input("  Choice [1/2/3]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if choice == "1":
            if not _run_anthropic_oauth_flow(save_env_value):
                return

        elif choice == "2":
            print()
            print("  Get an API key at: https://platform.claude.com/settings/keys")
            print()
            from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

            try:
                api_key = masked_secret_prompt("  API key (sk-ant-...): ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                return
            if not api_key:
                print("  Cancelled.")
                return
            save_anthropic_api_key(api_key, save_fn=save_env_value)
            print("  ✓ API key saved.")

        else:
            print("  No change.")
            return
    print()

    # Model selection
    model_list = _PROVIDER_MODELS.get("anthropic", [])
    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("Model name (e.g., claude-sonnet-4-20250514): ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Update config with provider — clear base_url since
        # resolve_runtime_provider() always hardcodes Anthropic's URL.
        # Leaving a stale base_url in config can contaminate other
        # providers if the user switches without running
        # 'superforecasting-agent model'.
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "anthropic"
        model.pop("base_url", None)
        save_config(cfg)
        deactivate_provider()

        print(f"Default model set to: {selected} (via Anthropic)")
    else:
        print("No change.")
