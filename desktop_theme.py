"""Application QSS and presentation tokens; widgets select styles via properties."""

from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget, QComboBox, QLabel, QTableWidget
from desktop_strings import ui_text

MINIMUM_WINDOW_SIZE = (1280, 720)

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
NUMERIC_FONT_FAMILY = 'monospace'
SPACING = {'label': 3, 'input': 7, 'button_vertical': 9, 'button_horizontal': 14}
STATUS_COLORS = {state: COLORS[state] for state in ('success', 'warning', 'danger', 'neutral')}

# Keep the legacy dark tokens immutable: external presentation contracts use COLORS.
LIGHT_COLORS = {
    **COLORS,
    **dict.fromkeys(('background', 'navigation_background'), '#f5f7fb'),
    **dict.fromkeys(('input_background', 'table_alternate'), '#ffffff'),
    **dict.fromkeys(('muted_background', 'notification_info', 'notification_error', 'market_button'), '#e1e8f1'),
    **dict.fromkeys(('text', 'header_text', 'navigation_text', 'market_input_text', 'notification_text', 'market_button_text'), '#172b45'),
    **dict.fromkeys(('hint_text', 'disabled_text'), '#425671'),
    'button_hover': '#d4e2f4',
    'market_selection': '#b6cdec',
    'tab_selection': '#b6cdec',
    'success': '#136347',
    'danger': '#ac2436',
    'neutral': '#244f88',
    'warning': '#765000',
    'market_warning': '#765000',
    'market_rise': '#a52636',
    'market_fall': '#146448',
}
THEMES = {'dark': COLORS, 'light': LIGHT_COLORS}
THEME_KEY = 'appearance.theme'
CONVENTION_KEY = 'appearance.rise_fall'
DEFAULT_THEME = 'dark'
DEFAULT_CONVENTION = 'red_up'
CONVENTIONS = ('red_up', 'green_up')
FINANCIAL_FIELDS = frozenset(('change', 'change_pct', 'return', 'net_pnl', 'gross_pnl', 'realized_gross_pnl', 'unrealized_pnl'))
SIGN_ROLE = int(Qt.ItemDataRole.UserRole) + 41

CHART_COLORS = {
    'dark': dict(
        background='#101722',
        grid='#293547',
        text='#d7e1ee',
        flat='#b5c2d3',
        muted='#8290a3',
        reference='#ffcc80',
        signal='#e4b9ff',
        fill='#ffdb7b',
        crosshair='#a5b6cc',
        overlay=('#f8cd68', '#6aa9ff', '#bd9bff', '#64d9df', '#f099d1'),
    ),
    'light': dict(
        background='#f5f7fb',
        grid='#b8c5d6',
        text='#172b45',
        flat='#425671',
        muted='#536079',
        reference='#765000',
        signal='#793c99',
        fill='#765000',
        crosshair='#425671',
        overlay=('#765000', '#175dab', '#793c99', '#11666b', '#943f78'),
    ),
}


