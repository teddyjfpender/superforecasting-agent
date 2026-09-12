"""Registry snapshots and retirement retain the resource owner's identity."""
import threading

import pytest

from superforecasting_agent.hosting.registry import SessionRegistry
from superforecasting_agent.hosting.sessions import SessionBusy, use_session


def test_enumeration_is_stable_while_membership_changes():
    registry = SessionRegistry()
    first = {'session_key': 'one'}
    registry.register('first', first)
    items, values = registry.items(), registry.values()
    registry.register('second', {'session_key': 'two'})
    registry.retire('first', lambda session: None)
    assert list(items) == [('first', first)]
    assert list(values) == [first]
    assert list(registry) == ['second']


def test_registration_collision_preserves_existing_owner():
    registry = SessionRegistry()
    original = {'session_key': 'one'}
    registry.register('runtime', original)
    with pytest.raises(SessionBusy):
        registry.register('runtime', {'session_key': 'two'})
    assert registry['runtime'] is original


def test_retirement_rejects_new_use_and_concurrent_replacement():
    registry = SessionRegistry()
    session = {'session_key': 'one'}
    registry.register('runtime', session)
    entered, release = threading.Event(), threading.Event()
    retired = []
    def finalize(value):
        entered.set()
        assert release.wait(3)
    thread = threading.Thread(target=lambda: retired.append(registry.retire('runtime', finalize)))
    thread.start()
    assert entered.wait(1)
    try:
        with pytest.raises(SessionBusy), use_session(session):
            pytest.fail('admitted during retirement')
        with pytest.raises(SessionBusy):
            registry.retire('runtime', finalize)
        with pytest.raises(SessionBusy):
            registry['runtime'] = {'session_key': 'replacement'}
    finally:
        release.set()
        thread.join(3)
    assert retired == [session]
    assert not registry
    assert registry.retire('runtime', finalize) is None


def test_interrupted_finalization_releases_admission_without_detaching():
    registry = SessionRegistry()
    session = {'session_key': 'one'}
    registry.register('runtime', session)
    def interrupted(value):
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        registry.retire('runtime', interrupted)
    assert registry['runtime'] is session
    with use_session(session):
        pass
    assert registry.retire('runtime', lambda value: None) is session


@pytest.mark.parametrize('state', [{}, {'running': True}, {'_cleanup_pending': True}])
def test_mapping_assignment_cannot_discard_existing_resource_owner(state):
    registry = SessionRegistry()
    original = {'session_key': 'one', **state}
    registry.register('runtime', original)
    registry['runtime'] = original  # assigning the identical owner is harmless
    with pytest.raises(SessionBusy, match='already registered'):
        registry['runtime'] = {'session_key': 'replacement'}
    assert registry['runtime'] is original


def test_mapping_assignment_cannot_orphan_an_inflight_build():
    registry = SessionRegistry()
    original = {'agent_build_started': True, 'agent_ready': threading.Event()}
    registry.register('runtime', original)
    with pytest.raises(SessionBusy, match='already registered'):
        registry['runtime'] = {'session_key': 'replacement'}
    assert registry['runtime'] is original
    original['agent_ready'].set()
    assert registry.retire('runtime', lambda session: None) is original
    replacement = {'session_key': 'replacement'}
    registry['runtime'] = replacement
    assert registry['runtime'] is replacement
