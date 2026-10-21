"""Sequential UI over the existing walk-forward operations and typed fields."""

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QStackedWidget, QLabel, QPushButton, QComboBox
from desktop_strings import ui_text
from desktop_presentation import display_number
from .result_widgets import ResultTable
from desktop_theme import theme_colors
from quantlab.wf_estimate import MEASURED_EVALUATION_SECONDS, estimated_seconds
from quantlab.errors import ERROR_TABLE


def failure_hint(error_code=None):
    """Project only B1 catalogue text; never accept exception or result details.

    All catalogue codes are covered, including local/validation failures used
    by walk-forward. Unknown codes use the notification centre's fallback.
    Catalogue-only copy contains no user names, paths or evaluation values.
    """
    code = error_code if type(error_code) is str and error_code in ERROR_TABLE else 'operation_failed'
    entry = ERROR_TABLE[code]
    return ui_text('wf.failure_hint').format(code, entry.explanation, entry.action)


def duration_estimate_text(evaluations, per_evaluation_seconds=MEASURED_EVALUATION_SECONDS):
    """An upper-count estimate, never a deadline or permission to run."""
    if type(evaluations) is not int or evaluations <= 0:
        return ''
    seconds = estimated_seconds(evaluations, per_evaluation_seconds)
    if seconds is None:
        return ui_text('wf.duration_unknown')
    return ui_text('wf.duration_estimate').format(display_number(seconds))


def display_result_rows(result):
    """Readable candidate identity without changing the journal projection."""
    from desktop_walk_forward import result_rows

    rows = result_rows(result)
    winner_key = ui_text('walk_forward.result_rows.winner')
    for fold in result.get('folds', []):
        index = fold.get('winner_pool_index')
        if index is not None:
            old = ui_text('walk_forward.result_rows.candidate_number').format(str(index + 1))
            for row in rows:
                if row.get(winner_key) == old:
                    row[winner_key] = ui_text('wf.candidate').format(display_number(index + 1))
    return rows


