"""Fixed worker diagnostics. Stages never originate from exception values."""

JOB_STAGES = frozenset({'unknown', 'prepare_operation', 'load_data', 'build_candidates', 'run_backtest', 'run_campaign', 'run_operation', 'write_result'})


def normalize_stage(value):
    return value if type(value) is str and value in JOB_STAGES else 'unknown'


# Function names seen in a failing traceback map to a stage; text never does.
_FRAME_STAGES = {
    '_dataset': 'load_data',
    'config_from_json': 'build_candidates',
    'builtin_strategies': 'build_candidates',
    'demo_campaign_config': 'build_candidates',
    'campaign_generator': 'build_candidates',
    'run_backtest': 'run_backtest',
    'run_campaign': 'run_campaign',
    'to_dict': 'write_result',
    '_json_bytes': 'write_result',
    'atomic_write': 'write_result',
}


def stage_from_traceback(tb, fallback):
    """Innermost mapped frame wins; frame names are code, never user text."""
    found = None
    while tb is not None:
        found = _FRAME_STAGES.get(tb.tb_frame.f_code.co_name, found)
        tb = tb.tb_next
    return normalize_stage(found or fallback)
