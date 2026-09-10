"""Interactive Bedrock provider setup and credential selection."""

def _model_flow_bedrock_api_key(config, region, current_model=""):
    """Bedrock API Key mode — uses the OpenAI-compatible bedrock-mantle endpoint.

    For developers who don't have an AWS account but received a Bedrock API Key
    from their AWS admin. Works like any OpenAI-compatible endpoint.
    """
    from superforecasting_agent.runtime.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from superforecasting_agent.runtime.config import (
        load_config,
        save_config,
        get_env_value,
        save_env_value,
    )
    from superforecasting_agent.runtime.models import _PROVIDER_MODELS

    mantle_base_url = f"https://bedrock-mantle.{region}.api.aws/v1"

    # Prompt for API key
    existing_key = get_env_value("AWS_BEARER_TOKEN_BEDROCK") or ""
    if existing_key:
        print(f"  Bedrock API Key: {existing_key[:12]}... ✓")
    else:
        print(f"  Endpoint: {mantle_base_url}")
        print()
        from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

        try:
            api_key = masked_secret_prompt("  Bedrock API Key: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            return
        if not api_key:
            print("  Cancelled.")
            return
        save_env_value("AWS_BEARER_TOKEN_BEDROCK", api_key)
        existing_key = api_key
        print("  ✓ API key saved.")
    print()

    # Model selection — use static list (mantle doesn't need boto3 for discovery)
    model_list = _PROVIDER_MODELS.get("bedrock", [])
    print(f"  Showing {len(model_list)} curated models")

    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("  Model ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        # Save as custom provider pointing to bedrock-mantle
        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "custom"
        model["base_url"] = mantle_base_url
        model.pop("api_mode", None)  # chat_completions is the default

        # Also save region in bedrock config for reference
        bedrock_cfg = cfg.get("bedrock", {})
        if not isinstance(bedrock_cfg, dict):
            bedrock_cfg = {}
        bedrock_cfg["region"] = region
        cfg["bedrock"] = bedrock_cfg

        # Save the API key env var name so hermes knows where to find it
        save_env_value("OPENAI_API_KEY", existing_key)
        save_env_value("OPENAI_BASE_URL", mantle_base_url)

        save_config(cfg)
        deactivate_provider()

        print(f"  Default model set to: {selected} (via Bedrock API Key, {region})")
        print(f"  Endpoint: {mantle_base_url}")
    else:
        print("  No change.")


def _model_flow_bedrock(config, current_model=""):
    """AWS Bedrock provider: verify credentials, pick region, discover models.

    Uses the native Converse API via boto3 — not the OpenAI-compatible endpoint.
    Auth is handled by the AWS SDK default credential chain (env vars, profile,
    instance role), so no API key prompt is needed.
    """
    from superforecasting_agent.runtime.auth import (
        _prompt_model_selection,
        _save_model_choice,
        deactivate_provider,
    )
    from superforecasting_agent.runtime.config import load_config, save_config
    from superforecasting_agent.runtime.models import _PROVIDER_MODELS

    # 1. Check for AWS credentials
    try:
        from agent.bedrock_adapter import (
            has_aws_credentials,
            resolve_aws_auth_env_var,
            resolve_bedrock_region,
            discover_bedrock_models,
        )
    except ImportError:
        print("  ✗ boto3 is not installed. Install it with:")
        print("    pip install boto3")
        print()
        return

    if not has_aws_credentials():
        print("  ⚠ No AWS credentials detected via environment variables.")
        print("  Bedrock will use boto3's default credential chain (IMDS, SSO, etc.)")
        print()

    auth_var = resolve_aws_auth_env_var()
    if auth_var:
        print(f"  AWS credentials: {auth_var} ✓")
    else:
        print("  AWS credentials: boto3 default chain (instance role / SSO)")
    print()

    # 2. Region selection
    current_region = resolve_bedrock_region()
    try:
        region_input = input(f"  AWS Region [{current_region}]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return
    region = region_input or current_region

    # 2b. Authentication mode
    print("  Choose authentication method:")
    print()
    print("    1. IAM credential chain (recommended)")
    print("       Works with EC2 instance roles, SSO, env vars, aws configure")
    print("    2. Bedrock API Key")
    print("       Enter your Bedrock API Key directly — also supports")
    print("       team scenarios where an admin distributes keys")
    print()
    try:
        auth_choice = input("  Choice [1]: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return

    if auth_choice == "2":
        _model_flow_bedrock_api_key(config, region, current_model)
        return

    # 3. Model discovery — try live API first, fall back to static list
    print(f"  Discovering models in {region}...")
    live_models = discover_bedrock_models(region)

    if live_models:
        _EXCLUDE_PREFIXES = (
            "stability.",
            "cohere.embed",
            "twelvelabs.",
            "us.stability.",
            "us.cohere.embed",
            "us.twelvelabs.",
            "global.cohere.embed",
            "global.twelvelabs.",
        )
        _EXCLUDE_SUBSTRINGS = ("safeguard", "voxtral", "palmyra-vision")
        filtered = []
        for m in live_models:
            mid = m["id"]
            if any(mid.startswith(p) for p in _EXCLUDE_PREFIXES):
                continue
            if any(s in mid.lower() for s in _EXCLUDE_SUBSTRINGS):
                continue
            filtered.append(m)

        # Deduplicate: prefer inference profiles (us.*, global.*) over bare
        # foundation model IDs.
        profile_base_ids = set()
        for m in filtered:
            mid = m["id"]
            if mid.startswith(("us.", "global.")):
                base = mid.split(".", 1)[1] if "." in mid[3:] else mid
                profile_base_ids.add(base)

        deduped = []
        for m in filtered:
            mid = m["id"]
            if not mid.startswith(("us.", "global.")) and mid in profile_base_ids:
                continue
            deduped.append(m)

        _RECOMMENDED = [
            "us.anthropic.claude-sonnet-4-6",
            "us.anthropic.claude-opus-4-6",
            "us.anthropic.claude-haiku-4-5",
            "us.amazon.nova-pro",
            "us.amazon.nova-lite",
            "us.amazon.nova-micro",
            "deepseek.v3",
            "us.meta.llama4-maverick",
            "us.meta.llama4-scout",
        ]

        def _sort_key(m):
            mid = m["id"]
            for i, rec in enumerate(_RECOMMENDED):
                if mid.startswith(rec):
                    return (0, i, mid)
            if mid.startswith("global."):
                return (1, 0, mid)
            return (2, 0, mid)

        deduped.sort(key=_sort_key)
        model_list = [m["id"] for m in deduped]
        print(
            f"  Found {len(model_list)} text model(s) (filtered from {len(live_models)} total)"
        )
    else:
        model_list = _PROVIDER_MODELS.get("bedrock", [])
        if model_list:
            print(
                f"  Using {len(model_list)} curated models (live discovery unavailable)"
            )
        else:
            print(
                "  No models found. Check IAM permissions for bedrock:ListFoundationModels."
            )
            return

    # 4. Model selection
    if model_list:
        selected = _prompt_model_selection(model_list, current_model=current_model)
    else:
        try:
            selected = input("  Model ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            selected = None

    if selected:
        _save_model_choice(selected)

        cfg = load_config()
        model = cfg.get("model")
        if not isinstance(model, dict):
            model = {"default": model} if model else {}
            cfg["model"] = model
        model["provider"] = "bedrock"
        model["base_url"] = f"https://bedrock-runtime.{region}.amazonaws.com"
        model.pop("api_mode", None)  # bedrock_converse is auto-detected

        bedrock_cfg = cfg.get("bedrock", {})
        if not isinstance(bedrock_cfg, dict):
            bedrock_cfg = {}
        bedrock_cfg["region"] = region
        cfg["bedrock"] = bedrock_cfg

        save_config(cfg)
        deactivate_provider()

        print(f"  Default model set to: {selected} (via AWS Bedrock, {region})")
    else:
        print("  No change.")
