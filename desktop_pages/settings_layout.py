"""Settings presentation helpers; existing page handlers own every action."""

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QLabel, QCheckBox, QToolButton
from desktop_strings import ui_text
from desktop_theme import install_appearance_controls
from .log_table import LogTable
from .maintenance import MaintenancePanel
from .diagnostics import DiagnosticsPanel, snapshot_for_state


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
    page.persist_logs = QCheckBox(ui_text('ui.settings_page.save_logs'))
    page.persist_logs.setChecked(True)
    general.addWidget(page.persist_logs)
    page.local_notifications = QCheckBox(ui_text('ui.settings_page.notify_jobs'))
    page.local_notifications.setChecked(True)
    general.addWidget(page.local_notifications)
    page._button(general, ui_text('ui.settings_page.save_preferences'), 'save_settings', page.save_settings, role='primary')
    page.paths_toggle, page.paths_advanced, advanced = collapsed(general, 'settings.advanced')
    page.paths_toggle.setObjectName('settings_help_advanced')
    page.paths_toggle.setAccessibleName(ui_text('help.accessible'))
    page.paths_toggle.setToolTip(ui_text('help.advanced'))
    page.paths_advanced.setObjectName('settings_help_details')
    for key, path in (
        ('ui.settings_page.workspace_path', page.paths.root),
        ('ui.settings_page.state_path', page.root),
        ('ui.settings_page.log_path', page.paths.logs),
    ):
        advanced.addWidget(QLabel(ui_text(key).format(str(path))))
    install_appearance_controls(page, advanced, page.settings)
    page.workspace_path = page._text(advanced, ui_text('ui.settings_page.next_workspace'), str(page.paths.root))
    page._button(advanced, ui_text('ui.settings_page.configure_workspace'), 'configure_workspace', page.configure_workspace)
    for key, path in (('settings.open_workspace', page.paths.root), ('settings.open_logs', page.paths.logs)):
        page._button(advanced, ui_text(key), '', lambda directory=path: open_folder(directory))
    page.connection_status = QLabel()
    connection.addWidget(page.connection_status)
    page.connection_toggle, _, management = collapsed(connection, 'settings.manage_connection')
    # Load the optional connection UI only when settings are mounted.
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
    backup.addWidget(QLabel(ui_text('ui.settings_page.irreversible_records_hint')))
    page.backup_toggle, page.backup_advanced, controls = collapsed(backup, 'settings.backup_advanced')
    page.backup_path = page._text(controls, ui_text('ui.settings_page.backup_path'))
    page._button(controls, ui_text('ui.settings_page.create_backup'), 'create_backup', lambda: page.backup(False))
    # Inspection reads metadata only and stays inside the collapsed backup area.
    from .backup_inspection import BackupInspectionPanel

    # Load the existing scheduling controls only when settings are mounted.
    from desktop_automatic_backup import AutomaticBackupPanel

    page.automatic_backup_panel = AutomaticBackupPanel(page)
    page.backup_inspection_panel = BackupInspectionPanel(page)
    controls.addWidget(page.backup_inspection_panel)
    page.restore_confirm = QCheckBox(ui_text('ui.settings_page.restore_consent'))
    controls.addWidget(page.restore_confirm)
    page._button(controls, ui_text('ui.settings_page.restore_backup'), 'restore_backup', lambda: page.backup(True), role='danger')
    controls.addWidget(page.automatic_backup_panel)
    page._button(controls, ui_text('settings.open_backup'), '', lambda: open_folder(page.automatic_backup_panel.directory.text() or page.paths.root))
    # Resolve the installed package version when rendering settings.
    from quantlab import __version__

    page.version_label = QLabel(ui_text('ui.settings_page.current_version').format(__version__))
    page.version_label.setWordWrap(True)
    about.addWidget(page.version_label)
    about.addWidget(QLabel(ui_text('ui.settings_page.manual_update_hint')))
    page._button(about, ui_text('ui.settings_page.releases'), 'open_releases', page.open_releases)
    page.maintenance_toggle, _, maintenance = collapsed(about, 'maintenance.options')
    page.maintenance_panel = MaintenancePanel(page)
    maintenance.addWidget(page.maintenance_panel)
    page.diagnostics_panel = DiagnosticsPanel(lambda: snapshot_for_state(page.state), page)
    maintenance.addWidget(page.diagnostics_panel)
    # The assistant belongs to the existing collapsed area; defaults stay intact.
    from .assistant import AssistantPanel

    page.assistant_panel = AssistantPanel(page)
    maintenance.addWidget(page.assistant_panel)
    # Mirror the session intent in the existing collapsed connection controls.
    from .assistant_permissions import install_menu

    page.assistant_permission_menu = install_menu(management, page.assistant_panel.permissions, 'settings_research_permission')
    page._button(about, ui_text('ui.settings_page.read_logs'), 'read_logs', page.read_logs)
    page.log_view = LogTable()
    page.errors_only = QCheckBox(ui_text('logs.errors_only'))
    about.addWidget(page.errors_only)
    page.errors_only.toggled.connect(page.log_view.filter_errors)
    page._button(about, ui_text('logs.export'), '', page.log_view.export)
    about.addWidget(page.log_view)
    layout.addStretch()
