"""Integration tests for the generic webhook platform adapter.

These tests exercise end-to-end flows through the webhook adapter:
1. GitHub PR webhook → agent MessageEvent created
2. Skills config injects skill content into the prompt
3. Cross-platform delivery routes to a mock Telegram adapter
4. GitHub comment delivery invokes ``gh`` CLI (mocked subprocess)
"""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import (
    GatewayConfig,
    HomeChannel,
    Platform,
    PlatformConfig,
)
from gateway.platforms.base import MessageEvent, MessageType, SendResult
from gateway.platforms.webhook import WebhookAdapter, _INSECURE_NO_AUTH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_adapter(routes, **extra_kw) -> WebhookAdapter:
    """Create a WebhookAdapter with the given routes."""
    extra = {"host": "0.0.0.0", "port": 0, "routes": routes}
    extra.update(extra_kw)
    config = PlatformConfig(enabled=True, extra=extra)
    return WebhookAdapter(config)


def _create_app(adapter: WebhookAdapter) -> web.Application:
    """Build the aiohttp Application from the adapter."""
    app = web.Application()
    app.router.add_get("/health", adapter._handle_health)
    app.router.add_post("/webhooks/{route_name}", adapter._handle_webhook)
    return app


def _github_signature(body: bytes, secret: str) -> str:
    """Compute X-Hub-Signature-256 for *body* using *secret*."""
    return "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()


# A realistic GitHub pull_request event payload (trimmed)
GITHUB_PR_PAYLOAD = {
    "action": "opened",
    "number": 42,
    "pull_request": {
        "title": "Add webhook adapter",
        "body": "This PR adds a generic webhook platform adapter.",
        "html_url": "https://github.com/org/repo/pull/42",
        "user": {"login": "contributor"},
        "head": {"ref": "feature/webhooks"},
        "base": {"ref": "main"},
    },
    "repository": {
        "full_name": "org/repo",
        "html_url": "https://github.com/org/repo",
    },
    "sender": {"login": "contributor"},
}


# ===================================================================
# Test 1: GitHub PR webhook triggers agent
# ===================================================================

class TestGitHubPRWebhook:

    @pytest.mark.asyncio
    async def test_github_pr_webhook_triggers_agent(self):
        """POST with a realistic GitHub PR payload should:
        1. Return 202 Accepted
        2. Call handle_message with a MessageEvent
        3. The event text contains the rendered prompt
        4. The event source has chat_type 'webhook'
        """
        secret = "gh-webhook-test-secret"
        routes = {
            "github-pr": {
                "secret": secret,
                "events": ["pull_request"],
                "prompt": (
                    "Review PR #{number} by {sender.login}: "
                    "{pull_request.title}\n\n{pull_request.body}"
                ),
                "deliver": "log",
            }
        }
        adapter = _make_adapter(routes)

        captured_events: list[MessageEvent] = []

        async def _capture(event: MessageEvent):
            captured_events.append(event)

        adapter.handle_message = _capture

        app = _create_app(adapter)
        body = json.dumps(GITHUB_PR_PAYLOAD).encode()
        sig = _github_signature(body, secret)

        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/webhooks/github-pr",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": sig,
                    "X-GitHub-Delivery": "gh-delivery-001",
                },
            )
            assert resp.status == 202
            data = await resp.json()
            assert data["status"] == "accepted"
            assert data["route"] == "github-pr"
            assert data["event"] == "pull_request"
            assert data["delivery_id"] == "gh-delivery-001"

        # Let the asyncio.create_task fire
        await asyncio.sleep(0.05)

        assert len(captured_events) == 1
        event = captured_events[0]
        assert "Review PR #42 by contributor" in event.text
        assert "Add webhook adapter" in event.text
        assert event.source.chat_type == "webhook"
        assert event.source.platform == Platform.WEBHOOK
        assert "github-pr" in event.source.chat_id
        assert event.message_id == "gh-delivery-001"


# ===================================================================
# Test 2: Skills injected into prompt
# ===================================================================

