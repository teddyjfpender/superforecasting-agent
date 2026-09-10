"""Provider-picker catalog: preserve configuration templates beside resolved values."""

def named_custom_provider_map(cfg) -> dict[str, dict[str, str]]:
    from superforecasting_agent.runtime.config import read_raw_config, get_compatible_custom_providers
    from superforecasting_agent.runtime.auth import resolve_provider, AuthError

    # Build lookups of raw (un-expanded) templates keyed by a
    # stable identity. We intentionally bypass
    # ``get_compatible_custom_providers(read_raw_config())`` here because
    # its ``_normalize_custom_provider_entry`` step calls ``urlparse()``
    # on ``base_url`` and drops any entry whose ``base_url`` is itself an
    # env-ref template (e.g. ``${NEURALWATT_API_BASE}``). Dropping those
    # entries is exactly how env-ref preservation fails for the user
    # config that motivated this fix.
    raw_api_key_refs: dict[tuple, str] = {}
    raw_base_url_refs: dict[tuple, str] = {}
    raw_cfg = read_raw_config()

    def _record_raw(
        name: str,
        provider_key: str,
        model: str,
        api_key: str,
        base_url: str,
    ) -> None:
        template = str(api_key or "").strip()
        base_template = str(base_url or "").strip()
        name = str(name or "").strip()
        provider_key = str(provider_key or "").strip()
        model = str(model or "").strip()
        # Index by every plausible identity the loaded (expanded) config
        # might present: (name), (name, model), (provider_key), and
        # (provider_key, model). Case-insensitive on name/provider_key so
        # the loaded entry matches regardless of display casing.
        identities = []
        if name:
            identities.extend(((name.lower(),), (name.lower(), model)))
        if provider_key:
            identities.extend(
                ((provider_key.lower(),), (provider_key.lower(), model))
            )
        if "${" in template:
            for identity in identities:
                raw_api_key_refs.setdefault(identity, template)
        if "${" in base_template:
            for identity in identities:
                raw_base_url_refs.setdefault(identity, base_template)

    raw_list = raw_cfg.get("custom_providers")
    if isinstance(raw_list, list):
        for raw_entry in raw_list:
            if not isinstance(raw_entry, dict):
                continue
            _record_raw(
                raw_entry.get("name", ""),
                "",
                raw_entry.get("model", "") or raw_entry.get("default_model", ""),
                raw_entry.get("api_key", ""),
                raw_entry.get("base_url", "")
                or raw_entry.get("url", "")
                or raw_entry.get("api", ""),
            )
    raw_providers = raw_cfg.get("providers")
    if isinstance(raw_providers, dict):
        for raw_key, raw_entry in raw_providers.items():
            if not isinstance(raw_entry, dict):
                continue
            _record_raw(
                raw_entry.get("name", "") or raw_key,
                raw_key,
                raw_entry.get("model", "") or raw_entry.get("default_model", ""),
                raw_entry.get("api_key", ""),
                raw_entry.get("base_url", "")
                or raw_entry.get("url", "")
                or raw_entry.get("api", ""),
            )

    def _lookup_ref(
        refs: dict[tuple, str],
        name: str,
        provider_key: str,
        model: str,
    ) -> str:
        name_lc = str(name or "").strip().lower()
        pkey_lc = str(provider_key or "").strip().lower()
        model = str(model or "").strip()
        for identity in (
            (pkey_lc, model),
            (pkey_lc,),
            (name_lc, model),
            (name_lc,),
        ):
            if identity[0] and identity in refs:
                return refs[identity]
        return ""

    custom_provider_map = {}
    for entry in get_compatible_custom_providers(cfg):
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        base_url = (entry.get("base_url") or "").strip()
        if not name or not base_url:
            continue
        key = "custom:" + name.lower().replace(" ", "-")
        provider_key = (entry.get("provider_key") or "").strip()
        if provider_key:
            try:
                resolve_provider(provider_key)
            except AuthError:
                key = provider_key
        custom_provider_map[key] = {
            "name": name,
            "base_url": base_url,
            "api_key": entry.get("api_key", ""),
            "key_env": entry.get("key_env", ""),
            "model": entry.get("model", ""),
            "api_mode": entry.get("api_mode", ""),
            "provider_key": provider_key,
            "api_key_ref": _lookup_ref(
                raw_api_key_refs, name, provider_key, entry.get("model", "")
            ),
            "base_url_ref": _lookup_ref(
                raw_base_url_refs, name, provider_key, entry.get("model", "")
            ),
        }
    return custom_provider_map

