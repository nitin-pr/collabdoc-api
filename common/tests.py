import io
import re
from contextlib import redirect_stdout
from datetime import datetime, timezone

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from .utils import parse_csv_param, parse_datetime_param, parse_uuid_param


class RequestLoggingMiddlewareTests(SimpleTestCase):
    def get(self, path):
        output = io.StringIO()
        with redirect_stdout(output):
            response = self.client.get(path)
        return response, output.getvalue()

    def test_logs_method_path_status_and_duration(self):
        response, output = self.get('/api/')

        self.assertEqual(response.status_code, 200)
        self.assertRegex(output, r'\[API\] GET /api/ -> 200 \(\d+\.\d{2} ms\)')

    def test_logs_error_statuses_too(self):
        _, output = self.get('/api/does-not-exist/')

        self.assertRegex(output, r'\[API\] GET /api/does-not-exist/ -> 404 \(\d+\.\d{2} ms\)')

    def test_logs_one_line_per_request(self):
        _, output = self.get('/api/')

        self.assertEqual(len(re.findall(r'\[API\]', output)), 1)

    def test_is_registered_in_settings(self):
        from django.conf import settings

        self.assertIn('common.middleware.RequestLoggingMiddleware', settings.MIDDLEWARE)


class QueryParamHelperTests(SimpleTestCase):
    def test_parse_uuid_param_accepts_a_uuid(self):
        self.assertEqual(str(parse_uuid_param('id', '00000000-0000-0000-0000-000000000001')),
                         '00000000-0000-0000-0000-000000000001')

    def test_parse_uuid_param_rejects_garbage_with_the_parameter_name(self):
        with self.assertRaises(ValidationError) as caught:
            parse_uuid_param('workspace', 'abc')

        self.assertIn('workspace', caught.exception.detail)

    def test_parse_csv_param_trims_and_drops_empty_items(self):
        self.assertEqual(parse_csv_param(' a, b,,c ,'), ['a', 'b', 'c'])

    def test_plain_date_is_the_start_of_the_day_for_a_lower_bound(self):
        self.assertEqual(parse_datetime_param('from', '2026-10-09'), datetime(2026, 10, 9, tzinfo=timezone.utc))

    def test_plain_date_is_the_end_of_the_day_for_an_upper_bound(self):
        self.assertEqual(parse_datetime_param('to', '2026-10-09', end_of_day=True),
                         datetime(2026, 10, 9, 23, 59, 59, 999999, tzinfo=timezone.utc))

    def test_iso_datetime_is_kept_as_given(self):
        self.assertEqual(parse_datetime_param('from', '2026-10-09T14:30:00Z'),
                         datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc))

    def test_naive_datetime_is_treated_as_utc(self):
        self.assertEqual(parse_datetime_param('from', '2026-10-09T14:30:00'),
                         datetime(2026, 10, 9, 14, 30, tzinfo=timezone.utc))

    def test_invalid_dates_raise_a_validation_error(self):
        for value in ('yesterday', '2026-13-45', '', '2026-10-09T99:99:99'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_datetime_param('from', value)
