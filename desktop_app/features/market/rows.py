from desktop_app.shell.theme import set_financial_label
from desktop_app.strings.catalog import ui_text
import desktop_app.components.privacy as _privacy
from decimal import Decimal, InvalidOperation
import re
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTableWidgetItem
from quantlab.market import QuoteSnapshot


def _identity(value):
    return isinstance(value, str) and (value == 'TWSE:TAIEX' or bool(re.fullmatch('TAIFEX:(?:TX|MTX|TMF):\\d{4}(?:0[1-9]|1[0-2])(?:W[1-5])?', value)))


def _friendly_contract(key):
    if key == 'TWSE:TAIEX':
        return ui_text('market.friendly_contract.weighted_index')
    parts = key.split(':')
    if len(parts) != 3:
        return key
    product = {
        'TX': ui_text('market.friendly_contract.index_futures'),
        'MTX': ui_text('market.friendly_contract.mini_futures'),
        'TMF': ui_text('market.friendly_contract.micro_futures'),
    }.get(parts[1], parts[1])
    expiry = parts[2]
    month = expiry[:4] + '/' + expiry[4:6]
    if len(expiry) > 6:
        month += ui_text('market.friendly_contract.week_number').format(expiry[-1])
    return product + ' ' + month


def _friendly_source(instrument):
    return ui_text('market.friendly_source.twse') if instrument.exchange == 'TWSE' else ui_text('market.friendly_source.taifex')


def _label(text, name):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _series_source(item):
    return ui_text('market.sample_label') if item.provenance.source_url == 'sample:synthetic-v1' else _friendly_source(item.instrument)


class MarketRows:
    def __init__(self, view):
        self.view = view

    def _render_cards(self):
        sources = self.view._series if self.view._quote_series is None else self.view._quote_series
        stale = self.view._stale if self.view._quote_series is None else self.view._quote_stale
        for symbol, label in self.view.cards.items():
            choices = [x for x in sources.values() if x.instrument.symbol == symbol]
            item = next((x for x in choices if x.instrument.contract_id == self.view._selected), choices[0] if choices else None)
            if not item:
                label.setText(ui_text('market.render_cards.no_data'))
                set_financial_label(label, None)
                label.setToolTip('')
                continue
            quote = QuoteSnapshot.from_series(item, stale=stale)
            change = quote.change
            delta = ui_text('market.render_cards.previous_close_missing') if change is None else f'{change:+f}'
            raw = (
                f'{_friendly_contract(item.instrument.contract_id)}\n{quote.last:,.2f}  {delta}\n{quote.trade_date} · '
                + (ui_text('market.render_cards.stale_cache') if stale else ui_text('market.render_cards.historical_snapshot'))
                + ' · '
                + ui_text('market.not_realtime')
                + (' · ' + ui_text('market.sample_label') if item.provenance.source_url == 'sample:synthetic-v1' else '')
            )
            _privacy.bind_text(
                label,
                lambda label=label, raw=raw: label.setText(
                    '\n'.join((_privacy.display(label, part, 'price') if index == 1 else part for index, part in enumerate(raw.split('\n'))))
                ),
            )
            label.setToolTip(
                ui_text('market.render_cards.source_details').format(
                    item.instrument.contract_id,
                    item.instrument.symbol,
                    item.provenance.attribution,
                    item.provenance.source_url,
                    item.provenance.timestamp_basis,
                    quote.received_at.isoformat(),
                )
            )
            set_financial_label(label, change)

    def set_trading_status(self, *, strategy=None, paper=None, risk=None):
        values = {'strategy': strategy, 'paper': paper, 'risk': risk}
        if any((value is not None and (not isinstance(value, str) or len(value) > 500) for value in values.values())):
            raise ValueError('invalid host status')
        for key, title in [
            ('strategy', ui_text('market.set_trading_status.strategy')),
            ('paper', ui_text('market.set_trading_status.paper')),
            ('risk', ui_text('market.set_trading_status.risk')),
        ]:
            label = self.view.trading_labels[key]
            raw = ui_text('market.set_trading_status.named_value').format(
                title, values[key] if values[key] is not None else ui_text('market.set_trading_status.unknown_status')
            )
            field = 'cash' if key == 'paper' else key
            _privacy.bind_text(label, lambda label=label, raw=raw, field=field: label.setText(_privacy.display(label, raw, field)))

    def set_account_tables(self, *, positions=(), orders=(), fills=()):
        """Validated display-only snapshots. Never produces an order or fills blanks."""
        prepared = []
        for rows, table, columns in [
            (positions, self.view.positions_table, ('contract_id', 'quantity', 'average_price')),
            (orders, self.view.orders_table, ('order_id', 'contract_id', 'side', 'quantity', 'status')),
            (fills, self.view.fills_table, ('fill_id', 'contract_id', 'side', 'quantity', 'price')),
        ]:
            if not isinstance(rows, (list, tuple)) or len(rows) > 10000:
                raise ValueError('bounded table rows required')
            output = []
            for row in rows:
                if not isinstance(row, dict) or not _identity(row.get('contract_id')) or type(row.get('quantity')) is not int:
                    raise ValueError('invalid host account row')
                if table is not self.view.positions_table and (row['quantity'] <= 0 or row.get('side') not in ('buy', 'sell')):
                    raise ValueError('invalid direction/quantity')
                cells = []
                for key in columns:
                    value = row.get(key)
                    if value is None:
                        cells.append('—')
                        continue
                    if key in ('average_price', 'price'):
                        try:
                            number = Decimal(str(value))
                        except InvalidOperation:
                            raise ValueError('invalid price') from None
                        if not number.is_finite() or number < 0:
                            raise ValueError('invalid price')
                    if not isinstance(value, (str, int, float, Decimal)) or isinstance(value, bool) or len(str(value)) > 500:
                        raise ValueError('invalid display value')
                    from desktop_app.components.formatting import display_value

                    cells.append(display_value(value, key))
                output.append(cells)
            prepared.append((table, output))
        for table, rows in prepared:
            table.setRowCount(len(rows))
            for r, cells in enumerate(rows):
                for c, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    keys = (
                        ('contract_id', 'quantity', 'average_price')
                        if table is self.view.positions_table
                        else ('order_id', 'contract_id', 'side', 'quantity', 'status')
                        if table is self.view.orders_table
                        else ('fill_id', 'contract_id', 'side', 'quantity', 'price')
                    )
                    _privacy.item_display(table, item, keys[c])
                    table.setItem(r, c, item)
