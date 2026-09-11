"""Strict JSON at forecasting trust boundaries; ambiguity is not evidence."""
import json
from forecasting.models import ValidationError


def strict_json_loads(value, *, object_name='JSON'):
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValidationError(f'duplicate {object_name} key: {key}')
            result[key] = item
        return result

    def reject_constant(constant):
        raise ValidationError(f'{object_name} cannot contain nonfinite number {constant}')

    return json.loads(value, object_pairs_hook=unique_object, parse_constant=reject_constant)
