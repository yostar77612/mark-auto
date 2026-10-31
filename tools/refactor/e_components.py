"""Idempotent PR E caller rewrites. Run from any working directory."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def rewrite(path, replacements, imports=()):
    file = ROOT / path
    source = file.read_text(encoding='utf-8')
    for old, new in replacements:
        source = source.replace(old, new)
    missing = [line for line in imports if line not in source.splitlines()]
    if missing:
        tree = ast.parse(source)
        offset = tree.body[0].end_lineno if ast.get_docstring(tree) is not None else 0
        lines = source.splitlines(keepends=True)
        lines[offset:offset] = ['\n', *(line + '\n' for line in missing)]
        source = ''.join(lines)
    if source != file.read_text(encoding='utf-8'):
        file.write_text(source, encoding='utf-8', newline='\n')


def tables():
    rewrite(
        'desktop_app/components/result_tables.py',
        [
            (
                """        for i, row in enumerate(rows):
            for j, key in enumerate(columns):
                text = readable(row.get(key), key)
                item = QTableWidgetItem(text)
                item.setToolTip(str(row.get(key)))
                if key in FINANCIAL_FIELDS:
                    set_financial_item(self, item, row.get(key))
                _privacy.item_display(self, item, key)
                self.setItem(i, j, item)
        self.resizeColumnsToContents()
        for j in range(len(columns)):
            self.setColumnWidth(j, min(self.columnWidth(j), 340))""",
                """        def make_item(row, key):
            text = readable(row.get(key), key)
            item = QTableWidgetItem(text)
            item.setToolTip(str(row.get(key)))
            if key in FINANCIAL_FIELDS:
                set_financial_item(self, item, row.get(key))
            _privacy.item_display(self, item, key)
            return item

        fill_table(self, rows, columns, make_item)
        resize_columns(self)""",
            ),
        ],
        ['from desktop_app.components.tables import fill_table, resize_columns'],
    )
    rewrite(
        'desktop_app/components/forms.py',
        [
            (
                """        for i, row in enumerate(rows):
            for j, (key, _) in enumerate(self.columns):
                self.table.setItem(i, j, QTableWidgetItem(str(row.get(key, ''))))
            open_date_editors(self.table, self.columns, i)""",
                """        fill_table(
            self.table, rows, [key for key, _ in self.columns],
            lambda row, key: QTableWidgetItem(str(row.get(key, ''))),
            after_row=lambda i: open_date_editors(self.table, self.columns, i),
        )""",
            ),
        ],
        ['from desktop_app.components.tables import fill_table'],
    )
    sortable_table()


def sortable_table():
    rewrite(
        'desktop_app/components/result_widgets.py',
        [
            (
                """        for r, row in enumerate(rows):
            for c, key in enumerate(columns):
                value = row.get(key, MISSING)
                item = SortItem(shown(value, (formats or {}).get(key, key)))
                number = numeric(value)
                item.setData(Qt.ItemDataRole.UserRole, (0, number) if number is not None else (1, item.text()))
                item.setToolTip(str(value) if value is not MISSING else ui_text('forms.metric.not_provided'))
                if key in FINANCIAL_FIELDS:
                    set_financial_item(self, item, value)
                _privacy.item_display(self, item, (formats or {}).get(key, key))
                self.setItem(r, c, item)""",
                """        def make_item(row, key):
            value = row.get(key, MISSING)
            item = SortItem(shown(value, (formats or {}).get(key, key)))
            number = numeric(value)
            item.setData(Qt.ItemDataRole.UserRole, (0, number) if number is not None else (1, item.text()))
            item.setToolTip(str(value) if value is not MISSING else ui_text('forms.metric.not_provided'))
            if key in FINANCIAL_FIELDS:
                set_financial_item(self, item, value)
            _privacy.item_display(self, item, (formats or {}).get(key, key))
            return item

        fill_table(self, rows, columns, make_item)""",
            ),
            (
                """        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            self.setColumnWidth(c, min(self.columnWidth(c), 340))""",
                '        resize_columns(self)',
            ),
        ],
        ['from desktop_app.components.tables import fill_table, resize_columns'],
    )
    rewrite(
        'desktop_app/features/backtest/summary.py',
        [
            (
                """        self.resizeColumnsToContents()
        for column in range(self.columnCount()):
            self.setColumnWidth(column, min(self.columnWidth(column), 340))""",
                '        resize_columns(self)',
            ),
        ],
        ['from desktop_app.components.tables import resize_columns'],
    )


def fields():
    rewrite(
        'desktop_app/components/forms.py',
        [
            (
                """        widget.setObjectName(key)
        widget.setAccessibleName(label)
        caption = QLabel(label)
        caption.setBuddy(widget)""",
                """        caption = QLabel(label)
        named_field(widget, key, label, caption=caption)""",
            ),
        ],
        ['from desktop_app.components.fields import named_field'],
    )
    rewrite(
        'desktop_app/features/data/data.py',
        [
            (
                """        field.setAccessibleName(title)
        label.setBuddy(field)""",
                '        named_field(field, None, title, caption=label)',
            ),
        ],
        ['from desktop_app.components.fields import named_field'],
    )
    rewrite(
        'desktop_app/features/market/rows.py',
        [
            (
                """def _named(widget, name, label):
    widget.setObjectName(name)
    widget.setAccessibleName(label)
    return widget