def load_appearance(store):
    """Read presentation preferences without repairing or overwriting corrupt stores."""
    try:
        values = store.load() if store is not None else {}
    except (OSError, ValueError, RuntimeError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    theme, convention = values.get(THEME_KEY), values.get(CONVENTION_KEY)
    return (
        theme if isinstance(theme, str) and theme in THEMES else DEFAULT_THEME,
        convention if isinstance(convention, str) and convention in CONVENTIONS else DEFAULT_CONVENTION,
    )


def appearance(widget):
    """Resolve preferences through ancestry, including not-yet-mounted children."""
    while widget is not None:
        if widget.property('appearanceTheme'):
            return widget.property('appearanceTheme'), widget.property('appearanceConvention') or DEFAULT_CONVENTION
        widget = widget.parentWidget()
    return DEFAULT_THEME, DEFAULT_CONVENTION


def theme_colors(widget):
    return THEMES[appearance(widget)[0]]


def up_down_colors(convention=DEFAULT_CONVENTION, *, theme=DEFAULT_THEME, context='chart'):
    """One convention source for candles, financial cells and labels (up, down)."""
    if convention not in CONVENTIONS:
        raise ValueError('Unknown rise/fall convention')
    palette = THEMES[theme]
    pairs = {'chart': ('#ff6575', '#35cf9b'), 'market': (palette['market_rise'], palette['market_fall']), 'status': (palette['danger'], palette['success'])}
    pair = pairs[context]
    return pair if convention == 'red_up' else pair[::-1]


def chart_color(widget, key):
    return CHART_COLORS[appearance(widget)[0]][key]


def chart_legend(widget):
    if appearance(widget)[1] == 'red_up':
        return ui_text('charts.paintEvent.text_2')
    return ui_text('appearance.legend.green_up')


def financial_sign(value):
    try:
        number = Decimal(str(value))
        return (1 if number > 0 else -1 if number < 0 else 0) if number.is_finite() else 0
    except (InvalidOperation, ValueError):
        return 0


def set_financial_label(label, value):
    sign = financial_sign(value)
    label.setProperty('financialSign', sign)
    _refresh_financial_label(label)


def _refresh_financial_label(label):
    sign = label.property('financialSign')
    theme, convention = appearance(label)
    pair = up_down_colors(convention, theme=theme, context='status')
    parent = label.parentWidget()
    while parent is not None:
        if parent.objectName() == 'market_dashboard':
            # Market QSS already swaps its semantic rise/fall tokens.
            pair = up_down_colors(theme=theme, context='status')
            break
        parent = parent.parentWidget()
    color = pair[0 if sign > 0 else 1]
    set_status(label, ('danger' if color == THEMES[theme]['danger'] else 'success') if sign else 'neutral')


def set_financial_item(table, item, value):
    item.setData(SIGN_ROLE, financial_sign(value))
    _refresh_financial_item(table, item)


def align_table_item(item, *, numeric=False):
    """Style cells and headers without touching display or sorting roles."""
    item.setTextAlignment((Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignVCenter)
    if numeric:
        font = item.font()
        font.setFamily(NUMERIC_FONT_FAMILY)
        font.setStyleHint(font.StyleHint.Monospace)
        font.setFixedPitch(True)
        item.setFont(font)


def _refresh_financial_item(table, item):
    sign = item.data(SIGN_ROLE)
    theme, convention = appearance(table)
    pair = up_down_colors(convention, theme=theme, context='market')
    item.setForeground(QColor(pair[0 if sign > 0 else 1] if sign else THEMES[theme]['text']))


def install_appearance_controls(parent, layout, store):
    """Settings advanced controls, applied immediately to their owning window."""
    theme, convention = load_appearance(store)
    parent.setProperty('appearanceTheme', theme)
    parent.setProperty('appearanceConvention', convention)
    controls = []
    for name, title, choices, selected in (
        ('appearance_theme', ui_text('appearance.theme'), (('dark', ui_text('appearance.dark')), ('light', ui_text('appearance.light'))), theme),
        (
            'appearance_convention',
            ui_text('appearance.convention'),
            (('red_up', ui_text('appearance.red_up')), ('green_up', ui_text('appearance.green_up'))),
            convention,
        ),
    ):
        combo = QComboBox(parent)
        combo.setObjectName(name)
        combo.setAccessibleName(title)
        combo.setToolTip(title)
        for key, text in choices:
            combo.addItem(text, key)
        combo.setCurrentIndex(combo.findData(selected))
        label = QLabel(title, parent)
        label.setBuddy(combo)
        layout.addWidget(label)
        layout.addWidget(combo)
        controls.append(combo)

    def changed():
        theme, convention = (control.currentData() for control in controls)
        if store is not None:
            values = store.load()
            values.update({THEME_KEY: theme, CONVENTION_KEY: convention})
            store.save(values)
        parent.setProperty('appearanceTheme', theme)
        parent.setProperty('appearanceConvention', convention)
        window = parent.window()
        window.setProperty('appearanceTheme', theme)
        window.setProperty('appearanceConvention', convention)
        apply_theme(window)

    for control in controls:
        control.currentIndexChanged.connect(changed)
    return controls


_PANEL_QSS = """
QWidget[themePart="panelCard"] { border:1px solid @table_grid@; border-radius:6px; }
QWidget[themePart="panelTitleBar"] { background:@background@; color:@text@; border:0; border-left:3px solid @focus_border@; }
QToolButton[themePart="panelTitleBar"]::menu-button { background:@background@; border:0; width:14px; }
QGroupBox[themePart="panelTitle"] { background:@background@; color:@text@; border:0; margin:0; padding:0; font-weight:600; }
QGroupBox[themePart="panelTitle"]::title { subcontrol-origin:margin; subcontrol-position:center left; padding:0; }
"""

_MARKET_QSS = """
QWidget#market_dashboard { background:@background@; color:@text@; }
QWidget#market_dashboard QWidget { background:@background@; color:@text@; }
QWidget#market_dashboard QLabel { color:@text@; }
QWidget#market_dashboard QLineEdit, QWidget#market_dashboard QComboBox, QWidget#market_dashboard QSpinBox, QWidget#market_dashboard QDoubleSpinBox, QWidget#market_dashboard QListWidget, QWidget#market_dashboard QTableWidget { background:@input_background@; color:@market_input_text@; border:1px solid @input_border@; border-radius:3px; padding:4px; selection-background-color:@market_selection@; }
QWidget#market_dashboard QPushButton { background:@market_button@; color:@market_button_text@; padding:6px 9px; border:1px solid @market_button_border@; border-radius:4px; }
QWidget#market_dashboard QToolButton:focus, QWidget#market_dashboard QPushButton:focus, QWidget#market_dashboard QComboBox:focus, QWidget#market_dashboard QLineEdit:focus { border:2px solid @focus_border@; }
QWidget#market_dashboard QCheckBox { color:@header_text@; }
QWidget#market_dashboard QHeaderView::section { background:@muted_background@; color:@header_text@; padding:5px; border:0; }
QWidget#market_dashboard QTabBar::tab { background:@muted_background@; color:@header_text@; padding:7px; }
QWidget#market_dashboard QTabBar::tab:selected { background:@tab_selection@; }
QWidget#market_dashboard QLabel#market_title { font-size:@font_market_title@px; font-weight:700; }
QWidget#market_dashboard QLabel#market_message { color:@market_warning@; }
QWidget#market_dashboard QLabel[status="success"] { color:@market_fall@; }
QWidget#market_dashboard QLabel[status="danger"] { color:@market_rise@; }
QWidget#market_dashboard QLabel[status="neutral"] { color:@text@; }
""" + _PANEL_QSS.replace('QWidget[', 'QWidget#market_dashboard QWidget[').replace('QGroupBox[', 'QWidget#market_dashboard QGroupBox[')

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
QToolButton[themePart="helpButton"] { background: @background@; color: @text@; border: 1px solid @button_border@; border-radius: 4px; padding: 2px 6px; width: 16px; }
QToolButton[themePart="helpButton"]:hover { background: @button_hover@; }
QToolButton[themePart="helpButton"]:focus { border-color: @focus_border@; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox { background: @input_background@; border: 1px solid @input_border@; border-radius: 5px; padding: @space_input@px; selection-background-color: @primary@; }
QCheckBox { padding: 7px 0; }
QTableWidget { background:@input_background@; alternate-background-color:@table_alternate@; gridline-color:@table_grid@; selection-background-color:@market_selection@; }
QHeaderView::section { background:@muted_background@; color:@header_text@; padding:6px; border:0; }
QProgressBar { border: 1px solid @input_border@; border-radius: 4px; background: @input_background@; text-align: center; }
QProgressBar::chunk { background: @primary@; }


QPushButton[role="secondary"] { background: transparent; color: @text@; border: 1px solid @button_border@; }
QPushButton[role="secondary"]:hover { background: @button_hover@; }
QPushButton[role="secondary"]:disabled { background: @muted_background@; color: @disabled_text@; }
QPushButton[role="onboardingChip"], QPushButton#onboarding_dismiss { padding:2px 8px; min-height:20px; }
QPushButton[role="onboardingChip"][state="done"] { color:@success@; border-color:@success@; }
QPushButton[role="onboardingChip"][state="pending"] { color:@text@; border-color:@button_border@; }
QWidget[role="asyncStatus"][state="error"] QLabel { color:@danger@; }
QWidget[role="asyncStatus"][state="stale"] QLabel { color:@warning@; }
QWidget[role="asyncStatus"][state="loading"] QLabel { color:@hint_text@; }
QLabel[themePart="pageTitle"] { font-size:@font_page_title@px; font-weight:600; }
QLabel[status="success"] { color:@success@; }
QLabel[status="warning"] { color:@warning@; }
QLabel[status="danger"] { color:@danger@; }
QLabel[status="neutral"] { color:@neutral@; }
QLabel#local_notification[status="neutral"] { background:@notification_info@; color:@notification_text@; padding:10px; border-radius:6px; }
QLabel#local_notification[status="danger"] { background:@notification_error@; color:@notification_text@; padding:10px; border-radius:6px; }
QWidget[feedback="true"] { border:2px solid @success@; }
"""


def _expand(template, theme=DEFAULT_THEME, convention=DEFAULT_CONVENTION):
    result = template
    palette = dict(THEMES[theme])
    palette['market_rise'], palette['market_fall'] = up_down_colors(convention, theme=theme, context='market')
    for name, value in palette.items():
        result = result.replace('@' + name + '@', value)
    for name, value in FONT_SIZES.items():
        result = result.replace('@font_' + name + '@', str(value))
    for name, value in SPACING.items():
        result = result.replace('@space_' + name + '@', str(value))
    return result


def build_app_stylesheet(theme=DEFAULT_THEME, convention=DEFAULT_CONVENTION):
    """Return the application styles (market dashboard styles are widget-scoped)."""
    return _expand(_QSS + _PANEL_QSS, theme, convention)


def build_market_stylesheet(theme=DEFAULT_THEME, convention=DEFAULT_CONVENTION):
    """Return the standalone-capable dark market dashboard styles."""
    return _expand(_MARKET_QSS, theme, convention)


def apply_market_theme(widget):
    """Scope the market dashboard styles to its own widget (preserves standalone look)."""
    widget.setStyleSheet(build_market_stylesheet(*appearance(widget)))


def scale_window_fonts(window, factor):
    """Emulate a larger logical UI font, including the theme's explicit pixel fonts.

    Scoped to one window; never restyle the QApplication or change raster DPI.
    """
    # Regex is needed only by the diagnostic font-scaling helper.
    import re

    def scaled(stylesheet):
        return re.sub(r'font-size:\s*(\d+)px', lambda match: 'font-size:' + str(round(int(match[1]) * factor)) + 'px', stylesheet)

    window.setStyleSheet(scaled(build_app_stylesheet(*appearance(window))))
    window.market.setStyleSheet(scaled(build_market_stylesheet(*appearance(window))))


def apply_theme(target=None):
    """Apply the application theme to `target` (a window: scoped like the former window QSS,
    so independently hosted top-level widgets are unaffected) or, with no widget, to the
    QApplication."""
    if isinstance(target, QWidget) and not target.property('appearanceTheme'):
        theme, convention = load_appearance(getattr(target, 'settings', None))
        target.setProperty('appearanceTheme', theme)
        target.setProperty('appearanceConvention', convention)
    stylesheet = build_app_stylesheet(*(appearance(target) if isinstance(target, QWidget) else (DEFAULT_THEME, DEFAULT_CONVENTION)))
    if isinstance(target, QWidget):
        if target.styleSheet() != stylesheet:
            target.setStyleSheet(stylesheet)
        for widget in [target] + target.findChildren(QWidget):
            if widget.property('themePart') in ('panelCard', 'panelTitleBar', 'panelTitle'):
                set_theme_property(widget, 'themePart', widget.property('themePart'))
            if widget.objectName() == 'market_dashboard':
                apply_market_theme(widget)
            if isinstance(widget, QLabel) and widget.property('financialSign') is not None:
                _refresh_financial_label(widget)
            if isinstance(widget, QTableWidget):
                for row in range(widget.rowCount()):
                    for column in range(widget.columnCount()):
                        item = widget.item(row, column)
                        if item is not None and item.data(SIGN_ROLE) is not None:
                            _refresh_financial_item(widget, item)
            widget.update()
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
