"""Table mechanics only; row adapters own values, roles, privacy and sorting."""


def fill_table(table, rows, columns, make_item, *, after_row=None):
    """Fill existing dimensions in row order without changing sorting or headers."""
    for row_index, row in enumerate(rows):
        for column_index, key in enumerate(columns):
            table.setItem(row_index, column_index, make_item(row, key))
        if after_row is not None:
            after_row(row_index)


def resize_columns(table, maximum=340):
    """Apply the existing content width cap after caller-specific headers/tooltips."""
    table.resizeColumnsToContents()
    for column in range(table.columnCount()):
        table.setColumnWidth(column, min(table.columnWidth(column), maximum))
