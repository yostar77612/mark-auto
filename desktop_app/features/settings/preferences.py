"""Display-only persistence adapters; no jobs, actions or provider settings."""

from PySide6.QtWidgets import QSplitter, QScrollArea
from quantlab.runtime_support import RuntimeSafetyError
from quantlab.ui_preferences import page_row, bounded_size, splitter_sizes
from desktop_app.strings.catalog import ui_text


def disclosure_value(key, toggle, stored):
    """Read old disclosure preferences without rewriting their keys."""
    stored = stored if isinstance(stored, dict) else {}
    if type(stored.get(key)) is bool:
        return stored[key]
    legacy = {
        'redesign_data_details': '2:' + ui_text('ui.advanced.default_title'),
        'redesign_backtest_advanced': '4:' + ui_text('ui.advanced.default_title'),
        'redesign_compare_details': '5:' + ui_text('ui.advanced.default_title'),
    }.get(key)
    if legacy and type(stored.get(legacy)) is bool:
        return stored[legacy]
    if key == 'paper_preparation' and any(name.startswith('6:') and value is True for name, value in stored.items() if isinstance(name, str)):
        return True
    return toggle.property('defaultExpanded') is True


def load_store(store):
    if store is None:
        return {}
    try:
        value = store.load()
        return value if type(value) is dict else {}
    except (OSError, ValueError, RuntimeSafetyError, UnicodeError, RecursionError):
        # Preserve corrupt originals: SettingsStore.save still refuses overwrites.
        return {}


def identities(stack):
    result = []
    for index in range(stack.count()):
        page = stack.widget(index)
        if isinstance(page, QScrollArea):
            page = page.widget()
        result.append(type(page).__module__ + '.' + type(page).__name__)
    return result


def install_sidebar(window, layout):
    splitter = QSplitter(window)
    splitter.setHandleWidth(layout.spacing())
    splitter.setMinimumWidth(200 + splitter.handleWidth())
    splitter.resize(max(200, window.width() - 24), window.height())
    window.navigation.setMinimumWidth(120)
    splitter.addWidget(window.navigation)
    splitter.addWidget(window.stack)
    splitter.setCollapsible(0, False)
    splitter.setCollapsible(1, False)
    splitter.setStretchFactor(1, 1)
    splitter.setSizes([180, 1100])
    layout.addWidget(splitter, 1)
    window.page_state.preference_sidebar = splitter
    window.page_state.preference_navigation = window.navigation
    window.page_state.preference_stack = window.stack


def _parts(page):
    state = getattr(getattr(page, 'host', None), 'state', None)
    navigation = getattr(state, 'preference_navigation', None)
    stack = getattr(state, 'preference_stack', None)
    sidebar = getattr(state, 'preference_sidebar', None)
    market = getattr(state, 'market', None)
    splitters = {'sidebar': sidebar, 'market': getattr(market, 'main_splitter', None)}
    return state, navigation, stack, splitters


def save_preferences(page, value):
    state, navigation, stack, splitters = _parts(page)
    if navigation is not None and stack is not None:
        keys = identities(stack)
        row = navigation.currentRow()
        value['last_page'] = keys[row] if 0 <= row < len(keys) else keys[0]
        value['sidebar_width'] = bounded_size(navigation.width(), 120, navigation.maximumWidth(), 180)
    value['splitter_sizes'] = {key: item.sizes() for key, item in splitters.items() if item is not None}
    form = getattr(state, 'strategy_form', None)
    if form is not None:
        value['family_parameters'] = form.preference_parameters()


def restore_preferences(page, value):
    state, navigation, stack, splitters = _parts(page)
    if navigation is not None and stack is not None:
        navigation.setCurrentRow(page_row(value.get('last_page'), identities(stack)))
    saved = value.get('splitter_sizes', {})
    saved = saved if type(saved) is dict else {}
    for key, item in splitters.items():
        if item is None:
            continue
        maximum = max(80, item.screen().availableGeometry().width())
        sizes = splitter_sizes(saved.get(key), item.count(), maximum)
        if key == 'sidebar':
            width = bounded_size(value.get('sidebar_width'), 120, min(180, navigation.maximumWidth()), 180)
            sizes = [width, max(80, item.width() - width - item.handleWidth())]
        if sizes is not None:
            item.setSizes(sizes)
    form = getattr(state, 'strategy_form', None)
    if form is not None:
        form.restore_preference_parameters(value.get('family_parameters'))
