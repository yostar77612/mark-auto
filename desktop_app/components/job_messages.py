"""Worker stage error text, presented through the canonical catalog lookup."""

from desktop_app.strings.catalog import ui_text


def stage_error_message(stage):
    # Share the fixed wire-code allow-list with the worker, without UI imports there.
    from quantlab.job_stages import normalize_stage

    messages = {
        'unknown': ui_text('worker.stage.unknown'),
        'prepare_operation': ui_text('worker.stage.prepare_operation'),
        'load_data': ui_text('worker.stage.load_data'),
        'build_candidates': ui_text('worker.stage.build_candidates'),
        'run_backtest': ui_text('worker.stage.run_backtest'),
        'run_campaign': ui_text('worker.stage.run_campaign'),
        'run_operation': ui_text('worker.stage.run_operation'),
        'write_result': ui_text('worker.stage.write_result'),
    }
    return messages[normalize_stage(stage)]
