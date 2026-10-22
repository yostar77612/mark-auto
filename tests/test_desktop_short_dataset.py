"""A valid but short dataset refreshes the views without a false failure status."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from quantlab.reporting import save_dataset, synthetic_dataset
from tests import test_desktop_ui as support


def fields(form):
    return {key: widget.text() for key, widget in form.fields.items() if hasattr(widget, 'text')}


@unittest.skipUnless(support.HAS_QT, 'Pinned Qt needed')
class ShortDatasetRefreshTests(unittest.TestCase):
    setUpClass = support.NativeDesktopTests.__dict__['setUpClass']
    setUp = support.NativeDesktopTests.setUp
    cleanup_window = support.NativeDesktopTests.cleanup_window

    def test_short_dataset_keeps_defaults_and_reports_no_error(self):
        # Regression: 2..15 bars made walk-forward/demo defaults raise inside refresh_views,
        # which poll_jobs reported as "validation failed" after a successful import.
        w = self.window
        campaign_before = fields(w.campaign_form)
        for count in (2, 7, 12):
            with self.subTest(bars=count):
                save_dataset(synthetic_dataset(count), self.paths.state / 'dataset.json')
                w.refresh_views()
                self.assertTrue(w._dataset_ready)
                self.assertTrue(w.run_button.isEnabled())
                self.assertIn(str(count), w.overview.text())
        self.assertEqual(fields(w.campaign_form), campaign_before)

    def test_long_enough_dataset_still_sets_derived_defaults(self):
        w = self.window
        save_dataset(synthetic_dataset(240), self.paths.state / 'dataset.json')
        w.refresh_views()
        payload = w.campaign_form.build_payload(w.backtest_form.build_payload()['config'])
        self.assertEqual(payload['splits']['holdout'][1], 240)
        self.assertTrue(w._dataset_ready)


if __name__ == '__main__':
    unittest.main()
