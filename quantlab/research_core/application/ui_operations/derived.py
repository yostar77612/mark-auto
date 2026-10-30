"""Existing derived worker use cases; concrete dependencies arrive through ports."""

from quantlab.research_core.ports.ui_operations import UiOperationPorts


def _handle_ui_capital_scenario(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    return ports.capital.execute(payload, paths)


def _handle_ui_walk_forward_preview(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    return ports.walk_forward.execute_walk_forward(
        'ui_walk_forward_preview', payload, paths, descendants_stopped=descendants_stopped, dataset_loader=ports.inputs._dataset
    )


def _handle_ui_walk_forward_read(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    return ports.walk_forward.execute_walk_forward(
        'ui_walk_forward_read', payload, paths, descendants_stopped=descendants_stopped, dataset_loader=ports.inputs._dataset
    )


def _handle_ui_walk_forward_reconcile(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    return ports.walk_forward.execute_walk_forward(
        'ui_walk_forward_reconcile', payload, paths, descendants_stopped=descendants_stopped, dataset_loader=ports.inputs._dataset
    )


def _handle_ui_walk_forward_run(ports: UiOperationPorts, payload, paths, root, *, emit=None, descendants_stopped=False):
    return ports.walk_forward.execute_walk_forward(
        'ui_walk_forward_run', payload, paths, descendants_stopped=descendants_stopped, dataset_loader=ports.inputs._dataset
    )
