"""Interactive model setup for subscription OAuth providers."""

import argparse

def _model_flow_nous(config, current_model="", args=None):
    """Nous Portal provider: ensure logged in, then pick model."""
    from superforecasting_agent.runtime.auth import (
        get_provider_auth_state,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
        resolve_nous_runtime_credentials,
        AuthError,
        format_auth_error,
        _login_nous,
        PROVIDER_REGISTRY,
    )
    from superforecasting_agent.runtime.config import (
        get_env_value,
        load_config,
        save_config,
        save_env_value,
    )
    from superforecasting_agent.runtime.nous_subscription import prompt_enable_tool_gateway

    state = get_provider_auth_state("nous")
    if not state or not state.get("access_token"):
        print("Not logged into Nous Portal. Starting login...")
        print()
        try:
            mock_args = argparse.Namespace(
                portal_url=getattr(args, "portal_url", None),
                inference_url=getattr(args, "inference_url", None),
                client_id=getattr(args, "client_id", None),
                scope=getattr(args, "scope", None),
                no_browser=bool(getattr(args, "no_browser", False)),
                timeout=getattr(args, "timeout", None) or 15.0,
                ca_bundle=getattr(args, "ca_bundle", None),
                insecure=bool(getattr(args, "insecure", False)),
            )
            _login_nous(mock_args, PROVIDER_REGISTRY["nous"])
            # Offer Tool Gateway enablement for paid subscribers
            try:
                _refreshed = load_config() or {}
                prompt_enable_tool_gateway(_refreshed)
            except Exception:
                pass
        except SystemExit:
            print("Login cancelled or failed.")
            return
        except Exception as exc:
            print(f"Login failed: {exc}")
            return
        # login_nous already handles model selection + config update
        return

    # Already logged in — use curated model list (same as OpenRouter defaults).
    # The live /models endpoint returns hundreds of models; the curated list
    # shows only agentic models users recognize from OpenRouter.
    from superforecasting_agent.runtime.models import (
        get_curated_nous_model_ids,
        get_pricing_for_provider,
        check_nous_free_tier,
        partition_nous_models_by_tier,
        union_with_portal_free_recommendations,
        union_with_portal_paid_recommendations,
    )

    model_ids = get_curated_nous_model_ids()
    if not model_ids:
        print("No curated models available for Nous Portal.")
        return

    # Verify credentials are still valid (catches expired sessions early)
    try:
        creds = resolve_nous_runtime_credentials(min_key_ttl_seconds=5 * 60)
    except Exception as exc:
        relogin = isinstance(exc, AuthError) and exc.relogin_required
        msg = format_auth_error(exc) if isinstance(exc, AuthError) else str(exc)
        if relogin:
            print(f"Session expired: {msg}")
            print("Re-authenticating with Nous Portal...\n")
            try:
                mock_args = argparse.Namespace(
                    portal_url=None,
                    inference_url=None,
                    client_id=None,
                    scope=None,
                    no_browser=False,
                    timeout=15.0,
                    ca_bundle=None,
                    insecure=False,
                )
                _login_nous(mock_args, PROVIDER_REGISTRY["nous"])
            except Exception as login_exc:
                print(f"Re-login failed: {login_exc}")
            return
        print(f"Could not verify credentials: {msg}")
        return

    # Fetch live pricing (non-blocking — returns empty dict on failure)
    pricing = get_pricing_for_provider("nous")

    # Check if user is on free tier
    free_tier = check_nous_free_tier()

    # Resolve portal URL early — needed both for upgrade links and for the
    # freeRecommendedModels endpoint below.
    _nous_portal_url = ""
    try:
        _nous_state = get_provider_auth_state("nous")
        if _nous_state:
            _nous_portal_url = _nous_state.get("portal_base_url", "")
    except Exception:
        pass

    # For free users: partition models into selectable/unavailable based on
    # whether they are free per the Portal-reported pricing.  First augment
    # with the Portal's freeRecommendedModels list so newly-launched free
    # models show up even if this CLI build's hardcoded curated list and
    # docs-hosted manifest haven't caught up yet.
    #
    # For paid users: mirror the same idea with paidRecommendedModels so
    # newly-launched paid models surface in the picker too — independent
    # of CLI release cadence.
    unavailable_models: list[str] = []
    if free_tier:
        model_ids, pricing = union_with_portal_free_recommendations(
            model_ids, pricing, _nous_portal_url,
        )
        model_ids, unavailable_models = partition_nous_models_by_tier(
            model_ids, pricing, free_tier=True
        )
    else:
        model_ids, pricing = union_with_portal_paid_recommendations(
            model_ids, pricing, _nous_portal_url,
        )

    if not model_ids and not unavailable_models:
        print("No models available for Nous Portal after filtering.")
        return

    if free_tier and not model_ids:
        print("No free models currently available.")
        if unavailable_models:
            from superforecasting_agent.runtime.auth import DEFAULT_NOUS_PORTAL_URL

            _url = (_nous_portal_url or DEFAULT_NOUS_PORTAL_URL).rstrip("/")
            print(f"Upgrade at {_url} to access paid models.")
        return

    print(
        f'Showing {len(model_ids)} curated models — use "Enter custom model name" for others.'
    )

    selected = _prompt_model_selection(
        model_ids,
        current_model=current_model,
        pricing=pricing,
        unavailable_models=unavailable_models,
        portal_url=_nous_portal_url,
    )
    if selected:
        _save_model_choice(selected)
        # Reactivate Nous as the provider and update config
        inference_url = creds.get("base_url", "")
        _update_config_for_provider("nous", inference_url)
        current_model_cfg = config.get("model")
        if isinstance(current_model_cfg, dict):
            model_cfg = dict(current_model_cfg)
        elif isinstance(current_model_cfg, str) and current_model_cfg.strip():
            model_cfg = {"default": current_model_cfg.strip()}
        else:
            model_cfg = {}
        model_cfg["provider"] = "nous"
        model_cfg["default"] = selected
        if inference_url and inference_url.strip():
            model_cfg["base_url"] = inference_url.rstrip("/")
        else:
            model_cfg.pop("base_url", None)
        config["model"] = model_cfg
        # Clear any custom endpoint that might conflict
        if get_env_value("OPENAI_BASE_URL"):
            save_env_value("OPENAI_BASE_URL", "")
            save_env_value("OPENAI_API_KEY", "")
        save_config(config)
        print(f"Default model set to: {selected} (via Nous Portal)")
        # Offer Tool Gateway enablement for paid subscribers
        prompt_enable_tool_gateway(config)
    else:
        print("No change.")


