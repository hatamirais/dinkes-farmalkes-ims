from datetime import date, timedelta
from django.test import SimpleTestCase
from apps.core.expiry_monitoring import expiry_display


class ExpiryDisplayTests(SimpleTestCase):
    def test_shared_day_boundaries_do_not_reclassify_ed_day_as_past(self):
        today = date(2026, 11, 23)
        for days, status in [(-1, "expired"), (0, "near-critical"), (1, "near-critical"),
                             (30, "near-critical"), (31, "near"), (90, "near")]:
            with self.subTest(days=days):
                result = expiry_display(today + timedelta(days=days), today)
                self.assertEqual(result["expiry_status"], status)
                self.assertEqual(result["days_to_expiry"], days)