class TestSkillsInjection:

    @pytest.mark.asyncio
    async def test_skills_injected_into_prompt(self):
        """When a route has skills: [code-review], the adapter should
        call build_skill_invocation_message() and use its output as the
        prompt instead of the raw template render."""
        routes = {
            "pr-review": {
                "secret": _INSECURE_NO_AUTH,
                "events": ["pull_request"],
                "prompt": "Review this PR: {pull_request.title}",
                "skills": ["code-review"],
            }
        }
        adapter = _make_adapter(routes)

        captured_events: list[MessageEvent] = []

        async def _capture(event: MessageEvent):
            captured_events.append(event)

        adapter.handle_message = _capture

        skill_content = (
            "You are a code reviewer. Review the following:\n"
            "Review this PR: Add webhook adapter"
        )

        # The imports are lazy (inside the handler), so patch the source module
        with patch(
            "agent.skill_commands.build_skill_invocation_message",
            return_value=skill_content,
        ) as mock_build, patch(
            "agent.skill_commands.get_skill_commands",
            return_value={"/code-review": {"name": "code-review"}},
        ):
            app = _create_app(adapter)
            async with TestClient(TestServer(app)) as cli:
                resp = await cli.post(
                    "/webhooks/pr-review",
                    json=GITHUB_PR_PAYLOAD,
                    headers={
                        "X-GitHub-Event": "pull_request",
                        "X-GitHub-Delivery": "skill-test-001",
                    },
                )
                assert resp.status == 202

            await asyncio.sleep(0.05)

            assert len(captured_events) == 1
            event = captured_events[0]
            # The prompt should be the skill content, not the raw template
            assert "You are a code reviewer" in event.text
            mock_build.assert_called_once()


# ===================================================================
# Test 3: Cross-platform delivery (webhook → Telegram)
# ===================================================================

class TestCrossPlatformDelivery:

    @pytest.mark.asyncio
    async def test_cross_platform_delivery(self):
        """When deliver='telegram', the response is routed to the
        Telegram adapter via gateway_runner.adapters."""
        routes = {
            "alerts": {
                "secret": _INSECURE_NO_AUTH,
                "prompt": "Alert: {message}",
                "deliver": "telegram",
                "deliver_extra": {"chat_id": "12345"},
            }
        }
        adapter = _make_adapter(routes)
        adapter.handle_message = AsyncMock()

        # Set up a mock gateway runner with a mock Telegram adapter
        mock_tg_adapter = AsyncMock()
        mock_tg_adapter.send = AsyncMock(return_value=SendResult(success=True))

        mock_runner = MagicMock()
        mock_runner.adapters = {Platform.TELEGRAM: mock_tg_adapter}
        mock_runner.config = GatewayConfig(
            platforms={Platform.TELEGRAM: PlatformConfig(enabled=True, token="fake")}
        )
        adapter.gateway_runner = mock_runner

        # First, simulate a webhook POST to set up delivery_info
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/webhooks/alerts",
                json={"message": "Server is on fire!"},
                headers={"X-GitHub-Delivery": "alert-001"},
            )
            assert resp.status == 202

        # The adapter should have stored delivery info
        chat_id = "webhook:alerts:alert-001"
        assert chat_id in adapter._delivery_info

        # Now call send() as if the agent has finished
        result = await adapter.send(chat_id, "I've acknowledged the alert.")

        assert result.success is True
        mock_tg_adapter.send.assert_awaited_once_with(
            "12345", "I've acknowledged the alert.", metadata=None
        )
        # Delivery info is retained after send() so interim status messages
        # don't strand the final response (TTL-based cleanup happens on POST).
        assert chat_id in adapter._delivery_info


# ===================================================================
# Test 4: GitHub comment delivery via gh CLI
# ===================================================================

