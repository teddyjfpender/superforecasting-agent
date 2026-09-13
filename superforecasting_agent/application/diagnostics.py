"""Reproducible installation identity and final diagnostic payload admission."""

from collections.abc import Callable
from importlib import metadata


def installed_product_versions() -> dict[str, str]:
    """Report installed distributions; do not mistake source constants for a wheel."""
    result: dict[str, str] = {}
    for name in ("superforecasting-agent", "superforecasting-agent-tui"):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = "not installed (source checkout or separate environment)"
    return result


def diagnostic_payload(text: str, *, sanitize: Callable[[str], str] | None) -> str:
    """Attach installed identity and sanitize the entire composed payload once.

    Passing None is reserved for an explicit raw-output request. Presentation
    adapters choose local output or upload only after this shared boundary.
    """
    versions = installed_product_versions()
    header = "--- Installed products ---\n" + "\n".join(
        f"{name}: {version}" for name, version in versions.items()
    )
    payload = header + "\n\n" + text
    return sanitize(payload) if sanitize is not None else payload
