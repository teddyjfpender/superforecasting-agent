"""Conversation-scoped execution sandboxes.

The gateway remains the control plane.  A sandbox is addressed by the durable
conversation key (for Slack, ``team/channel/thread_ts``), so retries and
follow-up messages reach the same Kubernetes pod without sharing a workspace
with another conversation.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence


_DNS_LABEL = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")


def sandbox_name(conversation_key: str) -> str:
    """Return a deterministic, DNS-safe name without exposing thread text."""
    digest = hashlib.sha256(conversation_key.encode("utf-8")).hexdigest()[:20]
    return f"forecast-thread-{digest}"


@dataclass(frozen=True)
class KubernetesSandboxSpec:
    image: str
    namespace: str = "superforecasting-agent"
    service_account: str = "superforecasting-agent-sandbox"
    command: tuple[str, ...] = ("sleep", "infinity")
    cpu_request: str = "250m"
    cpu_limit: str = "2"
    memory_request: str = "512Mi"
    memory_limit: str = "4Gi"
    workspace_size: str = "8Gi"
    labels: Mapping[str, str] = field(default_factory=dict)


class KubernetesSandboxRuntime:
    """Small kubectl-backed sandbox controller.

    ``kubectl`` is intentionally used instead of a Kubernetes SDK: the gateway
    already has a deployment credential boundary, and adding a large client
    dependency buys no capability here.  Callers may inject ``runner`` in tests.
    """

    def __init__(
        self,
        spec: KubernetesSandboxSpec,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        if not spec.image.strip():
            raise ValueError("A pinned sandbox image is required")
        if spec.image.rsplit("/", 1)[-1].endswith(":latest"):
            raise ValueError("Sandbox image must not use the mutable latest tag")
        if not _DNS_LABEL.fullmatch(spec.namespace) or not _DNS_LABEL.fullmatch(spec.service_account):
            raise ValueError("Kubernetes namespace and service account must be DNS labels")
        self.spec = spec
        self._runner = runner

    def manifest(self, conversation_key: str) -> dict:
        name = sandbox_name(conversation_key)
        labels = {
            **dict(self.spec.labels),
            "app.kubernetes.io/name": "superforecasting-agent-sandbox",
            "app.kubernetes.io/managed-by": "superforecasting-agent-gateway",
            "superforecasting.run/conversation": name.removeprefix("forecast-thread-"),
        }
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {"name": name, "namespace": self.spec.namespace, "labels": labels},
            "spec": {
                "serviceAccountName": self.spec.service_account,
                "automountServiceAccountToken": False,
                "restartPolicy": "Never",
                "enableServiceLinks": False,
                "securityContext": {"runAsNonRoot": True, "seccompProfile": {"type": "RuntimeDefault"}},
                "containers": [{
                    "name": "agent",
                    "image": self.spec.image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": list(self.spec.command),
                    "securityContext": {
                        "allowPrivilegeEscalation": False,
                        "readOnlyRootFilesystem": True,
                        "capabilities": {"drop": ["ALL"]},
                    },
                    "resources": {
                        "requests": {"cpu": self.spec.cpu_request, "memory": self.spec.memory_request},
                        "limits": {"cpu": self.spec.cpu_limit, "memory": self.spec.memory_limit},
                    },
                    "volumeMounts": [
                        {"name": "workspace", "mountPath": "/workspace"},
                        {"name": "tmp", "mountPath": "/tmp"},
                    ],
                    # Deliberately no env/envFrom/Secret mounts. Hosted tools
                    # receive scoped credentials through the control-plane
                    # credential broker, never through the sandbox manifest.
                }],
                "volumes": [
                    {"name": "workspace", "emptyDir": {"sizeLimit": self.spec.workspace_size}},
                    {"name": "tmp", "emptyDir": {}},
                ],
            },
        }

    def ensure(self, conversation_key: str, timeout_seconds: int = 120) -> str:
        """Create/update a sandbox and wait until its agent container is ready."""
        if timeout_seconds < 1:
            raise ValueError("Sandbox readiness timeout must be positive")
        name = sandbox_name(conversation_key)
        payload = json.dumps(self.manifest(conversation_key))
        self._run(["apply", "-f", "-"], input=payload)
        self._run([
            "wait", "--for=condition=Ready", f"pod/{name}",
            f"--timeout={int(timeout_seconds)}s",
        ])
        return name

    def execute(
        self,
        conversation_key: str,
        command: Sequence[str],
        *,
        input: str | None = None,
        timeout_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute argv in the conversation sandbox without a shell."""
        if not command:
            raise ValueError("Sandbox command cannot be empty")
        name = sandbox_name(conversation_key)
        return self._run(
            ["exec", f"pod/{name}", "--", *map(str, command)],
            input=input,
            timeout=timeout_seconds,
        )

    def delete(self, conversation_key: str) -> None:
        """Delete a sandbox idempotently."""
        self._run([
            "delete", f"pod/{sandbox_name(conversation_key)}",
            "--ignore-not-found=true", "--wait=false",
        ])

    def _run(self, args: Sequence[str], **kwargs) -> subprocess.CompletedProcess[str]:
        return self._runner(
            ["kubectl", "--namespace", self.spec.namespace, *args],
            text=True,
            check=True,
            capture_output=True,
            **kwargs,
        )
