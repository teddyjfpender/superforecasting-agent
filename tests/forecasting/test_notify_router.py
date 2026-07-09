"""Notification router (P2.4): event-class filtering, multi-surface fan-out,
failure isolation + surfacing, dedupe, dead-destination alerting, and the
autopilot ``--notify`` dead-end closure."""

from __future__ import annotations

import pytest

from forecasting import notify


# ── stub senders ──────────────────────────────────────────────────────────────


def _recorder():
    calls: list = []

    def _sender(ok=True, error=None):
        def _fn(route, event):
            calls.append((route.id, event.event_class, event.event_id))
            return notify.DeliveryResult(
                route_id=route.id, surface=route.surface, target=route.target,
                ok=ok, error=error,
            )
        return _fn

    return calls, _sender


@pytest.fixture()
def stores(tmp_path):
    store = notify.RouteStore(path=tmp_path / "routes.json")
    log = notify.DeliveryLog(path=tmp_path / "deliveries.json")
    return store, log


# ── event class validation ────────────────────────────────────────────────────


def test_event_rejects_unknown_class():
    with pytest.raises(ValueError):
        notify.NotifyEvent(event_class="not_a_class", title="x")


def test_route_accepts_filters():
    r = notify.NotifyRoute(surface="telegram", target="1", events=("cycle_digest",))
    assert r.accepts("cycle_digest")
    assert not r.accepts("alert")
    wild = notify.NotifyRoute(surface="slack", target="C1", events=(notify.ALL,))
    assert wild.accepts("alert") and wild.accepts("resolution")
    disabled = notify.NotifyRoute(surface="telegram", target="1", events=(notify.ALL,), enabled=False)
    assert not disabled.accepts("cycle_digest")


# ── event-class filtering + multi-surface fan-out ─────────────────────────────


def test_fan_out_respects_event_class(stores):
    store, log = stores
    store.upsert(notify.NotifyRoute(surface="telegram", target="111", events=("cycle_digest",)))
    store.upsert(notify.NotifyRoute(surface="slack", target="C1", events=(notify.ALL,)))
    store.upsert(notify.NotifyRoute(surface="telegram", target="222", events=("alert",)))

    calls, sender = _recorder()
    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": sender(), "slack": sender()})

    report = router.route(notify.NotifyEvent(event_class="cycle_digest", title="digest", body="hi"))

    delivered_ids = {r.route_id for r in report.delivered}
    # cycle_digest reaches telegram:111 (subscribed) + slack:C1 (wildcard); NOT telegram:222 (alert-only)
    assert delivered_ids == {"telegram:111", "slack:C1"}
    assert report.ok
    assert {c[0] for c in calls} == {"telegram:111", "slack:C1"}


def test_fan_out_across_surfaces(stores):
    store, log = stores
    store.upsert(notify.NotifyRoute(surface="telegram", target="1", events=(notify.ALL,)))
    store.upsert(notify.NotifyRoute(surface="slack", target="C1", events=(notify.ALL,)))
    tg_calls, tg = _recorder()
    sl_calls, sl = _recorder()
    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": tg(), "slack": sl()})

    report = router.route(notify.NotifyEvent(event_class="quorum_verdict", title="verdict"))
    assert len(report.delivered) == 2
    assert len(tg_calls) == 1 and len(sl_calls) == 1


# ── failure isolation + surfacing ─────────────────────────────────────────────


def test_failure_is_isolated_and_recorded(stores):
    store, log = stores
    store.upsert(notify.NotifyRoute(surface="telegram", target="good", events=(notify.ALL,)))
    store.upsert(notify.NotifyRoute(surface="slack", target="bad", events=(notify.ALL,)))
    _, sender = _recorder()
    router = notify.NotifyRouter(
        store=store, log=log,
        senders={"telegram": sender(ok=True), "slack": sender(ok=False, error="revoked token")},
    )

    report = router.route(notify.NotifyEvent(event_class="alert", title="a"))

    # the good binding still delivers despite the bad one failing
    assert {r.route_id for r in report.delivered} == {"telegram:good"}
    assert {r.route_id for r in report.failures} == {"slack:bad"}

    rows = {row["id"]: row for row in router.status_rows()}
    assert rows["telegram:good"]["last_status"] == "ok"
    assert rows["slack:bad"]["last_status"] == "failed"
    assert rows["slack:bad"]["last_error"] == "revoked token"
    assert rows["slack:bad"]["consecutive_failures"] == 1


def test_sender_exception_does_not_crash_router(stores):
    store, log = stores
    store.upsert(notify.NotifyRoute(surface="telegram", target="boom", events=(notify.ALL,)))

    def _explode(route, event):
        raise RuntimeError("network on fire")

    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": _explode})
    report = router.route(notify.NotifyEvent(event_class="cycle_digest", title="d"))
    assert report.failures and "network on fire" in report.failures[0].error


