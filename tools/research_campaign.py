"""Developer web-host process boundary; the original research engine stays authoritative."""

from pathlib import Path
import os
import signal
import subprocess
import sys
import tempfile
import time

from quantlab.reporting import save_dataset, write_json, read_json
from quantlab.core import Dataset

_RETAINED = []
_BOOTSTRAP = (
    "import sys\nif sys.stdin.buffer.read(1) != b'1':\n    raise SystemExit(3)\nfrom quantlab.__main__ import main\nraise SystemExit(main(sys.argv[1:]))\n"
)
_ROOT = Path(__file__).resolve().parents[1]


def run_fixture_campaign(dataset: Dataset, config: dict, output_dir: Path) -> dict:
    """Run the existing fixture CLI without importing Streamlit in its children.

    An admission pipe precedes all work; Windows owns descendants in the original
    Job Object supervisor, and POSIX owns a separate process group. No research,
    reservation or database operation is retried. Unknown stop retains inputs.
    """
    if _RETAINED:
        raise RuntimeError('A prior campaign worker stop remains unverified')
    seconds = config.get('max_runtime_seconds')
    if type(seconds) is not int or not 1 <= seconds <= 7200:
        raise ValueError('Invalid campaign runtime budget')
    inputs = tempfile.TemporaryDirectory(prefix='web-campaign-')
    directory = Path(inputs.name)
    process = tree = None
    try:
        save_dataset(dataset, directory / 'dataset.json')
        write_json(directory / 'config.json', config)
        command = [
            sys.executable,
            '-c',
            _BOOTSTRAP,
            'campaign',
            str(directory / 'dataset.json'),
            '--config',
            str(directory / 'config.json'),
            '--output',
            str(Path(output_dir).resolve()),
        ]
        process = subprocess.Popen(
            command,
            cwd=_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            start_new_session=sys.platform != 'win32',
        )
        if sys.platform == 'win32':
            from quantlab.desktop_runtime import _WindowsProcessTree

            tree = _WindowsProcessTree(process.pid)
        started = time.monotonic()
        process.stdin.write(b'1')
        process.stdin.close()
        process.stdin = None
        try:
            status = process.wait(timeout=max(0, seconds - (time.monotonic() - started)))
        except subprocess.TimeoutExpired:
            raise TimeoutError('Campaign worker exceeded its unchanged runtime budget') from None
        if status != 0:
            raise RuntimeError('Campaign worker failed; inspect retained campaign history')
        return read_json(Path(output_dir) / 'campaign.json')
    finally:
        try:
            if process is not None:
                if tree is not None:
                    tree.stop_and_join()
                    tree.close()
                elif sys.platform == 'win32':
                    if process.poll() is None:
                        process.kill()
                else:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                process.wait(timeout=6)
                if process.stdin is not None:
                    process.stdin.close()
            inputs.cleanup()
        except BaseException:
            inputs._finalizer.detach()
            _RETAINED.append((inputs, process, tree))
            raise
