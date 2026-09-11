"""Public commands for paired learning trials and source-backed conditions."""
from __future__ import annotations

import json
from pathlib import Path

from forecasting.cli import core as _core


def register(sub):
    domain = sub.add_parser('domain', help='Correct semantic domain with preserved history')
    domain.add_argument('id')
    domain.add_argument('--domain', required=True)
    domain.add_argument('--expected-domain', required=True, help='Current domain, or empty string for unknown')
    domain.add_argument('--reason', required=True)
    domain.set_defaults(_forecast_handler=handle_domain)
    trial = sub.add_parser('trial', help='Prospective paired learning evaluations; never changes live probabilities')
    commands = trial.add_subparsers(dest='trial_action', required=True)
    create = commands.add_parser('create', help='Freeze a cohort, evidence, lessons, model and evaluation policy')
    create.add_argument('--spec-file', required=True, help='JSON: assignments {question: cluster}, model, provider, optional budget/effect thresholds')
    for action in ('run', 'report', 'recover', 'export'):
        parser = commands.add_parser(action)
        parser.add_argument('id')
        if action == 'run':
            parser.add_argument('--preflight-id', help='Fresh readiness receipt for the same frozen model and budget')
            parser.add_argument('--limit', type=int, default=20, help='Maximum model calls; each question has two arms')
        if action == 'export':
            parser.add_argument('--output', required=True)
        parser.set_defaults(_forecast_handler=handle_trial)
    commands.add_parser('list').set_defaults(_forecast_handler=handle_trial)
    probe = commands.add_parser('preflight', help='Check provider and response budget before enrolling live arms')
    probe.add_argument('--spec-file', required=True)
    probe.set_defaults(_forecast_handler=handle_trial)
    create.set_defaults(_forecast_handler=handle_trial)
    facts = sub.add_parser('facts', help='Inspect or bind timestamped facts from archived source JSON')
    commands = facts.add_subparsers(dest='facts_action', required=True)
    show = commands.add_parser('show')
    show.add_argument('id')
    show.add_argument('--cutoff')
    show.set_defaults(_forecast_handler=handle_facts)
    bind = commands.add_parser('bind')
    bind.add_argument('id')
    bind.add_argument('--key', required=True)
    bind.add_argument('--source-url', required=True)
    bind.add_argument('--value-pointer', required=True)
    bind.add_argument('--observed-at-pointer', required=True)
    bind.add_argument('--value-type', choices=['string', 'number', 'boolean'], default='string')
    bind.add_argument('--max-age-seconds', type=int, default=3600)
    bind.set_defaults(_forecast_handler=handle_facts)
    source = commands.add_parser('bind-source', help='Bind a verified NWS or USGS measurement contract')
    source.add_argument('id')
    source.add_argument('--key', required=True)
    source.add_argument('--adapter', required=True, choices=['nws_temperature_v1', 'usgs_magnitude_v1'])
    source.add_argument('--entity', required=True)
    source.add_argument('--window-start', required=True)
    source.add_argument('--window-end', required=True)
    source.add_argument('--magnitude-type')
    source.add_argument('--max-age-seconds', type=int, default=3600)
    source.set_defaults(_forecast_handler=handle_facts)


def _run_operation(operation, args):
    from forecasting.models import ValidationError
    try:
        return operation(args)
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from None


def handle_trial(args):
    return _run_operation(_handle_trial, args)