class TestGitHubCommentDelivery:

    @pytest.mark.asyncio
    async def test_github_comment_delivery(self):
        """When deliver='github_comment', the adapter invokes
        ``gh pr comment`` via subprocess.run (mocked)."""
        routes = {
            "pr-bot": {
                "secret": _INSECURE_NO_AUTH,
                "prompt": "Review: {pull_request.title}",
                "deliver": "github_comment",
                "deliver_extra": {
                    "repo": "{repository.full_name}",
                    "pr_number": "{number}",
                },
            }
        }
        adapter = _make_adapter(routes)
        adapter.handle_message = AsyncMock()

        # POST a webhook to set up delivery info
        app = _create_app(adapter)
        async with TestClient(TestServer(app)) as cli:
            resp = await cli.post(
                "/webhooks/pr-bot",
                json=GITHUB_PR_PAYLOAD,
                headers={
                    "X-GitHub-Event": "pull_request",
                    "X-GitHub-Delivery": "gh-comment-001",
                },
            )
            assert resp.status == 202

        chat_id = "webhook:pr-bot:gh-comment-001"
        assert chat_id in adapter._delivery_info

        # Verify deliver_extra was rendered with payload data
        delivery = adapter._delivery_info[chat_id]
        assert delivery["deliver_extra"]["repo"] == "org/repo"
        assert delivery["deliver_extra"]["pr_number"] == "42"

        # Mock subprocess.run and call send()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Comment posted"
        mock_result.stderr = ""

        with patch(
            "gateway.platforms.webhook.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            result = await adapter.send(
                chat_id, "LGTM! The code looks great."
            )

        assert result.success is True
        mock_run.assert_called_once_with(
            [
                "gh", "pr", "comment", "42",
                "--repo", "org/repo",
                "--body", "LGTM! The code looks great.",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Delivery info is retained after send() so interim status messages
        # don't strand the final response (TTL-based cleanup happens on POST).
        assert chat_id in adapter._delivery_info


@pytest.mark.asyncio
async def test_authenticated_job_binding_is_durable_and_does_not_run_route_prompt(monkeypatch, tmp_path):
    from cron import jobs
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.research_jobs import JobTriggerJournal

    home = get_agent_home()
    monkeypatch.setattr(jobs, 'JOBS_FILE', home / 'cron' / 'jobs.json')
    monkeypatch.setattr(jobs, 'get_job', lambda identity: {'id': identity, 'prompt': 'Stored research', 'enabled': True})
    adapter = _make_adapter({'source': {'secret': 'fixture-secret', 'cron_job': 'job', 'prompt': 'Must not run'}})
    body = b'{"event_type":"published"}'
    headers = {'X-Hub-Signature-256': _github_signature(body, 'fixture-secret'), 'X-Request-ID': 'delivery'}
    async with TestClient(TestServer(_create_app(adapter))) as client:
        unauthorized = await client.post('/webhooks/source', data=body)
        assert unauthorized.status == 401
        first = await client.post('/webhooks/source', data=body, headers=headers)
        assert first.status == 202
        receipt = await first.json()
        repeat = await client.post('/webhooks/source', data=body, headers=headers)
        assert (await repeat.json())['trigger_id'] == receipt['trigger_id']
        changed = b'{"event_type":"revised"}'
        bad = await client.post('/webhooks/source', data=changed, headers={**headers, 'X-Hub-Signature-256': _github_signature(changed, 'fixture-secret')})
        assert bad.status == 409
    saved = JobTriggerJournal(home).get(receipt['trigger_id'])
    assert saved['state'] == 'accepted'
    assert saved['specification']['prompt'] == 'Stored research'


@pytest.mark.asyncio
async def test_job_route_reads_and_admits_only_its_explicit_profile(monkeypatch, tmp_path):
    from cron import jobs
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent import profile_paths
    from superforecasting_agent.storage.research_jobs import JobTriggerJournal

    target = tmp_path / 'target'
    with jobs.storage_home(target):
        jobs.save_jobs([{'id': 'shared', 'prompt': 'Target research', 'enabled': True}])
    with jobs.storage_home(get_agent_home()):
        jobs.save_jobs([{'id': 'shared', 'prompt': 'Wrong profile', 'enabled': True}])
    monkeypatch.setattr(profile_paths, 'resolve_profile_env', lambda name: str(target) if name == 'target' else pytest.fail('unexpected profile'))
    adapter = _make_adapter({'source': {'secret': 'fixture-secret', 'cron_job': 'shared', 'profile': 'target'}})
    body = b'{}'
    async with TestClient(TestServer(_create_app(adapter))) as client:
        response = await client.post('/webhooks/source', data=body, headers={
            'X-Hub-Signature-256': _github_signature(body, 'fixture-secret'), 'X-Request-ID': 'event'})
        assert response.status == 202
        identity = (await response.json())['trigger_id']
    assert JobTriggerJournal(target).get(identity)['specification']['prompt'] == 'Target research'
    # The ingress profile keeps only the immutable delivery binding; execution
    # remains owned by the requested target profile.
    assert not JobTriggerJournal(get_agent_home()).pending()


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ['job', 'profile'])
async def test_replayed_delivery_cannot_follow_edited_route_after_restart(monkeypatch, tmp_path, change):
    from cron import jobs
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent import profile_paths
    from superforecasting_agent.storage.research_jobs import JobTriggerJournal

    home = get_agent_home()
    other = tmp_path / 'other'
    for target in (home, other):
        with jobs.storage_home(target):
            jobs.save_jobs([{'id': name, 'prompt': name, 'enabled': True}
                            for name in ('original', 'replacement')])
    monkeypatch.setattr(profile_paths, 'resolve_profile_env', lambda name: str(other))
    route = {'secret': 'fixture-secret', 'cron_job': 'original'}
    body = b'{"event_type":"published"}'
    headers = {'X-Hub-Signature-256': _github_signature(body, 'fixture-secret'),
               'X-Request-ID': 'same-delivery'}
    adapter = _make_adapter({'source': route})
    async with TestClient(TestServer(_create_app(adapter))) as client:
        response = await client.post('/webhooks/source', data=body, headers=headers)
        assert response.status == 202
        identity = (await response.json())['trigger_id']
    changed = {**route, **({'cron_job': 'replacement'} if change == 'job' else {'profile': 'other'})}
    restarted = _make_adapter({'source': changed})
    async with TestClient(TestServer(_create_app(restarted))) as client:
        replay = await client.post('/webhooks/source', data=body, headers=headers)
        assert replay.status == 409
    assert [row['id'] for row in JobTriggerJournal(home).pending()] == [identity]
    assert not JobTriggerJournal(other).pending()


@pytest.mark.asyncio
async def test_failed_target_admission_retries_only_original_binding(monkeypatch):
    from cron import jobs
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.research_jobs import JobTriggerJournal

    home = get_agent_home()
    with jobs.storage_home(home):
        jobs.save_jobs([{'id': name, 'prompt': name} for name in ('original', 'replacement')])
    original_admit = JobTriggerJournal.admit
    calls = []
    def interrupted_admit(self, *args):
        calls.append(args)
        if len(calls) == 1:
            raise OSError('Injected target write failure')
        return original_admit(self, *args)
    monkeypatch.setattr(JobTriggerJournal, 'admit', interrupted_admit)
    body = b'{}'
    headers = {'X-Hub-Signature-256': _github_signature(body, 'fixture-secret'),
               'X-Request-ID': 'retry'}
    for name, expected in [('original', 503), ('replacement', 409), ('original', 202)]:
        adapter = _make_adapter({'source': {'secret': 'fixture-secret', 'cron_job': name}})
        async with TestClient(TestServer(_create_app(adapter))) as client:
            response = await client.post('/webhooks/source', data=body, headers=headers)
            assert response.status == expected
    pending = JobTriggerJournal(home).pending()
    assert len(pending) == 1
    assert pending[0]['job_id'] == 'original'
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('execution', ['script', 'agent'])
async def test_signed_job_cannot_commit_forecast_and_replay_does_not_rerun(monkeypatch, tmp_path, execution):
    """Exercise HTTP, scheduler, real execution and ledger with controlled model replies."""
    from pathlib import Path

    from cron import jobs, scheduler
    from forecasting.ledger import ForecastLedger, allow_ledger_writes
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.storage.research_jobs import JobTriggerJournal

    home = get_agent_home()
    monkeypatch.setattr(scheduler, '_agent_home', None)
    # A permissive launching shell must not weaken an unattended job's policy.
    monkeypatch.setenv('FORECAST_COMMIT_POLICY', 'commit')
    ledger_path = home / 'forecast-test.db'
    ledger = ForecastLedger(ledger_path)
    with allow_ledger_writes('seed active forecast'):
        question = ledger.create_question(
            title='Will the synthetic observation occur?',
            resolution_criteria='YES if the fixture observes the event by 2099-01-01.',
            close_time='2099-01-01T00:00:00Z',
        )
        ledger.create_snapshot(question_id=question.id, probability_or_distribution=0.4,
                               rationale='Initial synthetic estimate.')
    scripts = home / 'scripts'
    scripts.mkdir(exist_ok=True)
    attempts = tmp_path / 'attempts'
    script = scripts / 'attempt_update.py'
    script.write_text(
        'import sys\nfrom pathlib import Path\n'
        f'sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})\n'
        'from forecasting.ledger import ForecastLedger, allow_ledger_writes\n'
        f'with Path({str(attempts)!r}).open("a") as f: f.write("attempt\\n")\n'
        f'ledger = ForecastLedger({str(ledger_path)!r})\n'
        'with allow_ledger_writes("unattended script"):\n'
        f'    ledger.create_snapshot(question_id={question.id!r}, '
        'probability_or_distribution=0.9, rationale="Unattended changed estimate.")\n',
        encoding='utf-8',
    )
    job = {'id': 'source-job', 'prompt': 'Collect source observations', 'enabled': True,
           'no_agent': True, 'script': script.name, 'deliver': 'local',
           'schedule': {'kind': 'interval', 'minutes': 60},
           'next_run_at': '2099-01-01T00:00:00+00:00'}
    if execution == 'agent':
        from tests.run_agent.test_tool_call_guardrail_runtime import (
            _make_agent, _mock_response, _mock_tool_call,
        )

        agent = _make_agent('forecast_ledger')
        arguments = {'db': str(ledger_path), 'action': 'update_forecast',
                     'question_id': question.id, 'probability': 0.9,
                     'rationale': 'New synthetic observation warrants a proposed revision.',
                     'reference_class': {'name': 'Synthetic events', 'inclusion_criteria': 'Comparable fixtures', 'base_rate': 0.4},
                     'require_components': False, 'require_structured_reasoning': False,
                     'require_panel': False}
        model_calls = agent.client.chat.completions.create
        evidence = {'db': str(ledger_path), 'action': 'add_evidence',
                    'question_id': question.id, 'source_or_note': 'Synthetic source release',
                    'claim': 'The controlled source reports a new positive observation.'}
        model_calls.side_effect = [
            _mock_response(content='', finish_reason='tool_calls', tool_calls=[
                _mock_tool_call('forecast_ledger', json.dumps(evidence), 'evidence')]),
            _mock_response(content='', finish_reason='tool_calls', tool_calls=[
                _mock_tool_call('forecast_ledger', json.dumps(arguments), 'propose')]),
            _mock_response(content='Research complete; proposed revision awaits approval.'),
        ]
        class PreparedAgent(type(agent)):
            def __new__(cls, **kwargs):
                agent._session_db = kwargs['session_db']
                agent.session_id = kwargs['session_id']
                return agent
        monkeypatch.setattr('run_agent.AIAgent', PreparedAgent)
        monkeypatch.setattr('tools.mcp_tool.discover_mcp_tools', lambda: [])
        monkeypatch.setattr(
            'superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider',
            lambda **kwargs: {'provider': 'openrouter', 'api_key': 'test-key',
                              'base_url': 'https://example.invalid/v1'},
        )
        job.pop('script')
        job.pop('no_agent')
    with jobs.storage_home(home):
        jobs.save_jobs([job])
    adapter = _make_adapter({'source': {'secret': 'fixture-secret', 'cron_job': job['id']}})
    body = b'{"event_type":"published"}'
    headers = {'X-Hub-Signature-256': _github_signature(body, 'fixture-secret'),
               'X-Request-ID': 'source-release'}
    async with TestClient(TestServer(_create_app(adapter))) as client:
        response = await client.post('/webhooks/source', data=body, headers=headers)
        assert response.status == 202
        identity = (await response.json())['trigger_id']
        assert await asyncio.to_thread(scheduler.tick, verbose=False) == 1
        receipt = JobTriggerJournal(home).get(identity)
        if execution == 'script':
            assert receipt['state'] == 'failed'
            assert 'proposal-only' in receipt['result']['error']
        else:
            assert receipt['state'] == 'completed', receipt['result']
            assert model_calls.call_count == 3
            messages = model_calls.call_args.kwargs['messages']
            outcomes = [json.loads(message['content']) for message in messages
                        if message.get('role') == 'tool']
            assert len(outcomes) == 2
            assert outcomes[1].get('status') == 'proposal_created', outcomes
            assert outcomes[1]['proposal']['status'] == 'pending'
        repeated = await client.post('/webhooks/source', data=body, headers=headers)
        assert (await repeated.json())['trigger_id'] == identity
        assert await asyncio.to_thread(scheduler.tick, verbose=False) == 0
    if execution == 'script':
        assert attempts.read_text() == 'attempt\n'
    else:
        assert model_calls.call_count == 3
        reopened = ForecastLedger(ledger_path)
        proposal = reopened.get_forecast_update_proposal(outcomes[1]['proposal']['id'])
        assert proposal['status'] == 'pending'
        assert len(reopened.list_evidence(question.id)) == 1
    assert len(ledger.list_snapshots(question.id)) == 1
    assert ledger.get_current_snapshot(question.id).probability_or_distribution == 0.4
    with jobs.storage_home(home):
        assert jobs.get_job(job['id'])['next_run_at'] == job['next_run_at']
