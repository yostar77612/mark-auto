"""desktop_app components form_values responsibilities."""

from desktop_app.strings.catalog import ui_text
from decimal import Decimal, InvalidOperation
import re
from quantlab.core import ValidationError


def number(text, label, minimum=0, maximum='1e12', *, integer=False, optional=False):
    """Strict bounded decimal input; never silently clamp, round, or default."""
    text = str(text).strip()
    if not text and optional:
        return None
    if len(text) > 128 or not text:
        raise ValidationError(ui_text('forms.number.valid_number_required').format(label))
    try:
        value = Decimal(text)
        if not value.is_finite() or value < Decimal(str(minimum)) or value > Decimal(str(maximum)):
            raise ValueError()
        # Bound exponent as well as magnitude to avoid enormous decimal expansion.
        if abs(value.as_tuple().exponent) > 32:
            raise ValueError()
        if integer and (not re.fullmatch(r'[+-]?\d+', text) or value != value.to_integral_value()):
            raise ValueError()
    except (InvalidOperation, ValueError, OverflowError):
        raise ValidationError(
            ui_text('forms.number.range_prefix').format(label, minimum, maximum)
            + (ui_text('forms.number.integer') if integer else ui_text('forms.number.finite_number'))
        ) from None
    return int(value) if integer else format(value, 'f')


def required(text, label):
    text = text.strip()
    if not text or len(text) > 256:
        raise ValidationError(ui_text('forms.required.bounded_length_required').format(label))
    return text


def utc(text, label):
    from quantlab.paper import _time

    value = required(text, label)
    try:
        _time(value, label)
    except ValidationError:
        raise ValidationError(ui_text('forms.utc.utc_required').format(label)) from None
    return value
