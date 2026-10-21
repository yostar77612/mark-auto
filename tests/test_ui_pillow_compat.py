"""Streamlit's image path under the deliberately overridden Pillow 13 pin."""

import importlib.util
import unittest

HAS_STREAMLIT = importlib.util.find_spec('streamlit') is not None and importlib.util.find_spec('PIL') is not None


def _image_app():
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


@unittest.skipUnless(HAS_STREAMLIT, 'Optional Streamlit/Pillow is not installed; UI image verification not run')
class StreamlitPillowCompatibilityTests(unittest.TestCase):
    def test_pillow_major_carries_the_audit_fix(self):
        import PIL

        self.assertGreaterEqual(int(PIL.__version__.split('.')[0]), 13)

    def test_st_image_renders_pil_numpy_and_encoded_bytes(self):
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_function(_image_app).run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.get('image')), 4)

    def test_streamlit_hashes_pil_images(self):
        from PIL import Image
        from streamlit.runtime.caching.hashing import update_hash

        import hashlib

        digest = hashlib.new('md5', usedforsecurity=False)
        update_hash(Image.new('RGB', (2, 2)), digest, 'test', None)
        self.assertTrue(digest.hexdigest())


if __name__ == '__main__':
    unittest.main()
