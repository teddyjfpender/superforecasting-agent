"""Credential-safe request construction for hosted tool workers."""

from __future__ import annotations

import os
import posixpath
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from tools.registry import CredentialRequirement, ToolRegistry


@dataclass(frozen=True)
class BrokeredRequest:
    url: str
    headers: dict[str, str]


class CredentialBroker:
    """Authorize a tool destination and inject its secret in the control plane.

    This class is transport-neutral: an HTTP endpoint or an in-process hosted
    worker can use the same policy. It never returns secrets to the tool result;
    it only produces the outbound request inside the trusted gateway process.
    """

    def __init__(self, registry: ToolRegistry, environ: dict[str, str] | None = None):
        self.registry = registry
        self.environ = os.environ if environ is None else environ

    def prepare(
        self,
        tool_name: str,
        credential_name: str,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> BrokeredRequest:
        requirement = self._find(tool_name, credential_name)
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise PermissionError("Brokered credentials require HTTPS on the default port")
        host = (parsed.hostname or "").lower()
        if host not in {item.lower() for item in requirement.hosts}:
            raise PermissionError(f"Credential {credential_name!r} is not allowed for host {host!r}")
        raw_path = parsed.path or "/"
        if parsed.fragment or "\\" in raw_path or any(
            token in raw_path.lower() for token in ("%2e", "%2f", "%5c")
        ):
            raise PermissionError("Brokered URL contains ambiguous path encoding")
        path = posixpath.normpath(unquote(raw_path))
        if raw_path.endswith("/") and not path.endswith("/"):
            path += "/"
        if not any(self._path_matches(path, prefix) for prefix in requirement.path_prefixes):
            raise PermissionError(f"Credential {credential_name!r} is not allowed for path {path!r}")
        secret = self.environ.get(requirement.env_var)
        if not secret:
            raise RuntimeError(f"Credential {credential_name!r} is not configured")
        if "\r" in secret or "\n" in secret:
            raise RuntimeError(f"Credential {credential_name!r} contains invalid header characters")
        outbound = dict(headers or {})
        if any(key.lower() == requirement.header.lower() for key in outbound):
            raise PermissionError(f"Worker cannot supply the brokered {requirement.header} header")
        outbound[requirement.header] = f"{requirement.value_prefix}{secret}"
        return BrokeredRequest(url=url, headers=outbound)

    @staticmethod
    def _path_matches(path: str, prefix: str) -> bool:
        if prefix == "/":
            return True
        boundary = prefix.rstrip("/")
        return path == boundary or path.startswith(boundary + "/")

    def _find(self, tool_name: str, credential_name: str) -> CredentialRequirement:
        for requirement in self.registry.get_credential_requirements(tool_name):
            if requirement.name == credential_name:
                return requirement
        raise PermissionError(
            f"Tool {tool_name!r} has no credential binding named {credential_name!r}"
        )
