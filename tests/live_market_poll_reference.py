"""Frozen pre-OPT-1 P9 copy of `LiveMarketService.poll` (main 17fdbee7), the oracle for the tick-loss tests.

Generated mechanically from the original method body; only the module-level helpers it uses are imported from
the live module. Do not edit it to follow the new implementation.
"""

from dataclasses import replace

from quantlab.trading.application.live_market import LiveMarketService, _affected_minute, _replace_bars
from quantlab.trading.domain.freshness import classify_freshness
from quantlab.trading.domain.live_bars import compose_minute, finalize_minute
from quantlab.trading.domain.validation import DomainError


class ReferenceLiveMarketService(LiveMarketService):
    def poll(self, *, connected: bool | None = None, in_session: bool | None = None) -> int:
        if connected is None:
            connected = self._connection_source.connected if self._connection_source is not None else True
        self._recover_connection(connected, self.clock.now())
        before = self._views()
        previous = {key: (buffer.minute, buffer.tick, len(buffer.live), buffer.freshness) for key, buffer in self._buffers.items()}
        now = self.clock.now()
        for tick in self.market.drain_ticks(self.settings.queue_limit):
            if tick.instrument_id not in self._buffers:
                continue
            buffer = self._buffers[tick.instrument_id]
            update = compose_minute(buffer.minute, tick, incomplete=any(_affected_minute(tick.source_at, loss) for loss in buffer.losses))
            if buffer.minute is not None and buffer.minute.bar.final and update.state.bar.start > buffer.minute.bar.start:
                buffer.live.append(buffer.minute.bar)
            buffer.minute = update.state
            buffer.live.extend(update.finalized)
            if update.accepted:
                if buffer.first_live_start is None:
                    buffer.first_live_start = update.state.bar.start
                if buffer.tick is None or tick.source_at >= buffer.tick.source_at:
                    buffer.tick = tick
        if self._loss_source is not None:
            for loss in self._loss_source.drain_tick_losses():
                self.issues.append(loss)
                if loss.instrument_id not in self._buffers:
                    continue
                buffer = self._buffers[loss.instrument_id]
                buffer.losses.append(loss)
                if buffer.minute is not None and _affected_minute(buffer.minute.bar.start, loss):
                    buffer.minute = replace(buffer.minute, bar=replace(buffer.minute.bar, incomplete=True))
                for bars in (buffer.history, buffer.live):
                    _replace_bars(buffer, bars, (replace(bar, incomplete=True) if _affected_minute(bar.start, loss) else bar for bar in bars))
                self._view_cache.pop(loss.instrument_id, None)
        for key, buffer in self._buffers.items():
            if buffer.minute is not None:
                buffer.minute = finalize_minute(buffer.minute, now=now)
            session = in_session
            if session is None:
                try:
                    self.resolver.session_at(key, now)
                    session = True
                except DomainError as exc:
                    if exc.code != 'session_closed':
                        raise
                    session = False
            buffer.freshness = classify_freshness(
                buffer.tick.received_at if buffer.tick else None, now=now, connected=connected, in_session=session, settings=self.settings
            )
            if (buffer.minute, buffer.tick, len(buffer.live), buffer.freshness) != previous[key]:
                old_minute = previous[key][0]
                if buffer.minute is not None and (old_minute is None or old_minute.bar.trade_date != buffer.minute.bar.trade_date):
                    self._trim(buffer)
                self._view_cache.pop(key, None)
        if self._views() != before:
            self.market_revision += 1
        return self.market_revision
