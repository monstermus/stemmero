"""Kontrollér at en død appproces bliver startet igen."""
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import watchdog


class SupervisorTests(unittest.TestCase):
    def test_restarts_a_real_child_after_normal_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            starts = root / 'starts.txt'
            stop = root / 'stop'
            script = root / 'child.py'
            script.write_text(
                "from pathlib import Path\n"
                f"starts = Path({str(starts)!r})\n"
                "with starts.open('a') as out: out.write('start\\n')\n"
                "if len(starts.read_text().splitlines()) == 2:\n"
                f"    Path({str(stop)!r}).touch()\n"
            )
            watchdog.supervise([sys.executable, str(script)], stop, restart_delay=0.01)
            self.assertEqual(starts.read_text().splitlines(), ['start', 'start'])

    def test_restarts_a_real_child_after_error_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'stop'
            starts = root / 'starts'
            script = root / 'child.py'
            script.write_text(
                "from pathlib import Path\n"
                f"starts = Path({str(starts)!r})\n"
                "with starts.open('a') as out: out.write('start\\n')\n"
                "if len(starts.read_text().splitlines()) == 2:\n"
                f"    Path({str(marker)!r}).touch()\n"
                "raise SystemExit(3)\n"
            )
            watchdog.supervise([sys.executable, str(script)], marker, restart_delay=0.01, poll_interval=0.005)
            self.assertEqual(starts.read_text().splitlines(), ['start', 'start'])

    def test_stop_marker_terminates_a_running_child(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'stop'
            ready = root / 'ready'
            command = [sys.executable, '-c', f"from pathlib import Path; import time; Path({str(ready)!r}).touch(); time.sleep(2)"]
            worker = threading.Thread(target=watchdog.supervise, args=(command, marker),
                                      kwargs={'poll_interval': 0.005}, daemon=True)
            worker.start()
            self.addCleanup(worker.join, 3)
            deadline = time.monotonic() + 2
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertTrue(ready.exists(), 'Child-processen startede ikke')
            marker.touch()
            worker.join(0.5)
            self.assertFalse(worker.is_alive(), 'Stopmarkøren stoppede ikke den kørende child')

    def test_stop_marker_prevents_another_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / 'stop'
            marker.touch()
            started = root / 'should-not-exist'
            watchdog.supervise([sys.executable, '-c', f"open({str(started)!r}, 'w').close()"], marker)
            self.assertFalse(started.exists())

    def test_source_child_arguments_keep_the_script_path(self):
        self.assertEqual(
            watchdog.child_command('python.exe', 'C:/app/stemmero.py', frozen=False),
            ['python.exe', 'C:/app/stemmero.py', '--minimized'],
        )

    def test_frozen_child_has_no_watchdog_argument(self):
        self.assertEqual(
            watchdog.child_command('C:/app/Stemmero.exe', 'ignored', frozen=True),
            ['C:/app/Stemmero.exe', '--minimized'],
        )


if __name__ == '__main__':
    unittest.main()
