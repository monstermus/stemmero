"""Choose a capture endpoint from peak-signal measurements only."""
from collections.abc import Mapping
import math


MINIMUM_SIGNAL_DBFS = -50.0
MINIMUM_SIGNAL_SECONDS = 1.0
SWITCH_MARGIN_DB = 6.0
SWITCH_COOLDOWN_SECONDS = 5.0
TIE_WINDOW_DB = 1.0
MAX_SAMPLE_GAP_SECONDS = 0.5
MAX_SIGNAL_PAUSE_SECONDS = 0.4


class SignalSelector:
    """Keep the current endpoint unless another has a sustained stronger signal.

    ``peaks_dbfs`` maps endpoint IDs to peak levels in dBFS. Feed it the same
    IDs on each poll and the monotonic time when that snapshot was measured.
    The selector keeps only one pending candidate and its timing; it stores no
    audio or measurements.
    """

    def __init__(self):
        self._candidate = None
        self._candidate_current = None
        self._candidate_last_seen = None
        self._candidate_signal_seconds = 0.0
        self._candidate_paused_since = None
        self._last_switch_at = None

    def reset(self) -> None:
        """Clear pending signal evidence and the automatic-switch cooldown."""
        self._reset_candidate()
        self._last_switch_at = None

    def select(
        self,
        peaks_dbfs: Mapping[str, float],
        current_endpoint: str | None,
        now: float,
        discord_hint: str | None = None,
    ) -> str | None:
        """Return the current endpoint or a sustained stronger-signal endpoint.

        A candidate must be at least ``MINIMUM_SIGNAL_DBFS`` and, when the
        current endpoint has a signal, at least ``SWITCH_MARGIN_DB`` stronger.
        It must have ``MINIMUM_SIGNAL_SECONDS`` of positive signal, with pauses
        no longer than ``MAX_SIGNAL_PAUSE_SECONDS``. After a switch, another
        switch waits for ``SWITCH_COOLDOWN_SECONDS``. A Discord hint only
        breaks ties between eligible signals within ``TIE_WINDOW_DB``.
        """
        current = current_endpoint if isinstance(current_endpoint, str) and current_endpoint else None
        try:
            timestamp = float(now)
        except (TypeError, ValueError):
            self._reset_candidate()
            return current
        if not math.isfinite(timestamp) or not isinstance(peaks_dbfs, Mapping):
            self._reset_candidate()
            return current

        peaks = {}
        for endpoint, value in peaks_dbfs.items():
            if not isinstance(endpoint, str) or not endpoint or isinstance(value, bool):
                continue
            try:
                peak = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(peak):
                peaks[endpoint] = min(peak, 0.0)

        eligible = {endpoint: peak for endpoint, peak in peaks.items()
                    if peak >= MINIMUM_SIGNAL_DBFS and endpoint != current}
        if current is not None and peaks.get(current, -math.inf) >= MINIMUM_SIGNAL_DBFS:
            current_peak = peaks[current]
            eligible = {endpoint: peak for endpoint, peak in eligible.items()
                        if peak - current_peak >= SWITCH_MARGIN_DB}

        if not eligible:
            if not peaks or self._candidate is None or current != self._candidate_current:
                self._reset_candidate()
                return current

            if timestamp < self._candidate_last_seen:
                self._reset_candidate()
                return current

            elapsed = timestamp - self._candidate_last_seen
            if elapsed > MAX_SAMPLE_GAP_SECONDS:
                self._reset_candidate()
                return current

            if self._candidate_paused_since is None:
                self._candidate_paused_since = timestamp
            elif timestamp - self._candidate_paused_since > MAX_SIGNAL_PAUSE_SECONDS:
                self._reset_candidate()
                return current
            self._candidate_last_seen = timestamp
            return current

        best_peak = max(eligible.values())
        tied = sorted(endpoint for endpoint, peak in eligible.items()
                      if best_peak - peak <= TIE_WINDOW_DB)
        if (self._candidate in tied and self._candidate_current == current):
            candidate = self._candidate
        elif isinstance(discord_hint, str) and discord_hint in tied:
            candidate = discord_hint
        else:
            candidate = tied[0]

        if candidate != self._candidate or current != self._candidate_current:
            self._start_candidate(candidate, current, timestamp)
            return current

        if timestamp < self._candidate_last_seen:
            self._start_candidate(candidate, current, timestamp)
            return current

        elapsed = timestamp - self._candidate_last_seen
        if elapsed > MAX_SAMPLE_GAP_SECONDS:
            self._start_candidate(candidate, current, timestamp)
            return current

        if self._candidate_paused_since is not None:
            if timestamp - self._candidate_paused_since > MAX_SIGNAL_PAUSE_SECONDS:
                self._start_candidate(candidate, current, timestamp)
                return current
            self._candidate_paused_since = None
        else:
            self._candidate_signal_seconds += elapsed
        self._candidate_last_seen = timestamp

        sustained = self._candidate_signal_seconds + 1e-9 >= MINIMUM_SIGNAL_SECONDS
        cooldown_complete = (
            self._last_switch_at is None
            or timestamp - self._last_switch_at >= SWITCH_COOLDOWN_SECONDS
        )
        if sustained and cooldown_complete:
            self._last_switch_at = timestamp
            self._reset_candidate()
            return candidate
        return current

    def _reset_candidate(self):
        self._candidate = None
        self._candidate_current = None
        self._candidate_last_seen = None
        self._candidate_signal_seconds = 0.0
        self._candidate_paused_since = None

    def _start_candidate(self, candidate, current, timestamp):
        self._candidate = candidate
        self._candidate_current = current
        self._candidate_last_seen = timestamp
        self._candidate_signal_seconds = 0.0
        self._candidate_paused_since = None
