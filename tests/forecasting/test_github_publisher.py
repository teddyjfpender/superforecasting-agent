from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
from forecasting.github.app import GitHubAppClient
from forecasting.github.capabilities import GitHubPermissionError
from forecasting.github.checks import PromotionCheckPublisher
from forecasting.github.publisher import GitHubPublisher


class _GitHub:
    def __init__(self) -> None:
        self.calls = []
        self.branches = {"main": "base-sha"}
        self.commits = {"base-sha": {"tree": {"sha": "base-tree"}}}
        self.pull = None

    def call(self, action, method, path, body=None, *, expected_statuses=()):
        self.calls.append((action, method, path, body, expected_statuses))
        suffix = path.split("/git/ref/heads/", 1)
        if method == "GET" and len(suffix) == 2:
            branch = suffix[1]
            if branch not in self.branches:
                return {"status_code": 404, "body": {"message": "Not Found"}}
            return {
                "status_code": 200,
                "body": {"object": {"sha": self.branches[branch]}},
            }
        if method == "GET" and "/git/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            return {"status_code": 200, "body": self.commits[sha]}
        if method == "POST" and path.endswith("/git/blobs"):
            digest = hashlib.sha256(body["content"].encode()).hexdigest()
            return {"status_code": 201, "body": {"sha": f"blob-{digest}"}}
        if method == "POST" and path.endswith("/git/trees"):
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            return {"status_code": 201, "body": {"sha": f"tree-{digest}"}}
        if method == "POST" and path.endswith("/git/commits"):
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            sha = f"commit-{digest}"
            self.commits[sha] = {"tree": {"sha": body["tree"]}}
            return {"status_code": 201, "body": {"sha": sha}}
        if method == "POST" and path.endswith("/git/refs"):
            self.branches[body["ref"].removeprefix("refs/heads/")] = body["sha"]
            return {"status_code": 201, "body": {"ref": body["ref"]}}
        if method == "PATCH" and "/git/ref/heads/" in path:
            self.branches[path.split("/git/ref/heads/", 1)[1]] = body["sha"]
            return {"status_code": 200, "body": {"object": {"sha": body["sha"]}}}
        if method == "POST" and path.endswith("/pulls"):
            self.pull = {"number": 7, "html_url": "https://github.test/acme/forecasts/pull/7"}
            return {"status_code": 201, "body": self.pull}
        if method == "PATCH" and path.endswith("/pulls/7"):
            return {"status_code": 200, "body": self.pull}
        raise AssertionError((action, method, path, body))


class _Response:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")

    def json(self):
        return self._body


class _ForkGitHub(_GitHub):
    def __init__(self) -> None:
        super().__init__()
        self.fork_exists = False
        self.deny_canonical = True
        self.deny_fork = False

    def call(self, action, method, path, body=None, *, expected_statuses=()):
        self.calls.append((action, method, path, body, expected_statuses))
        if method == "GET" and path == "/repos/octocat/forecasts":
            if not self.fork_exists:
                return {"status_code": 404, "body": {"message": "Not Found"}}
            return {"status_code": 200, "body": self._fork_body()}
        if method == "POST" and path == "/repos/acme/forecasts/forks":
            self.fork_exists = True
            return {"status_code": 202, "body": self._fork_body()}
        if method == "POST" and path == "/repos/acme/forecasts/git/blobs" and self.deny_canonical:
            raise GitHubPermissionError("denied", status_code=403)
        if method == "POST" and path == "/repos/octocat/forecasts/git/blobs" and self.deny_fork:
            raise GitHubPermissionError("denied", status_code=403)
        self.calls.pop()
        return super().call(action, method, path, body, expected_statuses=expected_statuses)

    @staticmethod
    def _fork_body():
        return {
            "full_name": "octocat/forecasts",
            "owner": {"login": "octocat", "id": 101},
            "parent": {"full_name": "acme/forecasts"},
            "source": {"full_name": "acme/forecasts"},
        }


