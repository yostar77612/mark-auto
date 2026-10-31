"""Restore the desktop walk-forward port binding after the C/D integration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    bootstrap = ROOT / 'desktop_app/bootstrap.py'
    source = bootstrap.read_text(encoding='utf-8')
    source = source.replace(
        'import quantlab.research_core.application.walk_forward_operations as implementation',
        'import desktop_app.features.walk_forward.presenter as implementation',
    )
    bootstrap.write_text(source, encoding='utf-8', newline='\n')
    presenter = ROOT / 'desktop_app/features/walk_forward/presenter.py'
    source = presenter.read_text(encoding='utf-8')
    if '\ndef execute_walk_forward(' not in source:
        source += '''


def execute_walk_forward(operation, payload, paths, *, descendants_stopped=False, inputs):
    """Render application results at the Qt-free desktop operation boundary."""
    from quantlab.research_core.application.walk_forward_operations import execute_walk_forward as execute

    return render_result(execute(operation, payload, paths, descendants_stopped=descendants_stopped, inputs=inputs))
'''
    presenter.write_text(source, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()
