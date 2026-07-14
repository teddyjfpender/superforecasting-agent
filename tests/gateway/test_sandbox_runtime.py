import json

from gateway.sandbox_runtime import (
    KubernetesSandboxRuntime,
    KubernetesSandboxSpec,
    sandbox_name,
)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return object()


def test_sandbox_identity_is_stable_and_thread_scoped():
    assert sandbox_name("T1/C1/100.1") == sandbox_name("T1/C1/100.1")
    assert sandbox_name("T1/C1/100.1") != sandbox_name("T1/C1/100.2")
    assert len(sandbox_name("T1/C1/100.1")) <= 63


def test_rejects_mutable_latest_image():
    import pytest

    with pytest.raises(ValueError, match="latest"):
        KubernetesSandboxRuntime(KubernetesSandboxSpec(image="registry/agent:latest"))


def test_rejects_option_like_kubernetes_identity():
    import pytest

    with pytest.raises(ValueError, match="DNS labels"):
        KubernetesSandboxRuntime(KubernetesSandboxSpec(
            image="registry/agent:fixed", namespace="--kubeconfig",
        ))


def test_manifest_is_hardened_and_contains_no_credentials():
    runtime = KubernetesSandboxRuntime(KubernetesSandboxSpec(
        image="agent@sha256:abc",
        labels={"superforecasting.run/conversation": "attacker"},
    ))
    manifest = runtime.manifest("T1/C1/100.1")
    pod = manifest["spec"]
    container = pod["containers"][0]

    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"] == {"drop": ["ALL"]}
    assert "env" not in container and "envFrom" not in container
    assert "secret" not in json.dumps(manifest).lower()
    assert manifest["metadata"]["labels"]["superforecasting.run/conversation"] != "attacker"


def test_lifecycle_uses_argv_and_reuses_thread_name():
    recorder = Recorder()
    runtime = KubernetesSandboxRuntime(
        KubernetesSandboxSpec(image="registry/agent:fixed"), runner=recorder
    )

    name = runtime.ensure("T1/C1/100.1")
    runtime.execute("T1/C1/100.1", ["python", "-m", "worker"], input="{}")
    runtime.delete("T1/C1/100.1")

    assert recorder.calls[0][0][-3:] == ["apply", "-f", "-"]
    assert f"pod/{name}" in recorder.calls[1][0]
    assert recorder.calls[2][0][-4:] == [f"pod/{name}", "--", "python", "-m", "worker"][-4:]
    assert recorder.calls[3][0][-2:] == ["--ignore-not-found=true", "--wait=false"]