def _changeset(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    changeset = control.create_changeset(
        workspace_id="desk_1",
        author_owner_ids=["owner_1"],
        affected_question_ids=["question_1"],
    )
    control.add_operation(
        changeset["id"],
        LedgerOperation(
            id="document_1",
            kind="document.update",
            target_ref="brief_1",
            payload={"path": "documents/brief.md", "content": "Current thesis."},
        ),
    )
    control.add_decision_record(
        changeset["id"],
        conclusion="The documented thesis should reflect the latest evidence.",
        evidence_refs=["source_1"],
        tests=["preview"],
    )
    return ledger, control, control.get_changeset(changeset["id"])


def test_publisher_creates_deterministic_branch_draft_pr_and_provenance(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _GitHub()
    publisher = GitHubPublisher(
        ledger,
        repository_slug="acme/forecasts",
        client=github,
    )

    result = publisher.publish(
        changeset["id"],
        tmp_path / "workspace",
        slack_thread_url="https://acme.slack.test/archives/C1/p1",
    )

    assert result["branch"] == f"forecast/changesets/{changeset['id']}"
    assert result["pr_number"] == 7
    assert result["status"] == "review_open"
    stored = control.get_changeset(changeset["id"])
    assert stored["head_sha"] == result["head_sha"]
    assert stored["pr_number"] == 7
    assert (tmp_path / "workspace" / f"attestations/{changeset['id']}/decisions.json").is_file()
    pr_call = next(call for call in github.calls if call[2].endswith("/pulls"))
    assert pr_call[3]["draft"] is True
    assert "Required human approvals" in pr_call[3]["body"]
    assert "Slack thread" in pr_call[3]["body"]
    assert "Agent-authored" in pr_call[3]["body"]


def test_republish_updates_existing_pr_and_stales_head_bound_review(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _GitHub()
    publisher = GitHubPublisher(
        ledger,
        repository_slug="acme/forecasts",
        client=github,
    )
    first = publisher.publish(changeset["id"], tmp_path / "workspace")
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        source="github",
        owner_id="reviewer_1",
        head_sha=first["head_sha"],
    )
    control.add_decision_record(
        changeset["id"],
        conclusion="A reviewer-requested clarification was added.",
    )

    second = publisher.publish(changeset["id"], tmp_path / "workspace")

    assert second["pr_number"] == first["pr_number"]
    assert second["head_sha"] != first["head_sha"]
    assert control.list_reviews(changeset["id"])[0]["stale_at"] is not None
    assert len([call for call in github.calls if call[1] == "POST" and call[2].endswith("/pulls")]) == 1
    assert len([call for call in github.calls if call[1] == "PATCH" and call[2].endswith("/pulls/7")]) == 1
    branch_updates = [
        call for call in github.calls if call[1] == "PATCH" and "/git/ref/heads/" in call[2]
    ]
    assert branch_updates[-1][3]["force"] is False


def _fork_publisher(ledger, github):
    return GitHubPublisher(
        ledger,
        repository_slug="acme/forecasts",
        client=github,
        fork_repository_slug="octocat/forecasts",
        fork_owner_login="octocat",
        fork_owner_github_user_id="101",
        fork_client=github,
    )


def test_publisher_falls_back_to_verified_owner_fork_without_force_push(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _ForkGitHub()
    result = _fork_publisher(ledger, github).publish(
        changeset["id"], tmp_path / "workspace"
    )

    assert result["repository"] == "acme/forecasts"
    assert result["head_repository"] == "octocat/forecasts"
    assert result["publication_mode"] == "owner_fork"
    assert control.get_changeset(changeset["id"])["digest"] == changeset["digest"]
    assert any(call[2] == "/repos/acme/forecasts/forks" for call in github.calls)
    pr_call = next(call for call in github.calls if call[2].endswith("/pulls"))
    assert pr_call[3]["head"] == f"octocat:{result['branch']}"
    assert not any(
        call[1] == "PATCH" and (call[3] or {}).get("force") is True
        for call in github.calls
    )


def test_fork_permission_loss_blocks_but_preserves_recoverable_changeset(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _ForkGitHub()
    publisher = _fork_publisher(ledger, github)
    publisher.publish(changeset["id"], tmp_path / "workspace")
    github.deny_fork = True

    with pytest.raises(GitHubPermissionError):
        publisher.publish(changeset["id"], tmp_path / "workspace")

    stored = control.get_changeset(changeset["id"])
    assert stored["status"] == "blocked"
    assert stored["metadata"]["github_publication_error"] == {
        "recoverable": True,
        "category": "permission_denied",
    }
    assert stored["digest"] == changeset["digest"]


def test_publisher_rejects_repository_confused_fork(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _ForkGitHub()
    github._fork_body = lambda: {
        "full_name": "octocat/forecasts",
        "owner": {"login": "octocat", "id": 999},
        "parent": {"full_name": "attacker/forecasts"},
        "source": {"full_name": "attacker/forecasts"},
    }

    with pytest.raises(PermissionError, match="identity or ancestry"):
        _fork_publisher(ledger, github).publish(
            changeset["id"], tmp_path / "workspace"
        )

    assert control.get_changeset(changeset["id"])["status"] == "blocked"


def test_app_client_uses_cached_installation_token_and_redacts_response():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    calls = []
    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if "/app/installations/77/access_tokens" in url:
            return _Response({"token": "ghs_installation_secret", "expires_at": expires}, 201)
        assert kwargs["headers"]["Authorization"] == "Bearer ghs_installation_secret"
        return _Response({"id": 901, "token": "must-not-return"}, 201)

    client = GitHubAppClient(
        app_id="1234",
        private_key=pem,
        installation_id="77",
        repository_slug="acme/forecasts",
        request=request,
    )
    path = "/repos/acme/forecasts/check-runs"
    first = client.call("check.write", "POST", path, {"name": "ledger/promotion"})
    second = client.call("check.write", "POST", path, {"name": "ledger/promotion"})

    assert first["body"] == {"id": 901, "token": "[REDACTED]"}
    assert second["body"]["id"] == 901
    assert len([call for call in calls if "/access_tokens" in call[1]]) == 1
    jwt = calls[0][2]["headers"]["Authorization"].removeprefix("Bearer ")
    assert len(jwt.split(".")) == 3
    assert "ghs_installation_secret" not in jwt


def test_app_sourced_promotion_check_binds_exact_head_and_advances_low_risk(tmp_path):
    ledger, control, changeset = _changeset(tmp_path)
    github = _GitHub()
    workspace = tmp_path / "workspace"
    published = GitHubPublisher(
        ledger,
        repository_slug="acme/forecasts",
        client=github,
    ).publish(changeset["id"], workspace)
    check_calls = []

    class _App:
        def call(self, action, method, path, body=None, *, expected_statuses=()):
            check_calls.append((action, method, path, body))
            return {"status_code": 201, "body": {"id": 902}}

    result = PromotionCheckPublisher(
        ledger,
        repository_slug="acme/forecasts",
        app_id="1234",
        client=_App(),
    ).publish(changeset["id"], workspace)

    assert result["conclusion"] == "success"
    assert result["status"] == "merge_ready"
    assert check_calls[0][0:3] == (
        "check.write",
        "POST",
        "/repos/acme/forecasts/check-runs",
    )
    assert check_calls[0][3]["name"] == "ledger/promotion"
    assert check_calls[0][3]["head_sha"] == published["head_sha"]
    with ledger._connect() as conn:
        stored = dict(conn.execute("SELECT * FROM github_promotion_checks").fetchone())
    assert stored["app_id"] == "1234"
    assert stored["head_sha"] == published["head_sha"]
