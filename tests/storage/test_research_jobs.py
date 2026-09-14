"""Scheduled and event triggers share frozen input and exclusive job ownership."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from superforecasting_agent.storage.research_jobs import JobTriggerJournal


def test_frozen_trigger_reopen_and_conflicting_redelivery(tmp_path):
    journal = JobTriggerJournal(tmp_path)
    identity = journal.admit({'id': 'job', 'prompt': 'Original'}, 'webhook:route:delivery', 'a' * 64)
    reopened = JobTriggerJournal(tmp_path)
    assert reopened.admit({'id': 'job', 'prompt': 'Edited later'}, 'webhook:route:delivery', 'a' * 64) == identity
    assert reopened.get(identity)['specification']['prompt'] == 'Original'
    with pytest.raises(ValueError, match='conflicts'):
        reopened.admit({'id': 'job'}, 'webhook:route:delivery', 'b' * 64)


def test_scheduled_and_event_claims_serialize_the_same_job(tmp_path):
    journal = JobTriggerJournal(tmp_path)
    identities = [journal.admit({'id': 'job'}, key, 'a' * 64) for key in ('scheduled:date', 'webhook:delivery')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        owners = list(pool.map(journal.claim, identities))
    assert sum(owner is not None for owner in owners) == 1
    winner = next(index for index, owner in enumerate(owners) if owner is not None)
    owner = owners[winner]
    with pytest.raises(ValueError, match='another execution owner'):
        journal.finish(identities[winner], 'stale-owner', 'completed', {'output': 'wrong'})
    journal.finish(identities[winner], owner, 'completed', {'output': 'Saved'})
    journal.finish(identities[winner], owner, 'completed', {'output': 'Saved'})
    with pytest.raises(ValueError, match='different outcome'):
        journal.finish(identities[winner], owner, 'failed', {'error': 'late'})
    assert journal.claim(identities[winner]) is None
    assert journal.claim(identities[1 - winner]) is not None


@pytest.mark.parametrize('key,digest', [(42, 'a' * 64), ('', 'a' * 64), ('x' * 1025, 'a' * 64), ('event', 'not-a-digest')])
def test_invalid_trigger_identity_is_rejected_before_admission(tmp_path, key, digest):
    journal = JobTriggerJournal(tmp_path)
    with pytest.raises(ValueError, match='identities'):
        journal.admit({'id': 'job'}, key, digest)


def test_real_exited_owner_is_interrupted_without_reexecution(tmp_path):
    import subprocess
    import sys

    code = '''from pathlib import Path
import sys
from superforecasting_agent.storage.research_jobs import JobTriggerJournal
journal = JobTriggerJournal(Path(sys.argv[1]))
identity = journal.admit({'id': 'job'}, 'webhook:delivery', 'a' * 64)
assert journal.claim(identity)
print(identity)
'''
    child = subprocess.run([sys.executable, '-c', code, str(tmp_path)], capture_output=True, text=True, timeout=15, check=True)
    identity = child.stdout.strip()
    journal = JobTriggerJournal(tmp_path)
    assert journal.recover() == 1
    assert journal.recover() == 0
    assert journal.get(identity)['state'] == 'interrupted'
    assert journal.get(identity)['result']['automatic_retry'] is False
    assert journal.claim(identity) is None


def test_live_and_unverifiable_owners_are_never_reclaimed(tmp_path):
    import sqlite3

    journal = JobTriggerJournal(tmp_path)
    identity = journal.admit({'id': 'job'}, 'event', 'a' * 64)
    assert journal.claim(identity)
    assert journal.recover() == 0
    with closing(sqlite3.connect(journal.path)) as db, db:
        db.execute("UPDATE triggers SET owner_host='foreign-host' WHERE id=?", (identity,))
    assert journal.recover() == 0
    with closing(sqlite3.connect(journal.path)) as db, db:
        db.execute('UPDATE triggers SET owner_host=NULL,owner_pid=NULL,owner_started=NULL WHERE id=?', (identity,))
    assert journal.recover() == 0
    assert journal.get(identity)['state'] == 'running'


def test_pid_reuse_does_not_preserve_a_retired_job_claim(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import psutil

    journal = JobTriggerJournal(tmp_path)
    identity = journal.admit({'id': 'job'}, 'event', 'a' * 64)
    assert journal.claim(identity)
    recorded = journal.get(identity)['owner_started']
    monkeypatch.setattr(psutil, 'Process', lambda pid=None: SimpleNamespace(create_time=lambda: recorded + 1))
    assert journal.recover() == 1
    assert journal.get(identity)['state'] == 'interrupted'


def test_version_one_claim_migrates_without_inventing_owner_identity(tmp_path):
    import sqlite3

    journal = JobTriggerJournal(tmp_path)
    identity = journal.admit({'id': 'job'}, 'event', 'a' * 64)
    assert journal.claim(identity)
    with closing(sqlite3.connect(journal.path)) as db, db:
        for column in ('owner_host', 'owner_pid', 'owner_started'):
            db.execute(f'ALTER TABLE triggers DROP COLUMN {column}')
        db.execute('PRAGMA user_version=1')
    reopened = JobTriggerJournal(tmp_path)
    assert reopened.get(identity)['owner_pid'] is None
    assert reopened.recover() == 0
    assert reopened.get(identity)['state'] == 'running'
