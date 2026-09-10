"""Interactive configuration for Azure Foundry model providers."""

def _model_flow_azure_foundry(config, current_model=""):
    """Azure Foundry provider: configure endpoint, auth mode, API mode, and model.

    Azure Foundry supports both OpenAI-style (``/v1/chat/completions``) and
    Anthropic-style (``/v1/messages``) endpoints, and two authentication
    modes:

    * **API key** (default) — uses ``AZURE_FOUNDRY_API_KEY`` from .env.
    * **Microsoft Entra ID** — keyless, RBAC-based auth via the
      ``azure-identity`` SDK (Managed Identity / Workload Identity / az
      login / VS Code / azd / service principal env vars). Works on both
      OpenAI-style and Anthropic-style endpoints — Microsoft RBAC is
      per-resource and the same ``Azure AI User`` role grants
      both. For OpenAI-style the OpenAI SDK's native callable
      ``api_key=`` contract is used; for Anthropic-style an
      ``httpx.Client`` with a request event hook (built by
      :func:`agent.azure_identity_adapter.build_bearer_http_client`)
      mints a fresh JWT per request because the Anthropic SDK does not
      accept a callable ``auth_token`` natively.

    The wizard auto-detects the transport and available models when
    possible:

    * URLs ending in ``/anthropic`` → Anthropic Messages API.
    * Successful ``GET <base>/models`` probe → OpenAI-style + populates
      a picker with the returned deployment / model IDs.
    * Anthropic Messages probe fallback when ``/models`` fails.
    * Manual entry when every probe fails (private endpoints, etc.).

    Context lengths for the chosen model are resolved via the standard
    :func:`agent.model_metadata.get_model_context_length` chain
    (models.dev, provider metadata, hardcoded family fallbacks).
    """
    from superforecasting_agent.runtime.auth import _save_model_choice, deactivate_provider  # noqa: F401
    from superforecasting_agent.runtime.config import (
        get_env_value,
        save_env_value,
        load_config,
        save_config,
    )
    from superforecasting_agent.runtime import azure_detect

    # ── Load current Azure Foundry configuration ─────────────────────
    model_cfg = config.get("model", {})
    if isinstance(model_cfg, dict) and model_cfg.get("provider") == "azure-foundry":
        current_base_url = str(model_cfg.get("base_url", "") or "")
        current_api_mode = str(model_cfg.get("api_mode", "") or "")
        current_auth_mode = str(model_cfg.get("auth_mode") or "api_key").strip().lower() or "api_key"
        _cur_entra = model_cfg.get("entra") or {}
        current_entra = _cur_entra if isinstance(_cur_entra, dict) else {}
    else:
        current_base_url = ""
        current_api_mode = ""
        current_auth_mode = "api_key"
        current_entra = {}

    current_api_key = get_env_value("AZURE_FOUNDRY_API_KEY") or ""

    print()
    print("Azure Foundry Configuration")
    print("=" * 50)
    print()
    print("Azure Foundry can host models with either OpenAI-style or")
    print("Anthropic-style API endpoints.  Superforecasting Agent will probe your")
    print("endpoint to auto-detect the transport and the deployed")
    print("models when possible.")
    print()

    if current_base_url:
        print(f"  Current endpoint:  {current_base_url}")
    if current_api_mode:
        _lbl = (
            "OpenAI-style"
            if current_api_mode == "chat_completions"
            else "Anthropic-style"
        )
        print(f"  Current API mode:  {_lbl}")
    if current_auth_mode == "entra_id":
        print(f"  Current auth mode: Microsoft Entra ID (keyless)")
    elif current_api_key:
        print(f"  Current auth mode: API key ({current_api_key[:8]}...)")
    print()

    # ── Step 1: endpoint URL ─────────────────────────────────────────
    try:
        _placeholder = (
            current_base_url
            or "e.g. https://<resource>.openai.azure.com/openai/v1 "
              "or https://<resource>.services.ai.azure.com/anthropic"
        )
        base_url = input(
            f"API endpoint URL [{_placeholder}]: "
        ).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return

    effective_url = (base_url or current_base_url).rstrip("/")
    if not effective_url:
        print("No endpoint URL provided. Cancelled.")
        return
    if not effective_url.startswith(("http://", "https://")):
        print(f"Invalid URL: {effective_url} (must start with http:// or https://)")
        return

    # ── Step 2: authentication mode ──────────────────────────────────
    print()
    print("Authentication:")
    print("  1. API key                  (AZURE_FOUNDRY_API_KEY in .env)")
    print("  2. Microsoft Entra ID       (managed identity / workload identity / az login)")
    print("     Recommended by Microsoft. Works for both OpenAI-style and Anthropic-style endpoints.")
    print("     Requires the 'Azure AI User' role on the Foundry resource.")
    try:
        _auth_default = "2" if current_auth_mode == "entra_id" else "1"
        auth_choice = (
            input(f"Authentication mode [1/2] ({_auth_default}): ").strip()
            or _auth_default
        )
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return
    use_entra = auth_choice == "2"
    auth_mode_label = "entra_id" if use_entra else "api_key"

    # ── Step 3: credentials (key OR Entra preflight) ─────────────────
    effective_key: str = ""
    entra_overrides: dict = {}
    token_provider = None  # callable when entra
    entra_scope = ""

    if use_entra:
        try:
            from agent.azure_identity_adapter import (
                EntraIdentityConfig,
                SCOPE_AI_AZURE_DEFAULT,
                build_token_provider,
                describe_active_credential,
                has_azure_identity_installed,
            )
        except ImportError as exc:
            print()
            print(f"⚠ Could not import azure-identity adapter: {exc}")
            print("  Falling back to API key auth.")
            use_entra = False
            auth_mode_label = "api_key"

    if use_entra:
        print()
        if not has_azure_identity_installed():
            print("◐ The 'azure-identity' package is not installed yet.")
            print(
                "  Superforecasting Agent will install it now (the preflight below "
                "triggers the lazy-install). To skip lazy installs, "
                "run:  pip install azure-identity"
            )

        # Preserve only the optional scope override. Identity selection
        # (tenant, user-assigned MI, workload identity, service principal)
        # stays in Azure SDK env vars such as AZURE_CLIENT_ID.
        _persisted_scope_override = str(current_entra.get("scope") or "").strip()
        entra_scope = _persisted_scope_override or SCOPE_AI_AZURE_DEFAULT

        entra_overrides = {}
        if _persisted_scope_override:
            entra_overrides["scope"] = _persisted_scope_override

        print()
        print("◐ Probing Microsoft Entra ID credential chain (up to 10s)...")
        _config = EntraIdentityConfig(
            scope=entra_scope,
        )
        info = describe_active_credential(config=_config, timeout_seconds=10.0)
        if info.get("ok"):
            env_sources = info.get("env_sources") or []
            tag = ", ".join(env_sources) if env_sources else "default chain"
            print(f"✓ Entra ID token acquired ({tag}, scope={entra_scope})")
        else:
            err = info.get("error") or "credential chain exhausted"
            hint = info.get("hint") or (
                "Run `az login`, attach a managed identity to this VM, or "
                "set AZURE_TENANT_ID/AZURE_CLIENT_ID/AZURE_CLIENT_SECRET."
            )
            print(f"⚠ {err}")
            print(f"  Hint: {hint}")
            try:
                ans = input("Save Entra config anyway and validate later? [Y/n]: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return
            if ans and ans not in ("y", "yes"):
                print("Cancelled.")
                return

        # Build the token provider for the detection probe (best-effort —
        # if the credential chain failed above, this will silently return
        # None inside azure_detect and the probe falls back to manual).
        try:
            token_provider = build_token_provider(config=_config)
        except Exception as exc:
            print(f"⚠ Could not build token provider for probing: {exc}")
            token_provider = None
    else:
        print()
        from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

        try:
            api_key = masked_secret_prompt(
                f"API key [{current_api_key[:8] + '...' if current_api_key else 'required'}]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return

        effective_key = api_key or current_api_key
        if not effective_key:
            print("No API key provided. Cancelled.")
            return

    # ── Step 4: auto-detect transport + models ───────────────────────
    print()
    print("◐ Probing endpoint to auto-detect transport and models...")
    detection = azure_detect.detect(
        effective_url,
        api_key=effective_key,
        token_provider=token_provider,
    )

    discovered_models: list[str] = list(detection.models)
    api_mode: str = detection.api_mode or ""

    if api_mode:
        mode_label = (
            "OpenAI-style" if api_mode == "chat_completions" else "Anthropic-style"
        )
        print(f"✓ Detected API transport: {mode_label}")
        if detection.reason:
            print(f"    ({detection.reason})")
        if discovered_models:
            print(
                f"✓ Found {len(discovered_models)} deployed model(s) on this endpoint"
            )
    else:
        print(f"⚠ Auto-detection incomplete: {detection.reason}")
        print()
        print("Select the API format your Azure Foundry endpoint uses:")
        print("  1. OpenAI-style  (POST /v1/chat/completions)")
        print("     For: GPT models, Llama, Mistral, and most open models")
        print("  2. Anthropic-style  (POST /v1/messages)")
        print("     For: Claude models deployed via Anthropic API format")
        try:
            default_choice = "2" if current_api_mode == "anthropic_messages" else "1"
            mode_choice = (
                input(f"API format [1/2] ({default_choice}): ").strip()
                or default_choice
            )
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return
        api_mode = "anthropic_messages" if mode_choice == "2" else "chat_completions"

    # ── Step 5: model name ───────────────────────────────────────────
    print()
    effective_model = ""
    if discovered_models:
        print("Available models on this endpoint:")
        for i, mid in enumerate(discovered_models[:30], start=1):
            print(f"  {i:>2}. {mid}")
        if len(discovered_models) > 30:
            print(
                f"  ... and {len(discovered_models) - 30} more (type name manually if not shown)"
            )
        print()
        try:
            pick = input(
                f"Pick by number, or type a deployment name [{current_model or discovered_models[0]}]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return
        if not pick:
            effective_model = current_model or discovered_models[0]
        elif pick.isdigit() and 1 <= int(pick) <= min(len(discovered_models), 30):
            effective_model = discovered_models[int(pick) - 1]
        else:
            effective_model = pick
    else:
        try:
            model_name = input(
                f"Model / deployment name [{current_model or 'e.g. gpt-5.4, claude-sonnet-4-6'}]: "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return
        effective_model = model_name or current_model

    if not effective_model:
        print("No model name provided. Cancelled.")
        return

    # ── Step 6: context-length lookup ────────────────────────────────
    ctx_len = azure_detect.lookup_context_length(
        effective_model,
        effective_url,
        api_key=effective_key,
        token_provider=token_provider,
    )

    # ── Step 7: persist ──────────────────────────────────────────────
    if not use_entra:
        save_env_value("AZURE_FOUNDRY_API_KEY", effective_key)

    cfg = load_config()
    model = cfg.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        cfg["model"] = model

    model["provider"] = "azure-foundry"
    model["base_url"] = effective_url
    model["api_mode"] = api_mode
    model["default"] = effective_model
    model["auth_mode"] = auth_mode_label
    if use_entra:
        # Persist only the non-default Entra scope so config.yaml stays tidy.
        # Azure identity selection stays in standard AZURE_* env vars.
        clean_entra: dict = {}
        for key in ("scope",):
            val = entra_overrides.get(key)
            if val:
                clean_entra[key] = val
        if clean_entra:
            model["entra"] = clean_entra
        elif "entra" in model:
            del model["entra"]
    else:
        if "entra" in model:
            del model["entra"]
    if ctx_len:
        model["context_length"] = ctx_len

    save_config(cfg)
    deactivate_provider()
    config["model"] = dict(model)

    # Clear any conflicting env vars so auxiliary clients don't poison
    # themselves with a stale OpenAI base URL / key.
    if get_env_value("OPENAI_BASE_URL"):
        save_env_value("OPENAI_BASE_URL", "")
    if get_env_value("OPENAI_API_KEY"):
        save_env_value("OPENAI_API_KEY", "")

    mode_label = "OpenAI-style" if api_mode == "chat_completions" else "Anthropic-style"
    auth_label = (
        "Microsoft Entra ID (keyless)" if use_entra else "API key"
    )
    print()
    print("✓ Azure Foundry configured:")
    print(f"    Endpoint:       {effective_url}")
    print(f"    API mode:       {mode_label}")
    print(f"    Auth:           {auth_label}")
    print(f"    Model:          {effective_model}")
    if ctx_len:
        print(f"    Context length: {ctx_len:,} tokens")
    else:
        print("    Context length: not auto-detected (will fall back at runtime)")
    print()
