"""Genstart Stemmeros overvågning efter normal exit eller nedbrud."""
from pathlib import Path
import subprocess
import sys
import time


def child_command(executable, script, frozen=None):
    if frozen is None:
        frozen = bool(getattr(sys, 'frozen', False))
    command = [executable] if frozen else [executable, script]
    return command + ['--minimized']


def supervise(command, stop_marker, restart_delay=2.0, poll_interval=0.2):
    """Behold processen, til en installation eller afinstallation stopper den."""
    stop_marker = Path(stop_marker)
    while not stop_marker.exists():
        try:
            child = subprocess.Popen(command)
        except OSError:
            child = None
        if child is not None:
            while child.poll() is None:
                if stop_marker.exists():
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
                    return
                time.sleep(poll_interval)
        deadline = time.monotonic() + restart_delay
        while time.monotonic() < deadline:
            if stop_marker.exists():
                return
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
