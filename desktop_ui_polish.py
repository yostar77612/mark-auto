"""Presentation-only labels and disabled-action explanations for the desktop host."""
from PySide6.QtCore import QObject, QEvent
from PySide6.QtWidgets import QLabel, QPushButton, QBoxLayout, QFormLayout


class DisabledHint(QObject):
    """Follow Qt's effective enabled state, including disabled parent containers."""
    def __init__(self, button, label, prerequisite):
        super().__init__(button)
        self.button, self.label, self.prerequisite = button, label, prerequisite
        self.original_tooltip = button.toolTip()
        button.installEventFilter(self)
        self.update()

    def update(self):
        disabled = not self.button.isEnabled()
        jobs = getattr(self.button.window(), 'jobs', None)
        prerequisite = ('等待目前背景作業停止' if jobs is not None and jobs.active
                        and self.button.objectName() != 'cancel_job' else self.prerequisite)
        text = '需要先完成：' + prerequisite if disabled else ''
        self.button.setToolTip(text if disabled else self.original_tooltip)
        self.button.setProperty('disabled_hint', text)
        self.label.setText(text)
        self.label.setVisible(disabled)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.EnabledChange:
            self.update()
        return False


def _insert_after(layout, widget, label, *, before=False):
    for index in range(layout.count()):
        item = layout.itemAt(index)
        if item.widget() is widget:
            if isinstance(layout, QBoxLayout):
                layout.insertWidget(index if before else index + 1, label)
            elif isinstance(layout, QFormLayout):
                row, _ = layout.getWidgetPosition(widget)
                layout.insertRow(row if before else row + 1, label)
            else:
                return False
            return True
        if item.layout() and _insert_after(item.layout(), widget, label, before=before):
            return True
    return False


def _label_field(widget, text):
    label = QLabel(text, widget.parentWidget())
    label.setBuddy(widget)
    layout = widget.parentWidget().layout()
    if layout is None or not _insert_after(layout, widget, label, before=True):
        raise ValueError('Input label has no supported layout: ' + text)
    widget.setAccessibleName(text)


def install_polish(window):
    """Install once after construction; never change action eligibility or payloads."""
    fields = {
        'market_provider': '官方行情格式', 'import_kind': '研究資料匯入格式',
        'bars': '合成示範資料長度', 'days': '最近交易日數',
        'family': '進階策略家族', 'provider_mode': '研究生成來源',
        'candidate_choice': '已保存候選版本', 'walk_forward_choice': '已保存 Walk-forward 紀錄',
        'result_choice': '已保存回測結果', 'analysis_saved': '已保存分析紀錄',
        'replay_bars': '歷史重播長度',
    }
    for name, text in fields.items():
        _label_field(getattr(window, name), text)
    _label_field(window.chatgpt_panel.account, '已保存 ChatGPT 連線')
    _label_field(window.automatic_backup_panel.directory, '自動備份資料夾')
    for widget, suffix in ((window.bars, ' 根'), (window.days, ' 日'),
                           (window.replay_bars, ' 根'), (window.chatgpt_panel.max_calls, ' 次'),
                           (window.chatgpt_panel.timeout, ' 秒')):
        widget.setSuffix(suffix)
    for _, controls in window.market._indicator_widgets.values():
        for key, widget in controls.items():
            widget.setSuffix(' 倍' if key == 'deviations' else ' 根')
    prerequisites = {
        'run_backtest': '匯入並驗證研究資料',
        'use_candidate': '選取並核對有效的不可變候選版本',
        'select_strategy': '選取符合研究／紙上資格的回測結果',
        'run_walk_forward': '預覽並核對精確切分、門檻與一次性額度',
        'pick_walk_forward_original': '將候選池來源切換為已保存研究',
        'run_candidate_analysis': '預覽分析／比較並核對尚未使用的請求紀錄',
        'reconcile_saved_analysis': '選取含原始停止紀錄且可核對的本機分析，並等待背景作業停止',
        'cancel_job': '啟動可取消的背景作業',
        'market_add': '載入官方行情商品清單',
        'market_refresh': '等待官方行情更新完成',
        'chatgpt_enable_plan': '登入並選取身分已驗證的 ChatGPT 連線',
        'chatgpt_models': '啟用方案用量並確認帳戶未暫停、無待核對請求',
        'chatgpt_clear_pause': '核對帳戶額度、已知暫停與未確認請求',
        'chatgpt_open_official': '開始授權並取得官方授權網址',
    }
    window._disabled_hints = []
    for button in window.findChildren(QPushButton):
        if not button.property('role'):
            button.setProperty('role', 'secondary')
        name = button.objectName()
        prerequisite = prerequisites.get(name, '等待目前背景作業或連線作業停止')
        if button in window.chatgpt_panel.buttons.values() and name not in prerequisites:
            prerequisite = '選取已保存的 ChatGPT 連線，並等待目前連線作業停止'
        if button is window.chatgpt_panel.cancel_button:
            prerequisite = '開始可取消的 ChatGPT 連線作業'
        label = QLabel(button.parentWidget())
        label.setWordWrap(True)
        label.setProperty('prerequisite', True)
        label.setObjectName(name + '_prerequisite')
        layout = button.parentWidget().layout()
        if layout and _insert_after(layout, button, label):
            window._disabled_hints.append(DisabledHint(button, label, prerequisite))
        else:
            label.deleteLater()
