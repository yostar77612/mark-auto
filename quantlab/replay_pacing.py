"""Session-only pacing, separate from replay identity and simulated timestamps."""

from time import monotonic

from .core import ValidationError


SPEEDS = (1, 2, 5, 10, 50, 100)
# One bar per operation at every speed. No sleeping inside a paper worker.
TICK_BARS = 1


class ReplayPacer:
    def __init__(self, speed=1, *, clock=monotonic):
        self.clock = clock
        self.set_speed(speed)
        self.due = clock()

    def set_speed(self, speed):
        if type(speed) is not int or speed not in SPEEDS:
            raise ValidationError('Replay speed must be one of 1, 2, 5, 10, 50, 100')
        self.speed = speed

    def defer(self):
        self.due = self.clock() + 1 / self.speed

    def ready(self):
        return self.clock() >= self.due


def control(replay, action):
    """One short worker operation, independent of speed; caller owns timeout."""
    if action == 'inspect':
        return replay.snapshot()
    if action == 'pause':
        return replay.pause()
    if action == 'resume':
        return replay.resume()
    if action == 'stop':
        return replay.stop()
    if action != 'tick':
        raise ValidationError('Unsupported replay control')
    state = replay.snapshot()
    if state.get('paused', False):
        raise ValidationError('Paused replay requires explicit resume')
    if not state['active']:
        replay.start()
    try:
        return replay.step(max_bars=TICK_BARS)
    except BaseException:
        replay.stop()
        raise
