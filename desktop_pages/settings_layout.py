"""Settings presentation helpers; existing page handlers own every action."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QCheckBox, QToolButton
from desktop_strings import ui_text
from .log_table import LogTable
from .maintenance import MaintenancePanel


def open_folder(directory):
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))


def collapsed(layout, title):
    toggle = QToolButton() if title == 'settings.advanced' else QCheckBox()
    toggle.setText(ui_text(title))
    toggle.setCheckable(True)
    layout.addWidget(toggle)
    content = QWidget()
    inner = QVBoxLayout(content)
    layout.addWidget(content)
    content.hide()
    toggle.toggled.connect(content.setVisible)
    return toggle, content, inner


def build_settings(page, layout):
    sections = []
    page.settings_sections = []
    for key in ('general', 'connection', 'backup', 'about'):
        group = QGroupBox(ui_text('settings.' + key))
        layout.addWidget(group)
        sections.append(QVBoxLayout(group))
        page.settings_sections.append(group)
    general, connection, backup, about = sections
    page.persist_logs = QCheckBox(ui_text('ui._settings_page.text_8'))
    page.persist_logs.setChecked(True)
    general.addWidget(page.persist_logs)
    page.local_notifications = QCheckBox(ui_text('ui._settings_page.text_9'))
    page.local_notifications.setChecked(True)
    general.addWidget(page.local_notifications)
    page._button(general, ui_text('ui._settings_page.text_10'), 'save_settings', page.save_settings, role='primary')
    page.paths_toggle, page.paths_advanced, advanced = collapsed(general, 'settings.advanced')
    page.paths_toggle.setObjectName('settings_help_advanced')
    page.paths_toggle.setAccessibleName(ui_text('help.accessible'))
    page.paths_toggle.setToolTip(ui_text('help.advanced'))
    page.paths_advanced.setObjectName('settings_help_details')
    for key, path in (('ui._settings_page.text_2', page.paths.root), ('ui._settings_page.text_3', page.root), ('ui._settings_page.text_5', page.paths.logs)):
        advanced.addWidget(QLabel(ui_text(key).format(str(path))))
    page.workspace_path = page._text(advanced, ui_text('ui._settings_page.text_6'), str(page.paths.root))
    page._button(advanced, ui_text('ui._settings_page.text_7'), 'configure_workspace', page.configure_workspace)
    for key, path in (('settings.open_workspace', page.paths.root), ('settings.open_logs', page.paths.logs)):
        page._button(advanced, ui_text(key), '', lambda directory=path: open_folder(directory))
    page.connection_status = QLabel()
    connection.addWidget(page.connection_status)
    page.connection_toggle, _, management = collapsed(connection, 'settings.manage_connection')
    from desktop_chatgpt_ui import ChatGPTConnectionPanel, ConnectionController

    page.chatgpt_controller = ConnectionController(page)
    page.chatgpt_panel = ChatGPTConnectionPanel(page.chatgpt_controller)
    management.addWidget(page.chatgpt_panel)

    # Share the existing panel's status text without adding another controller.
    def update_status():
        page.connection_status.setText(page.chatgpt_controller.message)
        page.state.chatgpt_connection_status.setText(page.chatgpt_controller.message)

    page.chatgpt_controller.changed.connect(update_status)
    update_status()
    backup.addWidget(QLabel(ui_text('ui._settings_page.text_4')))
    page.backup_toggle, page.backup_advanced, controls = collapsed(backup, 'settings.backup_advanced')
    page.backup_path = page._text(controls, ui_text('ui._settings_page.text_11'))
    page._button(controls, ui_text('ui._settings_page.text_12'), 'create_backup', lambda: page.backup(False))
    page.restore_confirm = QCheckBox(ui_text('ui._settings_page.text_13'))
    controls.addWidget(page.restore_confirm)
    page._button(controls, ui_text('ui._settings_page.text_14'), 'restore_backup', lambda: page.backup(True), role='danger')
    from desktop_automatic_backup import AutomaticBackupPanel

    page.automatic_backup_panel = AutomaticBackupPanel(page)
    controls.addWidget(page.automatic_backup_panel)
    page._button(controls, ui_text('settings.open_backup'), '', lambda: open_folder(page.automatic_backup_panel.directory.text() or page.paths.root))
    from quantlab import __version__

    page.version_label = QLabel(ui_text('ui._settings_page.text_15').format(__version__))
    page.version_label.setWordWrap(True)
    about.addWidget(page.version_label)
    about.addWidget(QLabel(ui_text('ui._settings_page.text_16')))
    page._button(about, ui_text('ui._settings_page.text_17'), 'open_releases', page.open_releases)
    page.maintenance_toggle, _, maintenance = collapsed(about, 'maintenance.options')
    page.maintenance_panel = MaintenancePanel(page)
    maintenance.addWidget(page.maintenance_panel)
    page._button(about, ui_text('ui._settings_page.text_18'), 'read_logs', page.read_logs)
    page.log_view = LogTable()
    page.errors_only = QCheckBox(ui_text('logs.errors_only'))
    about.addWidget(page.errors_only)
    page.errors_only.toggled.connect(page.log_view.filter_errors)
    page._button(about, ui_text('logs.export'), '', page.log_view.export)
    about.addWidget(page.log_view)
    layout.addStretch()
