"""Small callback-driven sequencer; workers and presentation belong to the host."""


class QuickStartChain:
    def __init__(self, start, apply_strategy, results, notice):
        self.start = start
        self.apply_strategy = apply_strategy
        self.results = results
        self.notice = notice
        self.stage = None
        self.job_id = None
        self.pending = None

    def begin(self, confirmed, busy=False):
        if not confirmed or busy or self.stage is not None:
            return False
        self.stage = 'data'
        self._launch('ui_demo', {'bars': 960, 'synthetic_quick_start': True})
        return True

    def _launch(self, operation, payload):
        try:
            self.notice(self.stage)
            self.job_id = self.start(operation, payload)
        except Exception:
            self.stop('error')

    def accept(self, event):
        if self.stage is not None and event.get('job_id') == self.job_id:
            if event.get('type') == 'result':
                self.pending = event.get('result', {})
            elif event.get('type') in ('error', 'failed', 'cancelled', 'canceled'):
                self.stop('error' if event['type'] in ('error', 'failed') else 'cancelled')

    def advance(self, busy=False):
        if busy or self.pending is None or self.stage is None:
            return
        result, self.pending = self.pending, None
        try:
            if self.stage == 'data':
                payload = self.apply_strategy()
                payload['synthetic_quick_start'] = True
                self.stage = 'backtest'
                self._launch('ui_backtest', payload)
            else:
                self.results(result)
                self.stop('done')
        except Exception:
            self.stop('error')

    def stop(self, notice='cancelled'):
        self.stage = self.job_id = self.pending = None
        self.notice(notice)
