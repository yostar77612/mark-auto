"""Paint geometry only. Offline generated fixtures; no Windows DPI claim."""
import os,unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont,QFontMetrics
from desktop_charts import _footer_items,ChartTrace
from tests import test_result_reference_layers as references


class FooterGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def test_all_footer_slots_stay_in_bounds_without_overlap(self):
        trace=ChartTrace('TAIFEX:TMF:202610','a'*64,'b'*64,'回測')
        for size in (14,18,21):
            font=QFont('Noto Sans CJK TC');font.setPixelSize(size);fm=QFontMetrics(font)
            for width in (0,20,100,266,431,611,974,1600):
                for labels in (('2026/10/01 09:00 台北時間','2026/10/01 09:03 台北時間'),('2026-10-01','2026-10-03'),('時間未提供／未驗證','時間未提供／未驗證')):
                    for bound in (None,trace):
                        with self.subTest(size=size,width=width,labels=labels,trace=bool(bound)):
                            items=_footer_items(width,fm,*labels,bound);previous=0
                            for start,slot,label in items:
                                self.assertGreaterEqual(start,previous);self.assertGreaterEqual(slot,0)
                                self.assertLessEqual(start+slot,width);self.assertLessEqual(fm.horizontalAdvance(label),slot)
                                previous=start+slot
    def test_wide_footer_keeps_full_text_narrow_keeps_mode(self):
        font=QFont('Noto Sans CJK TC');font.setPixelSize(14);fm=QFontMetrics(font);trace=ChartTrace('TAIFEX:TMF:202610','a'*64,'b'*64,'紙上')
        labels=('2026/10/01 09:00 台北時間','2026/10/01 09:03 台北時間')
        wide=_footer_items(1600,fm,*labels,trace);self.assertEqual(wide[0][2],labels[0]);self.assertEqual(wide[-1][2],labels[1]);self.assertIn('策略 bbbbbbbb',wide[1][2])
        narrow=_footer_items(431,fm,*labels,trace);self.assertEqual(narrow[1][2],'紙上')


class FooterHostTests(unittest.TestCase):
    setUpClass=references.ResultReferenceHostTests.__dict__['setUpClass']
    setUp=references.ResultReferenceHostTests.setUp
    cleanup_window=references.ResultReferenceHostTests.cleanup_window
    install=references.ResultReferenceHostTests.install
    def test_tooltip_retains_full_times_identity_and_crosshair(self):
        self.install(mtm=True);chart=self.window.market.chart;chart.resize(525,408);chart.show()
        bars,trace,refs,ranges=chart.bars,chart.trace,chart.reference_lines,chart.visible_range
        chart.repaint();self.app.processEvents()
        for text in ('2026/10/01 09:00 台北時間','2026/10/01 09:03 台北時間',trace.data_hash,trace.strategy_hash):self.assertIn(text,chart.toolTip())
        chart.crosshair_index=1;chart.repaint();self.app.processEvents()
        self.assertIn('顯示範圍起點',chart.toolTip());self.assertIn('期末快照',chart.toolTip())
        self.assertEqual((chart.bars,chart.trace,chart.reference_lines,chart.visible_range),(bars,trace,refs,ranges))
        chart.set_series(());chart.repaint();self.app.processEvents();self.assertEqual(chart.toolTip(),'')

if __name__=='__main__':unittest.main(verbosity=2)