""",
                '',
            ),
        ],
    )
    market_fields()


def market_fields():
    for path in ('history_dialog.py', 'dashboard.py', 'layout.py', 'indicator_controls.py'):
        file = 'desktop_app/features/market/' + path
        rewrite(
            file,
            [
                ('import _label, _named', 'import _label'),
                ('import MarketRows, _named', 'import MarketRows'),
                ('_named(', 'named_field('),
            ],
            ['from desktop_app.components.fields import named_field'],
        )


def numeric_formatting():
    rewrite(
        'desktop_app/components/formatting.py',
        [
            (
                """        if isinstance(value, bool) or len(str(value)) > 128:
            raise ValueError
        number = Decimal(str(value))
        if not number.is_finite() or abs(number) > Decimal('1e100'):""",
                """        number = finite_decimal(value)
        if number is None or abs(number) > Decimal('1e100'):""",
            ),
        ],
    )
    rewrite(
        'desktop_app/features/backtest/summary.py',
        [
            ('from decimal import Decimal, InvalidOperation', 'from decimal import Decimal'),
            (
                'from desktop_app.components.formatting import display_value, display_number\n',
                'from desktop_app.components.formatting import display_value, display_number, finite_decimal\n',
            ),
            (
                """    if len(str(value)) > 128:
        return ui_text('forms.report_number.diagnostics_required')
    try:
        if not Decimal(str(value)).is_finite():
            return ui_text('forms.report_number.diagnostics_required')
    except (InvalidOperation, ValueError):
        return ui_text('forms.report_number.diagnostics_required')""",
                """    if finite_decimal(value) is None:
        return ui_text('forms.report_number.diagnostics_required')""",
            ),
        ],
    )
    numeric_result_rows()


def numeric_result_rows():
    rewrite(
        'desktop_app/components/result_widgets.py',
        [
            ('from decimal import Decimal, InvalidOperation\n', ''),
            ('import display_number, display_value, RATIOS, AMOUNTS\n', 'import display_number, display_value, RATIOS, AMOUNTS, finite_decimal\n'),
            (
                """def numeric(value):
    if isinstance(value, bool) or len(str(value)) > 128:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


""",
                '',
            ),
            ('numeric(', 'finite_decimal('),
        ],
    )


def timestamps():
    for path, variable in (
        ('desktop_app/features/backtest/summary.py', 'timestamp'),
        ('desktop_app/components/result_widgets.py', 'value'),
    ):
        rewrite(
            path,
            [
                (f"datetime.fromisoformat({variable}.replace('Z', '+00:00'))", f'aware_iso_utc({variable})'),
            ],
            ['from quantlab.shared.time import aware_iso_utc'],
        )
    rewrite(
        'quantlab/market_history.py',
        [
            ("datetime.fromisoformat(text.replace('Z', '+00:00'))", 'aware_iso_utc(text)'),
        ],
        ['from quantlab.shared.time import aware_iso_utc'],
    )


def feedback():
    file = ROOT / 'desktop_app/components/error_guidance.py'
    source = file.read_text(encoding='utf-8')
    if 'NEXT_STEP_KEYS =' in source:
        start = source.index('NEXT_STEP_KEYS =')
        end = source.index('def clear_inline', start)
        source = source[:start] + source[end:]
        file.write_text(source, encoding='utf-8', newline='\n')
    rewrite(
        'desktop_app/components/error_guidance.py',
        [
            ('from desktop_app.strings.catalog import ui_text\n', ''),
            (
                """            label.setText(with_next_step(shown, code))
            label.setAccessibleName(label.text())""",
                '            show_feedback(label, shown, code=code, accessible=True)',
            ),
        ],
        ['from desktop_app.components.validation_feedback import show_feedback'],
    )
    rewrite(
        'desktop_app/shell/window.py',
        [
            (
                '        self.status.setText(message)\n        scroll = widget.parentWidget()',
                '        show_feedback(self.status, message)\n        scroll = widget.parentWidget()',
            ),
        ],
        ['from desktop_app.components.validation_feedback import show_feedback'],
    )
    rewrite(
        'desktop_app/features/market/history_dialog.py',
        [
            ('self.error.setText(error_message(exception_code(exc)))', 'show_feedback(self.error, error_message(exception_code(exc)))'),
        ],
        ['from desktop_app.components.validation_feedback import show_feedback'],
    )
    rewrite(
        'desktop_app/components/async_status.py',
        [
            ('from desktop_app.components.error_guidance import with_next_step', 'from desktop_app.components.validation_feedback import with_next_step'),
        ],
    )
    feedback_test_imports()


def feedback_test_imports():
    for path in ('tests/test_accessibility_walk.py', 'tests/test_strict_json_a3.py'):
        rewrite(path, [('from desktop_app.components.error_guidance import', 'from desktop_app.components.validation_feedback import')])
    rewrite(
        'tests/test_error_guidance_u7.py',
        [
            (
                'from desktop_app.components.error_guidance import NEXT_STEP_KEYS, clear_inline, next_step, run_inline, with_next_step',
                'from desktop_app.components.error_guidance import clear_inline, run_inline\n'
                'from desktop_app.components.validation_feedback import NEXT_STEP_KEYS, next_step, with_next_step',
            ),
        ],
    )


def main():
    tables()
    fields()
    numeric_formatting()
    timestamps()
    feedback()


if __name__ == '__main__':
    main()
