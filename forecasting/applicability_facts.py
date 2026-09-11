"""Source-bound, timestamped applicability facts extracted from archived JSON.

A configured source is an operator trust decision, not a truth guarantee. This
module proves what an archived source said and when; it never infers peak passage
from a clock or turns an agent's assertion into verified evidence.
"""
from __future__ import annotations

import hashlib
import json
from forecasting.json_validation import strict_json_loads
import math
import re
from pathlib import Path
import uuid
from urllib.parse import urlsplit

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime, utc_now_iso


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS applicability_bindings (
        id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES forecast_questions(id),
        fact_key TEXT NOT NULL, source_url TEXT NOT NULL, value_pointer TEXT NOT NULL,
        observed_at_pointer TEXT NOT NULL, value_type TEXT NOT NULL,
        max_age_seconds INTEGER NOT NULL, created_at TEXT NOT NULL)''')

    if 'source_contract' not in {r[1] for r in conn.execute('PRAGMA table_info(applicability_bindings)')}:
        conn.execute("ALTER TABLE applicability_bindings ADD COLUMN source_contract TEXT")


def pointer_value(document, pointer):
    if not isinstance(pointer, str) or not pointer.startswith('/'):
        raise ValidationError('JSON pointer must start with /')
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])', token):
            raise ValidationError('invalid JSON pointer escape')
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(document, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token):
                raise ValidationError('invalid JSON pointer array index')
            document = document[int(token)]
        else:
            document = document[token]
    return document


def bind_fact(ledger, *, question_id, key, source_url, value_pointer, observed_at_pointer,
              value_type='string', max_age_seconds=3600, source_contract=None):
    ledger.get_question(question_id)
    if not isinstance(key, str) or not key.strip() or value_type not in ('string', 'number', 'boolean'):
        raise ValidationError('fact requires a key and a scalar value type')
    if urlsplit(source_url).scheme != 'https' or not urlsplit(source_url).netloc:
        raise ValidationError('fact source must be an explicit HTTPS URL')
    if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 31536000:
        raise ValidationError('max_age_seconds must be an integer between 1 and 31536000')
    for pointer in (value_pointer, observed_at_pointer):
        if not isinstance(pointer, str) or not pointer.startswith('/'):
            raise ValidationError('both JSON pointers must start with /')
    if source_contract is not None:
        from forecasting.source_bindings import source_contract as validate_contract, binding_spec
        source_contract = validate_contract(**source_contract)
        expected = binding_spec(source_contract)
        if value_type != 'number' or any(expected[k] != v for k, v in (
            ('source_url', source_url), ('value_pointer', value_pointer), ('observed_at_pointer', observed_at_pointer))):
            raise ValidationError('binding does not match its source measurement contract')
    bid = 'fb_'  + uuid.uuid4().hex[:12]
    with ledger._connect() as conn:
        conn.execute('INSERT INTO applicability_bindings (id,question_id,fact_key,source_url,value_pointer,observed_at_pointer,value_type,max_age_seconds,created_at,source_contract) VALUES (?,?,?,?,?,?,?,?,?,?)',
            (bid, question_id, key.strip(), source_url, value_pointer, observed_at_pointer, value_type, max_age_seconds, utc_now_iso(), json.dumps(source_contract) if source_contract else None))
    return {'binding_id': bid, 'facts': evidence_facts(ledger, ledger.get_question(question_id))}


def evidence_facts(ledger, question, *, cutoff=None):
    stamp = parse_timestamp(cutoff, field_name='fact cutoff') or utc_now_iso()
    at = timestamp_to_datetime(stamp)
    with ledger._connect() as conn:
        bindings = {r['fact_key']: dict(r) for r in conn.execute(
            'SELECT * FROM applicability_bindings WHERE question_id=? AND julianday(created_at)<=julianday(?) ORDER BY rowid', (question.id, stamp))}
    evidence = ledger.list_evidence(question.id)
    facts = {}
    for key, binding in bindings.items():
        result = {'status': 'unknown', 'reason': 'no_admissible_source', 'binding_id': binding['id'], 'source_url': binding['source_url'], 'cutoff': stamp}
        candidates = [e for e in evidence if e.source_url == binding['source_url'] and
                      all(t and timestamp_to_datetime(t) <= at for t in (e.available_at, e.captured_at))]
        candidates.sort(key=lambda e: (timestamp_to_datetime(e.available_at), timestamp_to_datetime(e.captured_at), e.id), reverse=True)
        # Latest admissible source wins; never fall back to a nicer older value
        # if the current archive is malformed, blocked, stale or contradictory.
        if candidates:
            e = candidates[0]
            result['evidence_id'] = e.id
            try:
                if e.metadata.get('blocked') or e.metadata.get('invalidated') or e.metadata.get('superseded_by'):
                    raise ValidationError('source_unusable')
                if not e.snapshot_path:
                    raise ValidationError('archive_missing')
                path = Path(e.snapshot_path)
                if path.stat().st_size > 2_000_000:
                    raise ValidationError('archive_too_large')
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                capture = e.metadata.get('source_capture') or {}
                if capture.get('url') != binding['source_url'] or capture.get('method') != 'https_fetch':
                    raise ValidationError('source_capture_unverified')
                expected = capture.get('sha256')
                if not expected:
                    raise ValidationError('archive_integrity_unverified')
                if digest != expected:
                    raise ValidationError('archive_hash_mismatch')
                document = strict_json_loads(raw)
                meaning = {}
                if binding.get('source_contract'):
                    from forecasting.source_bindings import extract_measurement
                    value, observed_at, meaning = extract_measurement(document, json.loads(binding['source_contract']), captured_at=e.captured_at)
                else:
                    value = pointer_value(document, binding['value_pointer'])
                    observed_at = parse_timestamp(pointer_value(document, binding['observed_at_pointer']), field_name='observation timestamp')
                if not observed_at:
                    raise ValidationError('observation_time_missing')
                age = (at - timestamp_to_datetime(observed_at)).total_seconds()
                if age < 0 or age > binding['max_age_seconds']:
                    raise ValidationError('observation_future_or_stale')
                kind = binding['value_type']
                valid = (isinstance(value, str) and bool(value.strip()) if kind == 'string' else
                         isinstance(value, bool) if kind == 'boolean' else
                         isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value))
                if not valid:
                    raise ValidationError('observation_type_mismatch')
                result.update(meaning)
                result.update(status='verified', reason='archived_source_value', value=value,
                    observed_at=observed_at, captured_at=e.captured_at, available_at=e.available_at,
                    sha256=digest, value_pointer=binding['value_pointer'], max_age_seconds=binding['max_age_seconds'])
            except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, ValidationError) as exc:
                result['reason'] = str(exc)
        facts[key] = result
    return facts
