"""Bounded provider transport and durable readiness receipts for learning trials."""
import hashlib
import json
import math
import uuid
from urllib.parse import urlsplit, urlunsplit

from forecasting.trial_contracts import response_json
from forecasting.models import ValidationError, timestamp_to_datetime, utc_now_iso


def settings_key(config):
    return hashlib.sha256(json.dumps({k: config[k] for k in ('model', 'provider', 'max_tokens')},
        sort_keys=True).encode()).hexdigest()


def provider_runner(config):
    from agent.auxiliary_client import resolve_provider_client
    client, model = resolve_provider_client(config['provider'], model=config['model'])
    if client is None or not model:
        raise ValidationError('configured trial provider is unavailable')
    if hasattr(client, 'with_options'):
        client = client.with_options(max_retries=0, timeout=120)

    def run(messages, settings):
        response = client.chat.completions.create(model=model, messages=messages,
            max_tokens=settings['max_tokens'], timeout=120)
        choice = response.choices[0]
        url = urlsplit(str(getattr(client, 'base_url', config['provider'])))
        endpoint = urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], url.path, '', ''))
        usage = getattr(response, 'usage', None)
        return {'content': choice.message.content, 'finish_reason': choice.finish_reason or 'missing',
            'model': getattr(response, 'model', model), 'endpoint': endpoint,
            'usage': (usage.model_dump() if hasattr(usage, 'model_dump') else usage if isinstance(usage, dict) else
                {k: getattr(usage, k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens') if hasattr(usage, k)} or None),
            'request_id': getattr(response, '_request_id', None)}
    return run


def initialize_schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS learning_provider_reservations (provider TEXT NOT NULL, reserved_at REAL NOT NULL, input_tokens INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS learning_provider_reservations_window ON learning_provider_reservations(provider,reserved_at)")
    conn.execute('''CREATE TABLE IF NOT EXISTS learning_provider_preflights (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL, settings_key TEXT NOT NULL,
        status TEXT NOT NULL, receipt TEXT, error TEXT)''')


def preflight(ledger, spec, *, runner=None):
    config = {k: spec[k] for k in ('model', 'provider')}
    config['max_tokens'] = spec.get('max_tokens', 8192)
    if type(config['max_tokens']) is not int or not 128 <= config['max_tokens'] <= 16384:
        raise ValidationError('invalid response token budget')
    if not all(isinstance(config[k], str) and config[k].strip() for k in ('model', 'provider')):
        raise ValidationError('explicit provider and model required')
    stamp, pid, receipt, error = utc_now_iso(), 'pf_' + uuid.uuid4().hex[:12], None, None
    try:
        call = runner or provider_runner(config)
        receipt = call([{'role': 'system', 'content': 'Return only JSON with forecast and rationale. Keep rationale under 100 words.'},
            {'role': 'user', 'content': 'Transport readiness check, not a forecast: a fair coin has probability 0.5 of heads. Return that probability and explain briefly.'}], config)
        parsed = response_json(receipt)
        value = parsed.get('forecast')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isclose(value, .5):
            raise ValidationError('readiness response did not satisfy the known-answer contract')
        if not isinstance(parsed.get('rationale'), str) or not parsed['rationale'].strip():
            raise ValidationError('readiness response requires rationale')
        status = 'ready'
    except Exception as exc:
        status, error = 'failed', type(exc).__name__ + ': ' + str(exc)
    with ledger._connect() as conn:
        conn.execute('INSERT INTO learning_provider_preflights VALUES (?,?,?,?,?,?)',
            (pid, stamp, settings_key(config), status, json.dumps(receipt, default=str, allow_nan=False), error))
    return {'preflight_id': pid, 'status': status, 'settings': config, 'receipt': receipt, 'error': error,
        'limitation': 'A transport probe does not guarantee provider availability or sufficient context for every question.'}


def require_preflight(ledger, config):
    with ledger._connect() as conn:
        row = conn.execute('SELECT * FROM learning_provider_preflights WHERE id=?', (config.get('preflight_id'),)).fetchone()
    if row is None or row['status'] != 'ready' or row['settings_key'] != settings_key(config):
        raise ValidationError('run a successful trial preflight for this exact model and response budget before live execution')
    age = (timestamp_to_datetime(utc_now_iso()) - timestamp_to_datetime(row['created_at'])).total_seconds()
    if not 0 <= age <= 1800:
        raise ValidationError('provider preflight expired; run a new probe and pass --preflight-id to resume pending arms')
    return json.loads(row['receipt'])


def validate_quota(requests_per_minute, input_tokens_per_minute):
    if type(requests_per_minute) is not int or not 1 <= requests_per_minute <= 60:
        raise ValidationError('requests_per_minute must be an integer from 1 to 60')
    if type(input_tokens_per_minute) is not int or input_tokens_per_minute < 1024:
        raise ValidationError('input_tokens_per_minute must be an integer of at least 1024')


def reserve_quota(conn, config, messages, stamp):
    """Reserve inside the arm-claim transaction; no sleeping or arm consumption.

    UTF-8 bytes plus framing allowance deliberately overestimate text tokens.
    This ledger-wide provider budget cannot account for callers outside this desk.
    """
    rpm, tpm = config.get('requests_per_minute', 6), config.get('input_tokens_per_minute', 60000)
    validate_quota(rpm, tpm)
    estimate = len(json.dumps(messages, ensure_ascii=False).encode('utf-8')) + 2048
    if estimate > tpm:
        return {'reason': 'request_exceeds_input_budget', 'estimated_input_tokens': estimate,
                'input_tokens_per_minute': tpm, 'retry_after_seconds': None}
    now = timestamp_to_datetime(stamp).timestamp()
    rows = conn.execute('SELECT reserved_at,input_tokens FROM learning_provider_reservations WHERE provider=? AND reserved_at>? ORDER BY reserved_at',
                        (config['provider'], now - 60)).fetchall()
    wait = max(0, rows[-1][0] + 60 / rpm - now) if rows else 0
    used = sum(r[1] for r in rows)
    for reserved_at, tokens in rows:
        if used + estimate <= tpm:
            break
        wait = max(wait, reserved_at + 60 - now)
        used -= tokens
    if wait > 0:
        return {'reason': 'provider_quota_pacing', 'retry_after_seconds': math.ceil(wait),
                'estimated_input_tokens': estimate}
    conn.execute('INSERT INTO learning_provider_reservations(provider,reserved_at,input_tokens) VALUES (?,?,?)',
                 (config['provider'], now, estimate))
    return None
