"""The readability audit's contrast heuristic on synthetic images."""

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest

from PySide6.QtGui import QColor, QImage

from tools.ui_readability_audit import contrast, image_contrast


def image(background, text, *, text_pixels=40):
    result = QImage(40, 20, QImage.Format.Format_RGB32)
    result.fill(QColor(*background))
    for index in range(text_pixels):
        result.setPixelColor(5 + index % 30, 8 + index // 30, QColor(*text))
    return result


class ReadabilityAuditTests(unittest.TestCase):
    def test_wcag_contrast_reference_values(self):
        self.assertAlmostEqual(contrast((0, 0, 0), (255, 255, 255)), 21.0, places=2)
        self.assertAlmostEqual(contrast((255, 255, 255), (255, 255, 255)), 1.0, places=2)
        self.assertEqual(contrast((10, 20, 30), (200, 210, 220)), contrast((200, 210, 220), (10, 20, 30)))

    def test_light_text_on_white_tab_is_flagged_and_dark_text_is_not(self):
        background, text, ratio = image_contrast(image((255, 255, 255), (217, 217, 217)))
        self.assertEqual((background, text), ((255, 255, 255), (217, 217, 217)))
        self.assertLess(ratio, 4.5)
        self.assertGreater(image_contrast(image((16, 23, 32), (224, 232, 243)))[2], 4.5)

    def test_blank_or_tiny_images_are_not_measured(self):
        self.assertIsNone(image_contrast(QImage(1, 1, QImage.Format.Format_RGB32)))
        self.assertEqual(image_contrast(image((40, 40, 40), (40, 40, 40), text_pixels=0))[2], 1.0)


if __name__ == '__main__':
    unittest.main()
