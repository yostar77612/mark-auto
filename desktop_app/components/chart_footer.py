"""desktop_app components chart_footer responsibilities."""

from desktop_app.strings.catalog import ui_text
from datetime import datetime
from zoneinfo import ZoneInfo
from PySide6.QtCore import Qt


def _display_time(value, date_only=''):
    """Presentation only; no timezone inference for unverified naive values."""
    if value is None:
        return date_only or ui_text('charts.display_time.time_unverified')
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return ui_text('charts.display_time.time_unverified')
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return ui_text('charts.display_time.time_unverified')
    return ui_text('charts.display_time.taipei_time').format(value.astimezone(ZoneInfo('Asia/Taipei')).strftime('%Y/%m/%d %H:%M'))


def _footer_items(width, metrics, first_time, last_time, trace=None):
    """Non-overlapping single-row paint slots; full labels stay in the tooltip."""
    width = max(0, int(width))
    gap = 8
    first_width = metrics.horizontalAdvance(first_time)
    last_width = metrics.horizontalAdvance(last_time)
    trace_text = ui_text('charts.footer_items.trace_hashes').format(trace.mode, trace.data_hash[:8], trace.strategy_hash[:8]) if trace else ''
    trace_width = metrics.horizontalAdvance(trace_text)
    if first_width + last_width + trace_width + gap * (2 if trace else 1) <= width:
        items = [(0, first_width, first_time), (width - last_width, last_width, last_time)]
        if trace:
            items.insert(1, (first_width + gap, trace_width, trace_text))
        return tuple(items)
    # At narrow widths retain the verified mode and elide only display labels.
    trace_text = trace.mode if trace else ''
    trace_width = min(metrics.horizontalAdvance(trace_text), width // 3)
    gaps = min(gap, width // 4) * (2 if trace else 1)
    side_width = max(0, (width - trace_width - gaps) // 2)
    items = [
        (0, side_width, metrics.elidedText(first_time, Qt.TextElideMode.ElideRight, side_width)),
        (width - side_width, side_width, metrics.elidedText(last_time, Qt.TextElideMode.ElideRight, side_width)),
    ]
    if trace:
        items.insert(1, ((width - trace_width) // 2, trace_width, metrics.elidedText(trace_text, Qt.TextElideMode.ElideRight, trace_width)))
    return tuple(items)
