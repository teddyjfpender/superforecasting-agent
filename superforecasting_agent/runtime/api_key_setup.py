"""Shared API-key entry and provider model setup."""

import os

def _prompt_api_key(pconfig, existing_key: str, provider_id: str = "") -> tuple:
    """Shared API-key entry point for setup and ``superforecasting-agent model``.

    Handles both first-time entry and the already-configured case.  When a key
    is already present, offers [K]eep / [R]eplace / [C]lear so the user can
    recover from a malformed paste without editing the active agent-home
    ``.env`` by hand.

    Returns ``(resolved_key, abort)``.  ``abort=True`` means the caller should
    ``return`` immediately — the user cancelled entry, declined to replace, or
    cleared the key and is now unconfigured.
    """
    from superforecasting_agent.runtime.auth import LMSTUDIO_NOAUTH_PLACEHOLDER
    from superforecasting_agent.runtime.config import save_env_value
    from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

    key_env = pconfig.api_key_env_vars[0] if pconfig.api_key_env_vars else ""

    def _prompt_new_key(*, allow_lmstudio_default: bool) -> str:
        if provider_id == "lmstudio" and allow_lmstudio_default:
            prompt = f"{key_env} (Enter for no-auth default {LMSTUDIO_NOAUTH_PLACEHOLDER!r}): "
        else:
            prompt = f"{key_env} (or Enter to cancel): "
        try:
            entered = masked_secret_prompt(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return ""
        if not entered and provider_id == "lmstudio" and allow_lmstudio_default:
            return LMSTUDIO_NOAUTH_PLACEHOLDER
        return entered

    # First-time entry ────────────────────────────────────────────────────
    if not existing_key:
        print(f"No {pconfig.name} API key configured.")
        if not key_env:
            return "", True
        new_key = _prompt_new_key(allow_lmstudio_default=True)
        if not new_key:
            print("Cancelled.")
            return "", True
        save_env_value(key_env, new_key)
        print("API key saved.")
        print()
        return new_key, False

    # Already configured — offer K / R / C ────────────────────────────────
    print(f"  {pconfig.name} API key: {existing_key[:8]}... ✓")
    if not key_env:
        # Nothing we can rewrite; just acknowledge and move on.
        print()
        return existing_key, False
    try:
        choice = input("  [K]eep / [R]eplace / [C]lear (default K): ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print()
        choice = "k"

    if choice.startswith("r"):
        new_key = _prompt_new_key(allow_lmstudio_default=False)
        if not new_key:
            print("  No change.")
            print()
            return existing_key, False
        save_env_value(key_env, new_key)
        print("  API key updated.")
        print()
        return new_key, False

    if choice.startswith("c"):
        save_env_value(key_env, "")
        print(
            f"  API key cleared.  Re-run `superforecasting-agent setup` to configure {pconfig.name} again."
        )
        return "", True

    # Keep (default, or any other input)
    print()
    return existing_key, False


def _model_flow_api_key_provider(config, provider_id, current_model="", *, _PROVIDER_MODELS, _prompt_api_key):
    """Generic flow for API-key providers (z.ai, MiniMax, OpenCode, etc.)."""
    from superforecasting_agent.runtime.auth import (
        LMSTUDIO_NOAUTH_PLACEHOLDER,
        PROVIDER_REGISTRY,
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from superforecasting_agent.runtime.config import (
        get_env_value,
        save_env_value,
        load_config,
        save_config,
    )
    from superforecasting_agent.runtime.models import (
        fetch_api_models,
        opencode_model_api_mode,
        normalize_opencode_model_id,
    )

    pconfig = PROVIDER_REGISTRY[provider_id]
    key_env = pconfig.api_key_env_vars[0] if pconfig.api_key_env_vars else ""
    base_url_env = pconfig.base_url_env_var or ""

    # Check / prompt for API key
    existing_key = ""
    for ev in pconfig.api_key_env_vars:
        existing_key = get_env_value(ev) or os.getenv(ev, "")
        if existing_key:
            break

    existing_key, abort = _prompt_api_key(
        pconfig, existing_key, provider_id=provider_id
    )
    if abort:
        return

    # Gemini free-tier gate: free-tier daily quotas (<= 250 RPD for Flash)
    # are exhausted in a handful of agent turns, so refuse to wire up the
    # provider with a free-tier key. Probe is best-effort; network or auth
    # errors fall through without blocking.
    if provider_id == "gemini" and existing_key:
        try:
            from agent.gemini_native_adapter import probe_gemini_tier
        except Exception:
            probe_gemini_tier = None
        if probe_gemini_tier is not None:
            print("  Checking Gemini API tier...")
            probe_base = (
                (get_env_value(base_url_env) if base_url_env else "")
                or os.getenv(base_url_env or "", "")
                or pconfig.inference_base_url
            )
            tier = probe_gemini_tier(existing_key, probe_base)
            if tier == "free":
                print()
                print(
                    "❌ This Google API key is on the free tier "
                    "(<= 250 requests/day for gemini-2.5-flash)."
                )
                print(
                    "   Superforecasting Agent typically makes 3-10 API calls per user turn "
                    "(tool iterations + auxiliary tasks),"
                )
                print(
                    "   so the free tier is exhausted after a handful of "
                    "messages and cannot sustain"
                )
                print("   an agent session.")
                print()
                print(
                    "   To use Gemini with Superforecasting Agent, enable billing on your "
                    "Google Cloud project and regenerate"
                )
                print(
                    "   the key in a billing-enabled project: "
                    "https://aistudio.google.com/apikey"
                )
                print()
                print(
                    "   Alternatives with workable free usage: DeepSeek, "
                    "OpenRouter (free models), Groq, Nous."
                )
                print()
                print("Not saving Gemini as the default provider.")
                return
            if tier == "paid":
                print("  Tier check: paid ✓")
            else:
                # "unknown" -- network issue, auth problem, unexpected response.
                # Don't block; the runtime 429 handler will surface free-tier
                # guidance if the key turns out to be free tier.
                print("  Tier check: could not verify (proceeding anyway).")
            print()

    # Optional base URL override.
    # Precedence: env var → config.yaml model.base_url → registry default.
    # Reading config.yaml prevents silently overwriting a saved remote URL
    # (e.g. a remote LM Studio endpoint) with localhost when the user just
    # presses Enter at the prompt below.
    current_base = ""
    if base_url_env:
        current_base = get_env_value(base_url_env) or os.getenv(base_url_env, "")
    if not current_base:
        try:
            _m = load_config().get("model") or {}
            if str(_m.get("provider") or "").strip().lower() == provider_id:
                current_base = str(_m.get("base_url") or "").strip()
        except Exception:
            pass
    effective_base = current_base or pconfig.inference_base_url

    try:
        override = input(f"Base URL [{effective_base}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        override = ""
    if override and base_url_env:
        if not override.startswith(("http://", "https://")):
            print(
                "  Invalid URL — must start with http:// or https://. Keeping current value."
            )
        else:
            save_env_value(base_url_env, override)
            effective_base = override

    # Model selection — resolution order:
    #   1. models.dev registry (cached, filtered for agentic/tool-capable models)
    #   2. Curated static fallback list (offline insurance)
    #   3. Live /models endpoint probe (small providers without models.dev data)
    #
    # LM Studio: live /api/v1/models probe (no models.dev catalog).
    # Ollama Cloud: merged discovery (live API + models.dev + disk cache).
    if provider_id == "lmstudio":
        from superforecasting_agent.runtime.auth import AuthError
        from superforecasting_agent.runtime.models import fetch_lmstudio_models

        api_key_for_probe = existing_key or (get_env_value(key_env) if key_env else "")
        try:
            model_list = fetch_lmstudio_models(
                api_key=api_key_for_probe, base_url=effective_base
            )
        except AuthError as exc:
            print(f"  LM Studio rejected the request: {exc}")
            print("  Set LM_API_KEY (or update it) to match the server's bearer token.")
            model_list = []
        if model_list:
            print(f"  Found {len(model_list)} model(s) from LM Studio")
    elif provider_id == "ollama-cloud":
        from superforecasting_agent.runtime.models import fetch_ollama_cloud_models

        api_key_for_probe = existing_key or (get_env_value(key_env) if key_env else "")
        # During setup, force a live refresh so the picker reflects newly
        # released models (e.g. deepseek v4 flash, kimi k2.6) the moment
        # the user enters their key — not an hour later when the disk
        # cache TTL expires.
        model_list = fetch_ollama_cloud_models(
            api_key=api_key_for_probe,
            base_url=effective_base,
            force_refresh=True,
        )
        if model_list:
            print(f"  Found {len(model_list)} model(s) from Ollama Cloud")
    elif provider_id == "novita":
        from superforecasting_agent.runtime.models import fetch_api_models

        api_key_for_probe = existing_key or (get_env_value(key_env) if key_env else "")
        curated = _PROVIDER_MODELS.get(provider_id, [])
        live_models = fetch_api_models(api_key_for_probe, effective_base)
        if live_models:
            model_list = live_models
            print(f"  Found {len(model_list)} model(s) from {pconfig.name} API")
        else:
            mdev_models: list = []
            try:
                from agent.models_dev import list_agentic_models

                mdev_models = list_agentic_models(provider_id)
            except Exception:
                pass
            if mdev_models:
                seen = {m.lower() for m in mdev_models}
                model_list = list(mdev_models)
                for m in curated:
                    if m.lower() not in seen:
                        model_list.append(m)
                        seen.add(m.lower())
                print(f"  Found {len(model_list)} model(s) from models.dev registry")
            else:
                model_list = curated
                if model_list:
                    print(
                        f'  Showing {len(model_list)} curated models — use "Enter custom model name" for others.'
                    )
    else:
        curated = _PROVIDER_MODELS.get(provider_id, [])

        # Try models.dev first — returns tool-capable models, filtered for noise
        mdev_models: list = []
        try:
            from agent.models_dev import list_agentic_models

            mdev_models = list_agentic_models(provider_id)
        except Exception:
            pass

        if mdev_models:
            # Merge models.dev with curated list so newly added models
            # (not yet in models.dev) still appear in the picker.
            if curated:
                seen = {m.lower() for m in mdev_models}
                merged = list(mdev_models)
                for m in curated:
                    if m.lower() not in seen:
                        merged.append(m)
                        seen.add(m.lower())
                model_list = merged
            else:
                model_list = mdev_models
            print(f"  Found {len(model_list)} model(s) from models.dev registry")
        elif curated and len(curated) >= 8:
            # Curated list is substantial — use it directly, skip live probe
            model_list = curated
            print(
                f'  Showing {len(model_list)} curated models — use "Enter custom model name" for others.'
            )
        else:
            api_key_for_probe = existing_key or (
                get_env_value(key_env) if key_env else ""
            )
            live_models = fetch_api_models(api_key_for_probe, effective_base)
            if live_models and len(live_models) >= len(curated):
                model_list = live_models
                print(f"  Found {len(model_list)} model(s) from {pconfig.name} API")
            else:
                model_list = curated
                if model_list:
                    print(
                        f'  Showing {len(model_list)} curated models — use "Enter custom model name" for others.'
                    )
            # else: no defaults either, will fall through to raw input

    if provider_id in {"opencode-zen", "opencode-go"}:
        model_list = [
            normalize_opencode_model_id(provider_id, mid) for mid in model_list
        ]
        current_model = normalize_opencode_model_id(provider_id, current_model)
        model_list = list(dict.fromkeys(mid for mid in model_list if mid))

    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("Model name: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        if provider_id in {"opencode-zen", "opencode-go"}:
            selected = normalize_opencode_model_id(provider_id, selected)

        _save_model_choice(selected)

        # Update config with provider, base URL, and provider-specific API mode
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = provider_id
        model["base_url"] = effective_base
        if provider_id in {"opencode-zen", "opencode-go"}:
            model["api_mode"] = opencode_model_api_mode(provider_id, selected)
        else:
            model.pop("api_mode", None)
        save_config(cfg)
        deactivate_provider()

        print(f"Default model set to: {selected} (via {pconfig.name})")
    else:
        print("No change.")
