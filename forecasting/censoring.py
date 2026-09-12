"""Typed right censoring and proper scoring of a predeclared threshold event.

The score is Brier loss for Y=1{X >= c} (or X>c). It is proper for that
identifiable event, not a score for the unobserved full continuous outcome.
Exact and censored observations use the same frozen threshold and loss.
"""
from dataclasses import asdict, dataclass
import math
import re

from forecasting.models import ValidationError, parse_timestamp


def validate_contract(contract):
    if not isinstance(contract, dict) or not {'threshold', 'inclusive'} <= set(contract) or set(contract) - {'threshold', 'inclusive', 'probability_key'}:
        raise ValidationError('censoring requires threshold and inclusive, with optional probability_key')
    if type(contract['threshold']) not in (int, float) or not math.isfinite(contract['threshold']):
        raise ValidationError('censoring threshold must be a finite JSON number')
    if type(contract['inclusive']) is not bool:
        raise ValidationError('censoring inclusive must be boolean')
    if 'probability_key' in contract:
        key = contract['probability_key']
        match = re.fullmatch(r'p_(gt|gte)_(-?\d+(?:\.\d+)?)(?:_[A-Za-z][A-Za-z0-9_]*)?', key) if isinstance(key, str) else None
        if not match or float(match[2]) != contract['threshold'] or (match[1] == 'gte') != contract['inclusive']:
            raise ValidationError('explicit probability key must identify the exact threshold and inequality')


@dataclass(frozen=True)
class RightCensoredOutcome:
    lower_bound: float
    inclusive: bool
    observed_through: str
    units: str
    kind: str = 'right_censored'

    @classmethod
    def from_dict(cls, value, space):
        if not isinstance(value, dict) or set(value) != {'kind', 'lower_bound', 'inclusive', 'observed_through', 'units'} or value['kind'] != 'right_censored':
            raise ValidationError('invalid typed right-censored outcome')
        validate_contract({'threshold': value['lower_bound'], 'inclusive': value['inclusive']})
        stamp = parse_timestamp(value['observed_through'], field_name='censoring observation cutoff')
        if not stamp or not space.units or value['units'] != space.units:
            raise ValidationError('censored outcome requires an observation cutoff and matching units')
        if space.censoring is None:
            raise ValidationError('declare the censoring threshold in the question before forecasting')
        if value['lower_bound'] != space.censoring['threshold'] or value['inclusive'] != space.censoring['inclusive']:
            raise ValidationError('censored bound must match the declared question threshold')
        return cls(float(value['lower_bound']), value['inclusive'], stamp, value['units'])


def is_censored(value):
    return isinstance(value, dict) and value.get('kind') == 'right_censored'


def threshold_probability(payload, contract):
    validate_contract(contract)
    threshold, inclusive = contract['threshold'], contract['inclusive']
    if not isinstance(payload, dict) or not payload:
        raise ValidationError('censored scoring requires a predictive distribution with identifiable tail mass')
    if 'probability_key' in contract:
        probability = payload.get(contract['probability_key'])
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValidationError('declared explicit tail probability is missing or invalid; Gaussian fallback is forbidden')
        return float(probability)
    gaussian_keys = {'mean', 'expected', 'value', 'point', 'sd', 'std', 'sigma', 'stdev', 'standard_deviation'}
    if set(payload) <= gaussian_keys:
        if len(set(payload) & {'mean', 'expected', 'value', 'point'}) != 1 or len(set(payload) - {'mean', 'expected', 'value', 'point'}) != 1:
            raise ValidationError('Gaussian censoring requires exactly one mean and one standard deviation')
        from forecasting.distribution_parameters import gaussian_parameters
        mean, sd = gaussian_parameters(payload)
        if mean is None or sd is None or sd <= 0:
            raise ValidationError('Gaussian censoring requires finite mean and positive standard deviation')
        return .5 * math.erfc((threshold-mean)/(sd*math.sqrt(2)))
    atoms = []
    for key, mass in payload.items():
        if type(mass) not in (int, float) or not math.isfinite(mass) or not 0 <= mass <= 1:
            raise ValidationError('censored PMF requires finite probability masses')
        match = re.fullmatch(r'p_?(\d+)(_?plus|\+)?', str(key))
        try:
            point = float(match[1] if match else key)
        except (TypeError, ValueError):
            raise ValidationError('tail probability is not identified by this distribution representation') from None
        if not math.isfinite(point):
            raise ValidationError('PMF support must be finite')
        atoms.append((point, bool(match and match[2]), float(mass)))
    if not math.isclose(sum(a[2] for a in atoms), 1, abs_tol=1e-6):
        raise ValidationError('censored PMF masses must sum to one')
    atoms.sort()
    if len({a[0] for a in atoms}) != len(atoms) or any(a[1] for a in atoms[:-1]):
        raise ValidationError('PMF buckets must be disjoint')
    probability = 0.0
    for point, open_tail, mass in atoms:
        above = point >= threshold if inclusive else point > threshold
        if open_tail and not above:
            raise ValidationError('censoring threshold splits an open-ended bucket; tail mass is unidentified')
        if above:
            probability += mass
    return probability


def score(payload, outcome, space):
    if space.censoring is None:
        raise ValidationError('censored outcome has no declared threshold contract')
    probability = threshold_probability(payload, space.censoring)
    if is_censored(outcome):
        RightCensoredOutcome.from_dict(outcome, space)
        observed = 1.0
    else:
        if type(outcome) not in (int, float) or not math.isfinite(outcome):
            raise ValidationError('threshold score requires an exact numeric or typed censored observation')
        threshold = space.censoring['threshold']
        observed = float(outcome >= threshold if space.censoring['inclusive'] else outcome > threshold)
    return dict(brier_score=None, log_score=None, proper_score=(probability-observed)**2,
        score_rule='right_censored_threshold_brier_v1', calibration_bucket=None,
        notes=f"Threshold-event Brier loss: p={probability:.12g}, observed={observed:g}, threshold={space.censoring['threshold']}, inclusive={space.censoring['inclusive']}. Scores the declared event only; no exact censored value or full-distribution accuracy is inferred.")


def normalized_outcome(value, space):
    return asdict(RightCensoredOutcome.from_dict(value, space))
