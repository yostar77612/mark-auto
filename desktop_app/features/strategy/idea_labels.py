FAMILY_TEXT = {
    'trend': 'idea.family.trend',
    'mean_reversion': 'idea.family.mean_reversion',
    'channel_breakout': 'idea.family.channel_breakout',
    'momentum': 'idea.family.momentum',
    'volatility_compression': 'idea.family.volatility_compression',
}

TIMEFRAME_TEXT = {'1d': 'idea.timeframe_1d', '1h': 'idea.timeframe_1h', '5m': 'idea.timeframe_5m'}

DISCOVERY_TEXT = {'web_search': 'idea.discovery.web_search', 'fixed_sources': 'idea.discovery.fixed_sources', 'user_urls': 'idea.discovery.user_urls'}

STATE_TEXT = {
    'pending': 'idea.state.pending',
    'loading': 'idea.state.loading',
    'read': 'idea.state.read',
    'partial': 'idea.state.partial',
    'failed': 'idea.state.failed',
    'blocked': 'idea.state.blocked',
    'cancelled': 'idea.state.cancelled',
}

STATUS_TEXT = {
    'running': 'idea.status.running',
    'completed': 'idea.status.completed',
    'cancelled': 'idea.status.cancelled',
    'search_unavailable': 'idea.status.search_unavailable',
    'quota_paused': 'idea.status.quota_paused',
    'no_sources': 'idea.status.no_sources',
    'failed': 'idea.status.failed',
}

STOP_TEXT = {'search_limit': 'idea.stop_reason.search_limit', 'search_timeout': 'idea.stop_reason.search_timeout'}

COLUMN_TEXT = {
    'state': 'idea.column.state',
    'title': 'idea.column.title',
    'url': 'idea.column.url',
    'chars': 'idea.column.chars',
    'origin': 'idea.column.origin',
    'reason': 'idea.column.reason',
    'open': 'idea.column.open',
}

FAMILIES = tuple(FAMILY_TEXT)

STATES = tuple(STATE_TEXT)

COLUMNS = tuple(COLUMN_TEXT)