def test_missing_transport_surface_reported(stores):
    store, log = stores
    # a surface with no registered transport (not telegram/slack) fails honestly
    store.upsert(notify.NotifyRoute(surface="discord", target="1", events=(notify.ALL,)))
    router = notify.NotifyRouter(store=store, log=log)
    report = router.route(notify.NotifyEvent(event_class="cycle_digest", title="d"))
    assert report.failures and "no transport" in report.failures[0].error


# ── dedupe: one digest per destination, not per question ──────────────────────


def test_dedupe_by_event_id(stores):
    store, log = stores
    store.upsert(notify.NotifyRoute(surface="telegram", target="1", events=(notify.ALL,)))
    calls, sender = _recorder()
    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": sender()})

    ev = notify.NotifyEvent(event_class="cycle_digest", title="d", event_id="sweep-42")
    first = router.route(ev)
    second = router.route(ev)

    assert len(first.delivered) == 1
    # second is deduped: recorded as skipped, real sender called only once
    assert len(calls) == 1
    assert all(r.skipped for r in second.results)


def test_dedupe_off_for_destination_path(stores):
    store, log = stores
    calls, sender = _recorder()
    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": sender()})
    ev = notify.NotifyEvent(event_class="alert", title="a", event_id="same")
    router.deliver_to_destinations(ev, ["telegram:9"])
    router.deliver_to_destinations(ev, ["telegram:9"])
    assert len(calls) == 2  # ad-hoc destination path never dedupes


def test_unroutable_destination_reported(stores):
    store, log = stores
    router = notify.NotifyRouter(store=store, log=log, senders={})
    report = router.deliver_to_destinations(notify.NotifyEvent(event_class="alert", title="a"), ["discord:x"])
    assert report.failures and "unroutable" in report.failures[0].error


# ── test_route proves a binding live ──────────────────────────────────────────


def test_test_route_bypasses_class_filter(stores):
    store, log = stores
    route = notify.NotifyRoute(surface="telegram", target="1", events=("resolution",))  # not job_completion
    calls, sender = _recorder()
    router = notify.NotifyRouter(store=store, log=log, senders={"telegram": sender()})
    result = router.test_route(route)
    assert result.ok and len(calls) == 1


# ── register_destination closes the autopilot dead-end ────────────────────────


def test_register_destination_persists_readable_binding(tmp_path):
    store = notify.RouteStore(path=tmp_path / "routes.json")
    route = notify.register_destination(
        "telegram:555", events=("cycle_digest", "alert"), label="autopilot:q1",
        source="autopilot:q1", store=store,
    )
    # previously the destination string was written into the void; now it is a
    # binding the router reads.
    stored = store.get(route.id)
    assert stored is not None
    assert stored.events == ("cycle_digest", "alert")
    assert stored.source == "autopilot:q1"

    calls, sender = _recorder()
    router = notify.NotifyRouter(store=store, log=notify.DeliveryLog(path=tmp_path / "d.json"),
                                 senders={"telegram": sender()})
    report = router.route(notify.NotifyEvent(event_class="cycle_digest", title="digest"))
    assert [c[0] for c in calls] == ["telegram:555"]
    assert report.delivered


def test_register_destination_rejects_bad_string(tmp_path):
    store = notify.RouteStore(path=tmp_path / "routes.json")
    with pytest.raises(ValueError):
        notify.register_destination("not-a-destination", store=store)


# ── deliver_digest: no-op with zero routes, dead-destination alert ────────────


def test_deliver_digest_noop_without_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    report = notify.deliver_digest("nothing bound")
    assert report.results == []


def test_deliver_digest_alerts_on_dead_destination(tmp_path):
    from forecasting.ledger import ForecastLedger

    db = tmp_path / "led.db"
    ledger = ForecastLedger(str(db))
    ledger.initialize_schema()

    store = notify.RouteStore(path=tmp_path / "routes.json")
    store.upsert(notify.NotifyRoute(surface="telegram", target="dead", events=(notify.ALL,)))
    _, sender = _recorder()
    router = notify.NotifyRouter(
        store=store, log=notify.DeliveryLog(path=tmp_path / "d.json"),
        senders={"telegram": sender(ok=False, error="401 unauthorized")},
    )

    for i in range(notify._PERSISTENT_FAILURE_THRESHOLD):
        notify.deliver_digest(f"digest {i}", event_id=f"s{i}", db_path=str(db), router=router)

    alerts = ledger.list_alerts(unresolved_only=True)
    dead = [a for a in alerts if "notification_delivery_failed" in a.reason]
    assert dead, "a persistently dead destination must raise a ledger alert"
