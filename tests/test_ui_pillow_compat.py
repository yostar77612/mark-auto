"""Pillow 13 override: static lock contract plus Streamlit image path when installed."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None and importlib.util.find_spec('PIL') is not None

# Runs in a child interpreter: AppTest.from_function rewrites __main__, which would
# otherwise break later multiprocessing 'spawn' tests in this process.
CHILD = """
import hashlib
import io

import numpy as np
import PIL
import streamlit as st
from PIL import Image
from streamlit.runtime.caching.hashing import update_hash
from streamlit.testing.v1 import AppTest

assert int(PIL.__version__.split('.')[0]) >= 13, PIL.__version__


def image_app():
    import io

    import numpy as np
    import streamlit as st
    from PIL import Image

    pil = Image.new('RGBA', (16, 8), (10, 20, 30, 128))
    buffer = io.BytesIO()
    pil.save(buffer, format='PNG')
    st.image(pil)
    st.image(np.zeros((8, 16, 3), dtype=np.uint8))
    st.image(buffer.getvalue(), width=8)
    st.image(pil.convert('P'), output_format='PNG')


if __name__ == '__main__':
    app = AppTest.from_function(image_app).run(timeout=30)
    assert not app.exception, app.exception
    assert len(app.get('image')) == 4
    digest = hashlib.new('md5', usedforsecurity=False)
    update_hash(Image.new('RGB', (2, 2)), digest, 'test', None)
    assert digest.hexdigest()
    print('ok')
"""


class PillowOverrideTests(unittest.TestCase):
    """Never skipped: the core coverage gate pins the exact set of allowed skips."""

    def test_override_lock_is_separate_and_ui_lock_has_no_conflicting_pin(self):
        override = (ROOT / 'requirements-ui-pillow.lock').read_text(encoding='utf-8')
        ui_lock = (ROOT / 'requirements-ui.lock').read_text(encoding='utf-8')
        self.assertIn('pillow==13.0.0', override.splitlines())
        self.assertNotIn('pillow==', ui_lock)
        self.assertIn('certifi==2026.10.19', ui_lock.splitlines())

    def test_streamlit_image_path_under_pillow_13_when_installed(self):
        if not HAS_STREAMLIT:
            return
        done = subprocess.run([sys.executable, '-c', CHILD], capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn('ok', done.stdout)


if __name__ == '__main__':
    unittest.main()
