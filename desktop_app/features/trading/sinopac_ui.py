"""Small Qt/application bridge for the single connection intent boundary."""

from dataclasses import replace

from quantlab.trading.application.contracts import UiAction
from desktop_app.features.trading.broker_panel import BrokerPanel


CONNECTION_ACTIONS = frozenset((UiAction.SAVE_AND_CONNECT_SINOPAC, UiAction.SELECT_SINOPAC_ACCOUNTS, UiAction.ACTIVATE_SINOPAC_CA, UiAction.DISCONNECT_SINOPAC))


def install_panel(window, layout):
    window.broker_panel = BrokerPanel(confirm=lambda value: window._confirm(value))
    window.broker_panel.save_connect_requested.connect(
        lambda settings, revision, generation: window.command(
            UiAction.SAVE_AND_CONNECT_SINOPAC, sinopac_settings=settings, connection_revision=revision, connection_generation=generation
        )
    )
    window.broker_panel.accounts_requested.connect(
        lambda accounts, revision, generation: window.command(
            UiAction.SELECT_SINOPAC_ACCOUNTS, sinopac_accounts=accounts, connection_revision=revision, connection_generation=generation
        )
    )
    window.broker_panel.certificate_requested.connect(
        lambda settings, revision, generation: window.command(
            UiAction.ACTIVATE_SINOPAC_CA, sinopac_settings=settings, connection_revision=revision, connection_generation=generation
        )
    )
    window.broker_panel.disconnect_requested.connect(
        lambda revision, generation: window.command(UiAction.DISCONNECT_SINOPAC, connection_revision=revision, connection_generation=generation)
    )
    layout.addWidget(window.broker_panel)


def render_connection(window, state):
    window.broker_panel.apply(state.sinopac_connection)
    accepted = window.broker_panel.view
    if (state.contexts, state.accounts) != (window.state.contexts, window.state.accounts):
        # Discovery changes available choices without changing the viewed book.
        window._rendered_version = None
    if window.state.sinopac_connection != accepted:
        window.state = replace(window.state, sinopac_connection=accepted)
    return replace(state, sinopac_connection=accepted)


def complete_connection(window, state, receipt, action):
    if action not in CONNECTION_ACTIONS:
        return False
    window._engine_reachable = True
    window.broker_panel.apply(state.sinopac_connection)
    if receipt is not None:
        window.broker_panel.complete(window._operation.command, receipt)
    window.apply_state(state)
    return True
