"""Queued event research uses scheduler execution and durable ownership."""
from unittest.mock import Mock

from cron import scheduler
from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.storage.research_jobs import JobTriggerJournal


def test_tick_drains_saved_event_once_without_any_due_schedule(monkeypatch, tmp_path):
    journal = JobTriggerJournal(get_agent_home())
    identity = journal.admit({'id': 'job', 'prompt': 'Original research'}, 'webhook:route:delivery', 'a' * 64)
    run = Mock(return_value=(True, 'Transcript', 'Finding', None))
    mark = Mock()
    monkeypatch.setattr(scheduler, 'get_due_jobs', lambda: [])
    monkeypatch.setattr(scheduler, 'run_job', run)
    monkeypatch.setattr(scheduler, 'save_job_output', lambda *args: tmp_path / 'output.md')
    monkeypatch.setattr(scheduler, '_deliver_result', Mock(return_value=None))
    monkeypatch.setattr(scheduler, 'mark_job_run', mark)
    assert scheduler.tick(verbose=False) == 1
    assert scheduler.tick(verbose=False) == 0
    run.assert_called_once_with({'id': 'job', 'prompt': 'Original research'})
    mark.assert_called_once()
    receipt = journal.get(identity)
    assert receipt['state'] == 'completed'
    assert receipt['result']['final_response'] == 'Finding'


def test_failed_status_save_is_not_retried_inside_same_execution(monkeypatch, tmp_path):
    run = Mock(return_value=(True, 'Transcript', 'Finding', None))
    mark = Mock(side_effect=OSError('status write interrupted'))
    monkeypatch.setattr(scheduler, 'run_job', run)
    monkeypatch.setattr(scheduler, 'save_job_output', lambda *args: tmp_path / 'output.md')
    monkeypatch.setattr(scheduler, '_deliver_result', Mock(return_value=None))
    monkeypatch.setattr(scheduler, 'mark_job_run', mark)
    job = {'id': 'job'}
    assert scheduler.process_job(job, trigger_key='webhook:event', input_digest='a' * 64) is False
    assert scheduler.process_job(job, trigger_key='webhook:event', input_digest='a' * 64) is False
    run.assert_called_once()
    mark.assert_called_once()


def test_profile_tick_keeps_identical_job_ids_and_event_cadence_separate(monkeypatch, tmp_path):
    from cron import jobs
    from superforecasting_agent.constants import set_agent_home_override, reset_agent_home_override

    monkeypatch.setattr(scheduler, '_agent_home', None)
    monkeypatch.setattr(scheduler, '_deliver_result', Mock(return_value=None))
    seen = []
    def run(job):
        seen.append((get_agent_home(), job['prompt']))
        return True, 'Transcript', 'Finding', None
    monkeypatch.setattr(scheduler, 'run_job', run)
    for name in ('first', 'second'):
        home = tmp_path / name
        job = {'id': 'shared', 'prompt': name, 'enabled': True, 'state': 'scheduled',
               'schedule': {'kind': 'interval', 'minutes': 60},
               'next_run_at': '2099-01-01T00:00:00+00:00', 'repeat': {'times': 2, 'completed': 0}}
        with jobs.storage_home(home):
            jobs.save_jobs([job])
        journal = JobTriggerJournal(home)
        identity = journal.admit(job, 'webhook:delivery', 'a' * 64)
        token = set_agent_home_override(home)
        try:
            assert scheduler.tick(verbose=False) == 1
        finally:
            reset_agent_home_override(token)
        with jobs.storage_home(home):
            saved = jobs.get_job('shared')
        assert saved['next_run_at'] == job['next_run_at']
        assert saved['repeat']['completed'] == 0
        assert journal.get(identity)['result']['output_file'].startswith(str(home))
    assert seen == [(tmp_path / 'first', 'first'), (tmp_path / 'second', 'second')]