def _model_flow_openai_codex(config, current_model=""):
    """OpenAI Codex provider: ensure logged in, then pick model."""
    from superforecasting_agent.runtime.auth import (
        get_codex_auth_status,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
        _login_openai_codex,
        PROVIDER_REGISTRY,
        DEFAULT_CODEX_BASE_URL,
    )
    from superforecasting_agent.runtime.codex_models import get_codex_model_ids

    status = get_codex_auth_status()
    if status.get("logged_in"):
        print("  OpenAI Codex credentials: ✓")
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
            print("Starting a fresh OpenAI Codex login...")
            print()
            try:
                mock_args = argparse.Namespace()
                _login_openai_codex(
                    mock_args,
                    PROVIDER_REGISTRY["openai-codex"],
                    force_new_login=True,
                )
            except SystemExit:
                print("Login cancelled or failed.")
                return
            except Exception as exc:
                print(f"Login failed: {exc}")
                return
            status = get_codex_auth_status()
            if not status.get("logged_in"):
                print("Login failed.")
                return
        elif choice == "3":
            return
    else:
        print("Not logged into OpenAI Codex. Starting login...")
        print()
        try:
            mock_args = argparse.Namespace()
            _login_openai_codex(mock_args, PROVIDER_REGISTRY["openai-codex"])
        except SystemExit:
            print("Login cancelled or failed.")
            return
        except Exception as exc:
            print(f"Login failed: {exc}")
            return

    _codex_token = None
    # Prefer credential pool (where `superforecasting-agent auth` stores
    # device_code tokens), fall back to legacy provider state.
    try:
        _codex_status = get_codex_auth_status()
        if _codex_status.get("logged_in"):
            _codex_token = _codex_status.get("api_key")
    except Exception:
        pass
    if not _codex_token:
        try:
            from superforecasting_agent.runtime.auth import resolve_codex_runtime_credentials

            _codex_creds = resolve_codex_runtime_credentials()
            _codex_token = _codex_creds.get("api_key")
        except Exception:
            pass

    codex_models = get_codex_model_ids(access_token=_codex_token)

    selected = _prompt_model_selection(codex_models, current_model=current_model)
    if selected:
        _save_model_choice(selected)
        _update_config_for_provider("openai-codex", DEFAULT_CODEX_BASE_URL)
        print(f"Default model set to: {selected} (via OpenAI Codex)")
    else:
        print("No change.")


