"""Application QSS and presentation tokens; widgets select styles via properties."""
from PySide6.QtWidgets import QApplication, QWidget

COLORS = {
    'background': '#101720',
    'navigation_background': '#12243b',
    'input_background': '#172230',
    'button_hover': '#1b4f9b',
    'table_alternate': '#1d2b3c',
    'notification_info': '#213b50',
    'muted_background': '#243448',
    'market_button': '#24384c',
    'primary': '#2563ba',
    'market_selection': '#285f89',
    'navigation_selection': '#2865c4',
    'table_grid': '#354459',
    'tab_selection': '#366487',
    'input_border': '#43566c',
    'notification_error': '#502b30',
    'market_button_border': '#506a82',
    'button_border': '#526b87',
    'market_fall': '#76d6b0',
    'focus_border': '#7cb9ed',
    'success': '#82c9ae',
    'danger_background': '#842e38',
    'disabled_text': '#9aabbc',
    'neutral': '#a9c8ee',
    'hint_text': '#aebed0',
    'text': '#dbe4ef',
    'danger_border': '#e06670',
    'header_text': '#e0e8f3',
    'navigation_text': '#e3edf9',
    'market_warning': '#e8c37a',
    'market_input_text': '#e8edf4',
    'notification_text': '#e8f1ff',
    'market_button_text': '#eaf0f7',
    'warning': '#f1b65c',
    'market_rise': '#f58b8b',
    'danger': '#ff8282',
}
FONT_SIZES = {'body': 14, 'hint': 12, 'page_title': 22, 'market_title': 20}
SPACING = {'label': 3, 'input': 7, 'button_vertical': 9, 'button_horizontal': 14}
STATUS_COLORS = {state: COLORS[state] for state in ('success', 'warning', 'danger', 'neutral')}

_MARKET_QSS = """
QWidget#market_dashboard { background:@background@; color:@text@; }
QWidget#market_dashboard QWidget { background:@background@; color:@text@; }
QWidget#market_dashboard QLabel { color:@text@; }
QWidget#market_dashboard QGroupBox { border:1px solid @table_grid@; border-radius:6px; margin-top:10px; padding:9px; font-weight:600; color:@text@; }
QWidget#market_dashboard QGroupBox::title { subcontrol-origin:margin; left:10px; }
QWidget#market_dashboard QLineEdit, QWidget#market_dashboard QComboBox, QWidget#market_dashboard QSpinBox, QWidget#market_dashboard QDoubleSpinBox, QWidget#market_dashboard QListWidget, QWidget#market_dashboard QTableWidget { background:@input_background@; color:@market_input_text@; border:1px solid @input_border@; border-radius:3px; padding:4px; selection-background-color:@market_selection@; }
QWidget#market_dashboard QPushButton { background:@market_button@; color:@market_button_text@; padding:6px 9px; border:1px solid @market_button_border@; border-radius:4px; }
QWidget#market_dashboard QPushButton:focus, QWidget#market_dashboard QComboBox:focus, QWidget#market_dashboard QLineEdit:focus { border:2px solid @focus_border@; }
QWidget#market_dashboard QCheckBox { color:@header_text@; }
QWidget#market_dashboard QHeaderView::section { background:@muted_background@; color:@header_text@; padding:5px; border:0; }
QWidget#market_dashboard QTabBar::tab { background:@muted_background@; color:@header_text@; padding:7px; }
QWidget#market_dashboard QTabBar::tab:selected { background:@tab_selection@; }
QWidget#market_dashboard QLabel#market_title { font-size:@font_market_title@px; font-weight:700; }
QWidget#market_dashboard QGroupBox[themePart="marketCard"] { padding:3px; }
QWidget#market_dashboard QLabel#market_message { color:@market_warning@; }
QWidget#market_dashboard QLabel[status="success"] { color:@market_fall@; }
QWidget#market_dashboard QLabel[status="danger"] { color:@market_rise@; }
QWidget#market_dashboard QLabel[status="neutral"] { color:@text@; }
"""

