import unittest

from signal_selection import SignalSelector


class SignalSelectorTests(unittest.TestCase):
    def test_short_spike_does_not_switch_the_current_endpoint(self):
        selector = SignalSelector()
        self.assertEqual(selector.select({'current': -25.0, 'other': -60.0}, 'current', 0.0), 'current')
        self.assertEqual(selector.select({'current': -25.0, 'other': -8.0}, 'current', 0.2), 'current')
        self.assertEqual(selector.select({'current': -25.0, 'other': -60.0}, 'current', 0.4), 'current')

    def test_candidate_must_remain_strong_for_one_second(self):
        selector = SignalSelector()
        self.assertEqual(selector.select({'current': -35.0, 'other': -25.0}, 'current', 0.0), 'current')
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertEqual(selector.select({'current': -35.0, 'other': -25.0}, 'current', now), 'current')
        self.assertEqual(selector.select({'current': -35.0, 'other': -25.0}, 'current', 1.0), 'other')

    def test_short_speech_pauses_do_not_restart_positive_signal_dwell(self):
        selector = SignalSelector()
        frames = (
            (0.0, -20.0),
            (0.2, -20.0),
            (0.4, -80.0),
            (0.6, -80.0),
            (0.8, -20.0),
            (1.0, -20.0),
            (1.2, -20.0),
            (1.4, -80.0),
            (1.6, -20.0),
            (1.8, -20.0),
            (2.0, -20.0),
        )
        for now, other_peak in frames[:-1]:
            with self.subTest(now=now):
                self.assertEqual(
                    selector.select({'current': -80.0, 'other': other_peak}, 'current', now),
                    'current',
                )
        self.assertEqual(
            selector.select({'current': -80.0, 'other': frames[-1][1]}, 'current', frames[-1][0]),
            'other',
        )

    def test_long_silence_discards_prior_positive_signal_dwell(self):
        selector = SignalSelector()
        for now, other_peak in (
            (0.0, -20.0),
            (0.2, -20.0),
            (0.4, -80.0),
            (0.6, -80.0),
            (0.8, -80.0),
            (1.0, -80.0),
            (1.2, -20.0),
        ):
            self.assertEqual(
                selector.select({'current': -80.0, 'other': other_peak}, 'current', now),
                'current',
            )
        for now in (1.4, 1.6, 1.8, 2.0):
            self.assertEqual(selector.select({'current': -80.0, 'other': -20.0}, 'current', now), 'current')
        self.assertEqual(selector.select({'current': -80.0, 'other': -20.0}, 'current', 2.2), 'other')

    def test_similar_signal_and_silence_keep_the_current_endpoint(self):
        selector = SignalSelector()
        for now, peaks in (
            (0.0, {'current': -25.0, 'other': -29.0}),
            (1.0, {'current': -80.0, 'other': -90.0}),
            (2.0, {}),
        ):
            with self.subTest(now=now):
                self.assertEqual(selector.select(peaks, 'current', now), 'current')

    def test_empty_current_selects_a_sustained_signal(self):
        selector = SignalSelector()
        self.assertIsNone(selector.select({'other': -40.0}, None, 0.0))
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertIsNone(selector.select({'other': -40.0}, None, now))
        self.assertEqual(selector.select({'other': -40.0}, None, 1.0), 'other')

    def test_repeated_old_snapshot_does_not_count_as_dwell(self):
        selector = SignalSelector()
        peaks = {'current': -35.0, 'other': -25.0}
        for _ in range(20):
            self.assertEqual(selector.select(peaks, 'current', 0.0), 'current')

    def test_long_gap_restarts_candidate_dwell(self):
        selector = SignalSelector()
        peaks = {'current': -35.0, 'other': -25.0}
        self.assertEqual(selector.select(peaks, 'current', 0.0), 'current')
        self.assertEqual(selector.select(peaks, 'current', 1.1), 'current')
        self.assertEqual(selector.select(peaks, 'current', 1.5), 'current')
        self.assertEqual(selector.select(peaks, 'current', 1.9), 'current')
        self.assertEqual(selector.select(peaks, 'current', 2.1), 'other')

    def test_empty_snapshot_clears_candidate_dwell(self):
        selector = SignalSelector()
        peaks = {'current': -35.0, 'other': -25.0}
        self.assertEqual(selector.select(peaks, 'current', 0.0), 'current')
        self.assertEqual(selector.select({}, 'current', 0.4), 'current')
        self.assertEqual(selector.select(peaks, 'current', 0.5), 'current')
        self.assertEqual(selector.select(peaks, 'current', 1.0), 'current')
        self.assertEqual(selector.select(peaks, 'current', 1.5), 'other')

    def test_six_db_margin_and_cooldown_prevent_rapid_switching(self):
        selector = SignalSelector()
        self.assertEqual(selector.select({'current': -35.0, 'first': -25.0}, 'current', 0.0), 'current')
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertEqual(selector.select({'current': -35.0, 'first': -25.0}, 'current', now), 'current')
        self.assertEqual(selector.select({'current': -35.0, 'first': -25.0}, 'current', 1.0), 'first')
        self.assertEqual(selector.select({'first': -30.0, 'second': -23.5}, 'first', 2.0), 'first')
        for step in range(11, 30):
            now = round(step * 0.2, 1)
            self.assertEqual(selector.select({'first': -30.0, 'second': -23.5}, 'first', now), 'first')
        self.assertEqual(selector.select({'first': -30.0, 'second': -23.5}, 'first', 6.0), 'second')

    def test_reset_clears_pending_candidate_and_cooldown(self):
        selector = SignalSelector()
        self.assertEqual(selector.select({'first': -35.0, 'second': -25.0}, 'first', 0.0), 'first')
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertEqual(selector.select({'first': -35.0, 'second': -25.0}, 'first', now), 'first')
        self.assertEqual(selector.select({'first': -35.0, 'second': -25.0}, 'first', 1.0), 'second')
        selector.reset()
        self.assertEqual(selector.select({'second': -30.0, 'first': -23.5}, 'second', 2.0), 'second')
        for step in range(11, 15):
            now = round(step * 0.2, 1)
            self.assertEqual(selector.select({'second': -30.0, 'first': -23.5}, 'second', now), 'second')
        self.assertEqual(selector.select({'second': -30.0, 'first': -23.5}, 'second', 3.0), 'first')

    def test_discord_hint_only_breaks_a_near_equal_signal_tie(self):
        tied = SignalSelector()
        self.assertIsNone(tied.select({'first': -20.0, 'hinted': -20.5}, None, 0.0,
                                      discord_hint='hinted'))
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertIsNone(tied.select({'first': -20.0, 'hinted': -20.5}, None, now,
                                          discord_hint='hinted'))
        self.assertEqual(tied.select({'first': -20.0, 'hinted': -20.5}, None, 1.0,
                                     discord_hint='hinted'), 'hinted')

        stronger = SignalSelector()
        self.assertIsNone(stronger.select({'first': -20.0, 'hinted': -22.0}, None, 0.0,
                                          discord_hint='hinted'))
        for now in (0.2, 0.4, 0.6, 0.8):
            self.assertIsNone(stronger.select({'first': -20.0, 'hinted': -22.0}, None, now,
                                              discord_hint='hinted'))
        self.assertEqual(stronger.select({'first': -20.0, 'hinted': -22.0}, None, 1.0,
                                         discord_hint='hinted'), 'first')


if __name__ == '__main__':
    unittest.main()