def _model_flow_xai_oauth(_config, current_model="", *, args=None):
    """xAI Grok OAuth (SuperGrok Subscription) provider: ensure logged in, then pick model."""
    from superforecasting_agent.runtime.auth import (
        get_xai_oauth_auth_status,
        _prompt_model_selection,
        _save_model_choice,
        _update_config_for_provider,
        resolve_xai_oauth_runtime_credentials,
        _login_xai_oauth,
        DEFAULT_XAI_OAUTH_BASE_URL,
        PROVIDER_REGISTRY,
    )
    from superforecasting_agent.runtime.models import _PROVIDER_MODELS

    status = get_xai_oauth_auth_status()
    if status.get("logged_in"):
        print("  xAI Grok OAuth (SuperGrok Subscription) credentials: ✓")
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
            print("Starting a fresh xAI OAuth login...")
            print()
            try:
                # Forward CLI flags from ``superforecasting-agent model --manual-paste``
                # / ``--no-browser`` / ``--timeout`` into the loopback
                # login. Without this, browser-only remotes (#26923)
                # can't reach the manual-paste path via ``superforecasting-agent model``.
                mock_args = argparse.Namespace(
                    manual_paste=bool(getattr(args, "manual_paste", False)),
                    no_browser=bool(getattr(args, "no_browser", False)),
                    timeout=getattr(args, "timeout", None),
                )
                _login_xai_oauth(
                    mock_args,
                    PROVIDER_REGISTRY["xai-oauth"],
                    force_new_login=True,
                )
            except SystemExit:
                print("Login cancelled or failed.")
                return
            except Exception as exc:
                print(f"Login failed: {exc}")
                return
        elif choice == "3":
            return
    else:
        print("Not logged into xAI Grok OAuth (SuperGrok Subscription). Starting login...")
        print()
        try:
            mock_args = argparse.Namespace(
                manual_paste=bool(getattr(args, "manual_paste", False)),
                no_browser=bool(getattr(args, "no_browser", False)),
                timeout=getattr(args, "timeout", None),
            )
            _login_xai_oauth(mock_args, PROVIDER_REGISTRY["xai-oauth"])
        except SystemExit:
            print("Login cancelled or failed.")
            return
        except Exception as exc:
            print(f"Login failed: {exc}")
            return

    # Resolve a usable base URL.  ``resolve_xai_oauth_runtime_credentials``
    # only reads from the auth.json singleton — but credentials may legitimately
    # live only in the pool (e.g. after
    # ``superforecasting-agent auth add xai-oauth``). Fall back to the default
    # base URL in that case so the model picker still completes successfully
    # instead of bailing out with
    # ``Could not resolve xAI OAuth credentials``.
    base_url = DEFAULT_XAI_OAUTH_BASE_URL
    try:
        creds = resolve_xai_oauth_runtime_credentials()
        base_url = (creds.get("base_url") or "").strip().rstrip("/") or base_url
    except Exception:
        pass

    models = list(_PROVIDER_MODELS.get("xai-oauth") or _PROVIDER_MODELS.get("xai") or [])
    selected = _prompt_model_selection(models, current_model=current_model or (models[0] if models else "grok-4.3"))
    if selected:
        _save_model_choice(selected)
        _update_config_for_provider("xai-oauth", base_url)
        print(f"Default model set to: {selected} (via xAI Grok OAuth — SuperGrok Subscription)")
    else:
        print("No change.")