def _handle_trial(args):
    from forecasting.learning_trials import create_trial, run_trial, trial_report, recover_trial, trial_records
    ledger = _core._ledger(args)
    action = args.trial_action
    if action == 'preflight':
        from forecasting.trial_provider import preflight
        report = preflight(ledger, json.loads(Path(args.spec_file).read_text(encoding='utf-8')))
        print(json.dumps(report, indent=2))
        if report['status'] != 'ready':
            raise SystemExit(1)
        return
    if action == 'create':
        report = create_trial(ledger, **json.loads(Path(args.spec_file).read_text(encoding='utf-8')))
    elif action == 'run':
        report = run_trial(ledger, args.id, limit=args.limit, preflight_id=getattr(args, "preflight_id", None))
    elif action == 'recover':
        report = recover_trial(ledger, args.id)
    elif action == 'export':
        trial, cases, arms = trial_records(ledger, args.id)
        report = {'trial': trial, 'cases': cases, 'arms': arms, 'report': trial_report(ledger, args.id)}
        with open(args.output, 'x', encoding='utf-8') as f:
            import os
            os.chmod(args.output, 0o600)
            json.dump(report, f, indent=2)
        report = {'exported': args.output, 'trial_id': args.id}
    elif action == 'list':
        with ledger._connect() as conn:
            ids = [r[0] for r in conn.execute('SELECT id FROM learning_trials ORDER BY created_at DESC')]
        report = [{'trial_id': tid, **{k: v for k, v in trial_report(ledger, tid).items()
            if k in ('assigned_questions', 'assigned_clusters', 'arm_status_counts', 'treatment_coverage', 'estimates')}} for tid in ids]
    else:
        report = trial_report(ledger, args.id)
        # Read-only inspection belongs at the CLI boundary; the frozen trial
        # execution/scoring policy does not change when report copy improves.
        _, cases, arms = trial_records(ledger, args.id)
        case_by_question = {case['question_id']: case for case in cases}
        saved_arms = {(arm['question_id'], arm['arm']): arm for arm in arms}
        for arm in report['arms']:
            case = case_by_question[arm['question_id']]
            saved = saved_arms[(arm['question_id'], arm['arm'])]
            arm['question_title'] = json.loads(case['packet'])['question']['title']
            arm['frozen_lesson_refs'] = ([lesson['id'] for lesson in json.loads(case['treatment'])['lessons']]
                if arm['arm'] == 'learning' else [])
            arm.update(json.loads(saved['output'] or 'null') or {})
    print(json.dumps(report, indent=2))


def handle_facts(args):
    return _run_operation(_handle_facts, args)


def _handle_facts(args):
    from forecasting.applicability_facts import bind_fact, evidence_facts
    ledger = _core._ledger(args)
    q = ledger.get_question(_core._resolve_question_id(ledger, args.id))
    if args.facts_action == 'bind-source':
        from forecasting.source_bindings import source_contract, binding_spec
        contract = source_contract(adapter=args.adapter, entity=args.entity, window_start=args.window_start,
            window_end=args.window_end, magnitude_type=args.magnitude_type)
        report = bind_fact(ledger, question_id=q.id, key=args.key, **binding_spec(contract),
            value_type='number', max_age_seconds=args.max_age_seconds, source_contract=contract)
    elif args.facts_action == 'bind':
        report = bind_fact(ledger, question_id=q.id, key=args.key, source_url=args.source_url,
            value_pointer=args.value_pointer, observed_at_pointer=args.observed_at_pointer,
            value_type=args.value_type, max_age_seconds=args.max_age_seconds)
    else:
        from forecasting.learning import _in_scope_lessons, lesson_applicability
        report = {'question_id': q.id, 'facts': evidence_facts(ledger, q, cutoff=args.cutoff),
            'conditions': [{'lesson_id': lesson['id'], 'decision': lesson_applicability(lesson, q,
                context={'_fact_cutoff': args.cutoff}, ledger=ledger)[1]} for lesson in _in_scope_lessons(ledger, q)],
            'next_action': 'Bind missing facts to an explicit source URL, JSON value pointer and observation timestamp. Refresh expired evidence; never assert peak passage from the clock alone.'}
    print(json.dumps(report, indent=2))


def handle_domain(args):
    def operation(args):
        from dataclasses import asdict
        from forecasting.domains import set_question_domain
        ledger = _core._ledger(args)
        qid = _core._resolve_question_id(ledger, args.id)
        print(json.dumps(asdict(set_question_domain(ledger, qid, domain=args.domain,
            expected_domain=args.expected_domain or None, reason=args.reason)), indent=2))
    return _run_operation(operation, args)