_QSS = """
QMainWindow, QScrollArea, QStackedWidget { background: @background@; }
QWidget { background: @background@; font-family: "Microsoft JhengHei UI", "Noto Sans CJK TC", sans-serif; font-size: @font_body@px; color: @text@; }
QLabel { padding: @space_label@px 0; }
QWidget[resultCard="true"] { background: @input_background@; border: 1px solid @input_border@; border-radius: 6px; }
QLabel[kpiValue="true"] { font-size: 18px; font-weight: bold; }
QListWidget { background: @navigation_background@; color: @navigation_text@; border: none; border-radius: 9px; padding: 9px; }
QListWidget::item { padding: 12px 8px; border-radius: 5px; }
QListWidget::item:selected { background: @navigation_selection@; color: white; }
QPushButton { background: transparent; color: @text@; border: 1px solid @button_border@; border-radius: 6px; padding: @space_button_vertical@px @space_button_horizontal@px; min-height: 20px; }
QPushButton[role="primary"] { background: @primary@; color: white; border: 1px solid @primary@; }
QPushButton[role="danger"] { background: @danger_background@; color: white; border: 1px solid @danger_border@; }
QLabel[prerequisite="true"] { color: @hint_text@; font-size: @font_hint@px; }
QPushButton:hover { background: @button_hover@; }
QPushButton:disabled { background: @muted_background@; color: @disabled_text@; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: @input_background@; border: 1px solid @input_border@; border-radius: 5px; padding: @space_input@px; selection-background-color: @primary@; }
QCheckBox { padding: 7px 0; }
QTableWidget { background:@input_background@; alternate-background-color:@table_alternate@; gridline-color:@table_grid@; selection-background-color:@market_selection@; }
QHeaderView::section { background:@muted_background@; color:@header_text@; padding:6px; border:0; }
QProgressBar { border: 1px solid @input_border@; border-radius: 4px; background: @input_background@; text-align: center; }
QProgressBar::chunk { background: @primary@; }


QPushButton[role="secondary"] { background: transparent; color: @text@; border: 1px solid @button_border@; }
QPushButton[role="secondary"]:hover { background: @button_hover@; }
QPushButton[role="secondary"]:disabled { background: @muted_background@; color: @disabled_text@; }
QLabel[themePart="pageTitle"] { font-size:@font_page_title@px; font-weight:600; }
QLabel[status="success"] { color:@success@; }
QLabel[status="warning"] { color:@warning@; }
QLabel[status="danger"] { color:@danger@; }
QLabel[status="neutral"] { color:@neutral@; }
QLabel#local_notification[status="neutral"] { background:@notification_info@; color:@notification_text@; padding:10px; border-radius:6px; }
QLabel#local_notification[status="danger"] { background:@notification_error@; color:@notification_text@; padding:10px; border-radius:6px; }
QWidget[feedback="true"] { border:2px solid @success@; }
"""


def _expand(template):
    result = template
    for name, value in COLORS.items():
        result = result.replace('@' + name + '@', value)
    for name, value in FONT_SIZES.items():
        result = result.replace('@font_' + name + '@', str(value))
    for name, value in SPACING.items():
        result = result.replace('@space_' + name + '@', str(value))
    return result


def build_app_stylesheet():
    """Return the application styles (market dashboard styles are widget-scoped)."""
    return _expand(_QSS)


def build_market_stylesheet():
    """Return the standalone-capable dark market dashboard styles."""
    return _expand(_MARKET_QSS)


def apply_market_theme(widget):
    """Scope the market dashboard styles to its own widget (preserves standalone look)."""
    widget.setStyleSheet(build_market_stylesheet())


def apply_theme(target=None):
    """Apply the application theme to `target` (a window: scoped like the former window QSS,
    so independently hosted top-level widgets are unaffected) or, with no widget, to the
    QApplication."""
    stylesheet = build_app_stylesheet()
    if isinstance(target, QWidget):
        if target.styleSheet() != stylesheet:
            target.setStyleSheet(stylesheet)
        return
    app = target or QApplication.instance()
    if app is None:
        raise RuntimeError('A QApplication is required')
    if app.styleSheet() != stylesheet:
        app.setStyleSheet(stylesheet)


def set_theme_property(widget, name, value):
    """Refresh Qt's cached property selectors after a presentation change."""
    widget.setProperty(name, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_status(widget, state):
    if state not in STATUS_COLORS:
        raise ValueError('Unknown status state: ' + str(state))
    set_theme_property(widget, 'status', state)


def status_for_color(color):
    """Bridge the existing stop_presentation colour contract without changing it."""
    return next(state for state, value in STATUS_COLORS.items() if value == color)
