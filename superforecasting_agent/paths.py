"""Installed code locations, separate from profile data in the agent home."""

from pathlib import Path


def get_install_root() -> Path:
    """Return the source checkout or site-packages directory containing the app.

    Anchor this to the product package so relocating runtime modules does not
    change where they find sibling packages, build assets, or repository tools.
    This is a code location, not the writable profile home.
    """
    return Path(__file__).resolve().parent.parent
