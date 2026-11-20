"""Isolate config before importing any Atticus test module."""
import atexit
import os
import tempfile

config = tempfile.TemporaryDirectory(prefix='atticus-test-config-')
os.environ['ATTICUS_DIR'] = config.name
os.environ['ATTICUS_POSTHOG_KEY'] = ''   # tests that clear os.environ also drop ATTICUS_DIR; with no key nothing reaches PostHog
atexit.register(config.cleanup)


def scratch_dir(test):
    """A temp atticus.DIR with default prefs for one test, undone at cleanup; returns the folder."""
    from pathlib import Path
    from unittest.mock import patch
    import atticus
    root = tempfile.TemporaryDirectory(); test.addCleanup(root.cleanup)
    for p in (patch.object(atticus, 'DIR', root.name), patch.object(atticus, 'pref', side_effect=lambda k, d: d)):
        p.start(); test.addCleanup(p.stop)
    return Path(root.name)


def swift_motion(source):
    """Atticus.swift's shared Motion timings, for a slice that fades or resizes a window."""
    start = source.index('enum Motion {')
    return source[start:source.index('\n}\n', start) + 3]


def run_swift(test, source, timeout=10):
    """Compile Swift source to a temp binary, run it, assert both succeed; returns its stdout."""
    import subprocess, sys
    from pathlib import Path
    if sys.platform != 'darwin': test.skipTest('needs macOS frameworks (Cocoa, AppKit)')
    with tempfile.TemporaryDirectory() as root:
        path, binary = Path(root) / 'test.swift', Path(root) / 'test'
        path.write_text(source)
        result = subprocess.run(['swiftc', str(path), '-o', str(binary)], capture_output=True, text=True)
        test.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=timeout)
        test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout


# Host guard: window/app-driving tests run only in the VM (run.sh sets ATTICUS_VM=1). On Saarth's Mac, launching a
# compiled fixture/harness, osascript, `open` or the Atticus binary skips the test instead of taking over his screen.
if not os.environ.get('ATTICUS_VM') and not os.environ.get('ATTICUS_ALLOW_HOST_UI'):
    import subprocess, unittest
    _popen_init = subprocess.Popen.__init__
    _tmp = os.path.realpath(tempfile.gettempdir())

    def _guarded(self, args, *a, **k):
        first = args if isinstance(args, (str, bytes, os.PathLike)) else (args[0] if args else '')
        exe = os.path.realpath(str(first).split()[0]) if first else ''
        name = os.path.basename(exe)
        if exe.startswith(_tmp) or name in ('osascript', 'open', 'Atticus', 'swift') or '/Atticus.app/' in exe:
            raise unittest.SkipTest(f'host guard: {name} runs only in the VM (run.sh)')
        _popen_init(self, args, *a, **k)
    subprocess.Popen.__init__ = _guarded


# The app runs one ask per process. A test's in-process atticus.main() left its ask folder, env and relay thread behind;
# the relay polls time.sleep until the folder goes, so a later test's fake clock or sleep mock counted its naps.
import shutil
import atticus
_main = atticus.main


def _one_ask(*a, **k):
    env = dict(os.environ)
    try:
        return _main(*a, **k)
    finally:
        state = os.path.dirname(os.environ.get('ATTICUS_HANDS_STATE', ''))
        if os.environ.get('ATTICUS_HANDS_STATE') != env.get('ATTICUS_HANDS_STATE') and os.path.basename(state).startswith('atticus-hands-'):
            shutil.rmtree(state, True)
        os.environ.clear(); os.environ.update(env)
atticus.main = _one_ask
