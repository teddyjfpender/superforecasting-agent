"""Versioned response contracts and explicitly reviewed evaluation compatibility."""
import hashlib
import json
import math
from pathlib import Path

from forecasting.models import ValidationError
from forecasting.json_validation import strict_json_loads

# These modules own score computation, payload validation and frozen adjustments.
EVALUATION_PATHS = ('ledger/scoring.py', 'ledger/core.py', 'models.py', 'learning.py',
                    'censoring.py', 'distribution_parameters.py', 'json_validation.py',
                    'trial_evaluation.py', 'trial_contracts.py')


def evaluation_identity():
    root = Path(__file__).parent
    return hashlib.sha256(b''.join((root / p).read_bytes() for p in EVALUATION_PATHS)).hexdigest()


def evaluation_compatible(trial):
    config = json.loads(trial['config'])
    expected = config.get('evaluation_identity')
    registry = json.loads(Path(__file__).with_name('trial_compatibility.json').read_text())
    if expected is None:
        # Reviewed source hashes, never inferred from a version label or DB claim.
        expected = registry.get(trial['scoring_kernel'], {}).get('evaluation_identity')
    current = evaluation_identity()
    if expected == current:
        return True
    # Explicitly reviewed non-scoring changes only; unknown identities fail
    # closed. Frozen trial config and source identities are never rewritten.
    review = registry.get('evaluation_reviews', {}).get(expected, {})
    return bool(review.get('reason')) and review.get('compatible_identity') == current


def response_schema(space):
    number = {'type': 'number'}
    if space['type'] == 'binary':
        forecast = {**number, 'minimum': 0, 'maximum': 1}
    elif space['type'] == 'categorical':
        forecast = {'type': 'object', 'properties': {c: {**number, 'minimum': 0, 'maximum': 1} for c in space['choices']},
                    'required': space['choices'], 'additionalProperties': False}
    else:
        forecast = {'type': 'object', 'properties': {'mean': number, 'sd': {**number, 'exclusiveMinimum': 0}},
                    'required': ['mean', 'sd'], 'additionalProperties': False}
    return {'type': 'object', 'properties': {'forecast': forecast, 'rationale': {'type': 'string', 'minLength': 1}},
            'required': ['forecast', 'rationale'], 'additionalProperties': False}


def validate_response(parsed, space):
    if set(parsed) != {'forecast', 'rationale'} or not isinstance(parsed['rationale'], str) or not parsed['rationale'].strip():
        raise ValidationError('trial response requires exactly forecast and nonempty rationale')
    value = parsed['forecast']
    def finite(v):
        return type(v) in (int, float) and math.isfinite(v)
    if space['type'] == 'binary':
        valid = finite(value) and 0 <= value <= 1
    elif space['type'] == 'categorical':
        valid = (isinstance(value, dict) and set(value) == set(space['choices']) and
                 all(finite(v) and 0 <= v <= 1 for v in value.values()) and
                 math.isclose(sum(value.values()), 1, abs_tol=1e-8))
    else:
        valid = (isinstance(value, dict) and set(value) == {'mean', 'sd'} and
                 all(finite(v) for v in value.values()) and value['sd'] > 0)
    if not valid:
        raise ValidationError('trial forecast violates declared response schema; numeric forecasts require exactly mean and positive sd')


def response_json(response):
    if not isinstance(response, dict) or not isinstance(response.get('model'), str) or not response['model'] or not isinstance(response.get('endpoint'), str) or not response['endpoint']:
        raise ValidationError('trial requires model and endpoint receipts')
    reason = response.get('finish_reason')
    if reason is not None and reason != 'stop':
        raise ValidationError('incomplete provider response: finish_reason=' + str(reason))
    content = response['content']
    if isinstance(content, str):
        lines = content.strip().splitlines()
        if len(lines) >= 3 and lines[0].lower() in ('```json', '```') and lines[-1] == '```':
            content = '\n'.join(lines[1:-1])
    parsed = content if isinstance(content, dict) else strict_json_loads(content)
    if not isinstance(parsed, dict):
        raise ValidationError('trial response must be a JSON object')
    return parsed