def preset_values(count, preset):
    """Quarter train, eighth validation/test; 2/3/4 folds for quick/standard/strict.

    Strict uses one sixteenth per validation/test to retain a final holdout.
    Budgets use the existing five-candidate upper bound: folds * (2*5+1).
    No source, ranking, evidence, or cost setting is changed.
    """
    if type(count) is not int or not 8 <= count <= 100000:
        raise ValueError(ui_text('wf.data_error'))
    folds = {'quick': 2, 'standard': 3, 'strict': 4}[preset]
    train = max(1, count // 4)
    width = max(1, count // (16 if preset == 'strict' else 8))
    return dict(
        start=0,
        train_bars=train,
        validation_bars=width,
        oos_bars=width,
        step_bars=width,
        gap_bars=0,
        fold_count=folds,
        final_holdout_start=train + (folds + 1) * width,
        final_holdout_end=count,
        max_evaluations=folds * 11,
    )


class WizardStack(QStackedWidget):
    def __init__(self, wizard):
        super().__init__()
        self.wizard = wizard
        self.accepted = 0
        self.currentChanged.connect(self._guard)

    def setCurrentIndex(self, index):
        self.wizard.go_to(index)

    def _guard(self, index):
        if index != self.accepted:
            QStackedWidget.setCurrentIndex(self, self.accepted)
            self.wizard.message.setText(ui_text('wf.skip_error'))

    def sizeHint(self):
        widget = self.currentWidget()
        return widget.sizeHint() if widget else super().sizeHint()

    def minimumSizeHint(self):
        widget = self.currentWidget()
        return widget.minimumSizeHint() if widget else super().minimumSizeHint()

    def accept(self, index):
        if index != self.wizard.position or index > self.accepted + 1:
            self.wizard.message.setText(ui_text('wf.skip_error'))
            return False
        self.accepted = index
        QStackedWidget.setCurrentIndex(self, index)
        self.updateGeometry()
        return True


class WindowTimeline(QWidget):
    roles = ('train', 'validation', 'oos', 'holdout')

    def __init__(self):
        super().__init__()
        self.setObjectName('wf_timeline')
        self.setMinimumHeight(110)
        self.lengths = (1, 1, 1, 1)
        self.setProperty('segmentColors', [theme_colors(self)[k] for k in ('primary', 'success', 'warning', 'neutral')])
        self.setAccessibleName(' / '.join(ui_text('wf.' + r) for r in self.roles))

    def segments(self, width):
        total = sum(self.lengths)
        left = 0.0
        result = []
        for role, length in zip(self.roles, self.lengths):
            size = width * length / total
            result.append((role, ui_text('wf.' + role), left, size))
            left += size
        return result

    def paintEvent(self, event):
        painter = QPainter(self)
        colors = [theme_colors(self)[k] for k in ('primary', 'success', 'warning', 'neutral')]
        for index, (role, label, left, width) in enumerate(self.segments(self.width())):
            painter.fillRect(QRectF(left, 12, width, 30), QColor(colors[index]))
            painter.setPen(QColor(theme_colors(self)['text']))
            # Separate legend remains legible even when a segment is narrow.
            painter.drawText(
                QRectF(index * self.width() / 4, 50, self.width() / 4, 50), Qt.AlignmentFlag.AlignCenter, label + '\n' + display_number(self.lengths[index])
            )
        painter.end()


class WalkForwardWizard(QWidget):
    def __init__(self, page, content):
        super().__init__()
        controls = {name: page.findChild(QPushButton, name) for name in ("pick_walk_forward_original", "preview_walk_forward", "read_walk_forward")}
        self.page = page
        self.position = 0
        self.setObjectName('wf_wizard')
        outer = QVBoxLayout(self)
        self.header = QLabel()
        self.header.setObjectName('wf_step_header')
        outer.addWidget(self.header)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setObjectName('wf_step_message')
        self.message.setAccessibleName(ui_text('wf.failure_hint_name'))
        self.stack = WizardStack(self)
        self.stack.setObjectName('wf_steps')
        outer.addWidget(self.stack)
        self.layouts = []
        for index in range(5):
            widget = QWidget()
            widget.setObjectName('wf_step_' + str(index))
            layout = QVBoxLayout(widget)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            self.stack.addWidget(widget)
            self.layouts.append(layout)
        self._move_field('pool_origin', 0)
        self.layouts[0].addWidget(page.walk_forward_saved_controls)
        saved = page.walk_forward_saved_controls.layout()
        row = saved.takeRow(page.walk_forward_original)
        data_form = QFormLayout()
        data_form.addRow(row.labelItem.widget(), row.fieldItem.widget())
        self.layouts[1].addWidget(QLabel(ui_text('wf.data')))
        self._move_field('evidence_mode', 1)
        self.layouts[1].addLayout(data_form)
        self.layouts[1].addWidget(controls['pick_walk_forward_original'])
        self.preset = QComboBox()
        self.preset.setObjectName('wf_preset')
        for name in ('quick', 'standard', 'strict', 'custom'):
            self.preset.addItem(ui_text('wf.' + name), name)
        self.preset.setCurrentIndex(1)
        preset_form = QFormLayout()
        preset_form.addRow(ui_text('wf.preset'), self.preset)
        self.layouts[2].addLayout(preset_form)
        self.layouts[2].addWidget(QLabel(ui_text('wf.preset_note')))
        self.layouts[2].addWidget(page.walk_forward_form)
        self.preset.currentIndexChanged.connect(self.apply_preset)
        self._custom_visibility()
        self.timeline = WindowTimeline()
        self.layouts[3].addWidget(self.timeline)
        self.timeline.hide()
        self.summary = ResultTable()
        self.summary.setObjectName('wf_preview_table')
        self.layouts[3].addWidget(self.summary)
        self.layouts[3].addWidget(controls['preview_walk_forward'])
        self.preview_summary = QLabel()
        self.preview_summary.setWordWrap(True)
        self.preview_summary.setObjectName('wf_preview_summary')
        self.layouts[3].addWidget(self.preview_summary)
        # Preserve the original text projection for existing evidence consumers;
        # the default preview uses the table and graphic above.
        page.walk_forward_preview.setMinimumHeight(100)
        page.walk_forward_advanced_group.layout().addWidget(page.walk_forward_preview)
        page.walk_forward_preview.hide()
        page.walk_forward_advanced_group.toggled.connect(page.walk_forward_preview.setVisible)
        self.layouts[3].addWidget(page.walk_forward_advanced_group)
        for widget in (page.walk_forward_consent, page.walk_forward_start):
            self.layouts[4].addWidget(widget)
        buttons = QHBoxLayout()
        self.back = QPushButton(ui_text('wf.back'))
        self.back.setObjectName('wf_back')
        self.next = QPushButton(ui_text('wf.next'))
        self.next.setObjectName('wf_next')
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        outer.addWidget(self.message)
        outer.addLayout(buttons)
        # Saved evidence remains readable without completing a new preview.
        for widget in (page.walk_forward_choice, controls['read_walk_forward'], page.walk_forward_status, page.result_panel):
            outer.addWidget(widget)
        # Candidate-level evidence remains available in the collapsed advanced group.
        page.walk_forward_advanced_group.layout().addWidget(page.walk_forward_results)
        page.walk_forward_results.hide()
        page.walk_forward_advanced_group.toggled.connect(page.walk_forward_results.setVisible)
        self.back.clicked.connect(lambda: self.go_to(self.position - 1))
        self.next.clicked.connect(lambda: self.go_to(self.position + 1))
        page.walk_forward_consent.toggled.connect(self.sync_consent)
        content.addWidget(self)
        self.update_header()

    def _move_field(self, key, step):
        form = self.page.walk_forward_form
        row = form.form.takeRow(form.fields[key])
        target = QFormLayout()
        target.addRow(row.labelItem.widget(), row.fieldItem.widget())
        self.layouts[step].addLayout(target)

    def _custom_visibility(self):
        custom = self.preset.currentData() == 'custom'
        self.page.walk_forward_form.setVisible(custom)
        # Source/evidence fields have moved; disabling the form cannot disable them.
        self.page.walk_forward_form.setEnabled(custom)

    def bar_count(self):
        data = self.page.host.dataset(self.page.state.root, {})
        return len(data.bars)

    def apply_preset(self, *args):
        self._custom_visibility()
        if self.preset.currentData() != 'custom':
            try:
                self.page.walk_forward_form.load(preset_values(self.bar_count(), self.preset.currentData()))
            except (ValueError, OSError, KeyError) as exc:
                self.message.setText(ui_text('wf.data_error'))

    def validate_step(self, step):
        page = self.page
        if step == 0:
            origin = page.walk_forward_form.fields['pool_origin'].currentData()
            if origin not in ('exact_builtin_pool', 'saved_campaign_pool') or (
                origin == 'saved_campaign_pool' and not page.walk_forward_campaign.currentData()
            ):
                return ui_text('wf.pool_error')
        elif step == 1:
            try:
                self.bar_count()
                page._walk_forward_saved_source()
            except (ValueError, OSError, KeyError):
                return ui_text('wf.data_error')
        elif step == 2:
            try:
                _, plan = page._walk_forward_input_key()
                count = self.bar_count()
                from quantlab.walk_forward import _validate_source
                from quantlab.desktop_runtime import validate_walk_forward_request

                chronology = validate_walk_forward_request(plan, page._walk_forward_saved_source())
                _validate_source(page.host.dataset(page.state.root, {}), chronology)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                return ui_text('wf.windows_error').format(str(exc))
        elif step == 3 and page.state._wf_preview is None:
            return ui_text('wf.preview_error')
        return ''

    def go_to(self, index):
        if not 0 <= index <= 4 or index > self.position + 1:
            self.message.setText(ui_text('wf.skip_error'))
            return False
        if index > self.position:
            for step in range(self.position + 1):
                error = self.validate_step(step)
                if error:
                    self.message.setText(error)
                    return False
        if index == 2 and self.position == 1:
            self.apply_preset()
        self.position = index
        self.stack.accept(index)
        if index in (3, 4):
            # Reuse the preview projection above consent on the final step.
            self.layouts[index].insertWidget(0 if index == 4 else 3, self.preview_summary)
        self.message.clear()
        self.update_header()
        self.sync_consent()
        if index == 3:
            self.page.host.safe(self.page.preview_walk_forward)
        return True

    def update_header(self):
        self.header.setText(ui_text('wf.header').format(display_number(self.position + 1), ui_text('wf.step.' + str(self.position))))
        self.back.setEnabled(self.position > 0)
        self.next.setVisible(self.position < 4)

    def sync_consent(self, *args):
        self.page.walk_forward_start.setEnabled(
            self.page.state._wf_preview is not None and self.page.walk_forward_consent.isChecked() and not self.page.state.jobs.active
        )

    def show_preview(self, result):
        self.timeline.show()
        rows = []
        for fold in result['folds']:
            for role in ('train', 'validation', 'oos'):
                bounds = fold[role]
                rows.append(
                    {
                        ui_text('wf.fold'): display_number(fold['index'] + 1),
                        ui_text('wf.role'): ui_text('wf.' + role),
                        ui_text('wf.start'): display_number(bounds['start']),
                        ui_text('wf.end'): display_number(bounds['end']),
                        ui_text('wf.length'): display_number(bounds['end'] - bounds['start']),
                    }
                )
        holdout = result['final_holdout']
        rows.append(
            {
                ui_text('wf.role'): ui_text('wf.holdout'),
                ui_text('wf.start'): display_number(holdout['start']),
                ui_text('wf.end'): display_number(holdout['end']),
                ui_text('wf.length'): display_number(holdout['end'] - holdout['start']),
            }
        )
        self.summary.set_rows(rows)
        first = result['folds'][0]
        self.timeline.lengths = tuple(first[r]['end'] - first[r]['start'] for r in ('train', 'validation', 'oos')) + (holdout['end'] - holdout['start'],)
        self.timeline.update()
        self.preview_summary.setText(
            '\n'.join(
                (
                    ui_text('wf.summary').format(
                        display_number(len(result['folds'])),
                        display_number(result['candidate_count']),
                        display_number(result['planned_evaluations_upper_bound']),
                    ),
                    duration_estimate_text(result['planned_evaluations_upper_bound']),
                    ui_text('walk_forward.preview_text.irreversible_consumption'),
                    ui_text('walk_forward.preview_text.holdout_excluded'),
                    ui_text('walk_forward.preview_text.exposure_warning'),
                    ui_text('walk_forward.preview_text.winner_selection'),
                    ui_text('walk_forward.preview_text.split_warmup'),
                )
            )
        )
        self.sync_consent()
