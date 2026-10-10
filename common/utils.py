"""Helpers shared by the apps for validating query parameters (bad input -> 400, never 500)."""

import uuid
from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from rest_framework.exceptions import ValidationError


def parse_uuid_param(name, value):
    """Return `value` as a UUID or raise a 400 naming the offending parameter."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise ValidationError({name: f'"{value}" is not a valid UUID.'})


def parse_csv_param(value):
    """'a, b,,c' -> ['a', 'b', 'c']."""
    return [item.strip() for item in value.split(',') if item.strip()]


def parse_datetime_param(name, value, end_of_day=False):
    """
    Accept an ISO datetime ('2026-10-09T14:30:00Z') or a plain date ('2026-10-09').

    A plain date means the whole day: it becomes 00:00 for a lower bound and the
    last instant of the day for an upper bound (end_of_day=True), so `?to=2026-10-09`
    includes everything that happened on the 9th.
    """
    try:
        # Check for a bare date first: Python would otherwise read it as midnight.
        day = parse_date(value)
        parsed = parse_datetime(value) if day is None else None
    except ValueError:
        day, parsed = None, None

    if day is not None:
        parsed = datetime.combine(day, time.min)
        if end_of_day:
            parsed += timedelta(days=1) - timedelta(microseconds=1)
    elif parsed is None:
        raise ValidationError({name: f'"{value}" is not a valid date or datetime (use YYYY-MM-DD or ISO 8601).'})

    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt_timezone.utc)
    return parsed
