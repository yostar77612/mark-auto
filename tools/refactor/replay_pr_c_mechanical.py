"""Final exact selector, binding-order and reviewed line-location corrections.

These rules contain only mechanical consumer changes left after the historical
AST passes. No split module body, historical fixture, or PR patch is embedded.
"""

from pathlib import Path
import json
import hashlib
import re

RULES = {
    'desktop_app/shell/host.py': [
        [
            '    window_geometry: Callable\n    # QWidget x()/y() are frame coordinates; geometry().x()/y() are client coordinates.\n    window_position: Callable\n',
            '    window_geometry: Callable\n    window_position: Callable\n',
        ],
        ['    window_minimum_size: Callable\n\n', '    window_minimum_size: Callable\n    idea_records: Callable\n\n'],
    ],
    'desktop_app/smoke/__init__.py': [
        [
            "        raise ValueError('Walk-forward synthetic source changed')\n    expected = preview_walk_forward(data, payload['plan'], paths)\n    reference = expected['preview_identity']\n",
            "        raise ValueError('Walk-forward synthetic source changed')\n    from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports\n\n    expected = preview_walk_forward(data, payload['plan'], paths, inputs=_c_create_operation_ports().inputs)\n    reference = expected['preview_identity']\n",
        ]
    ],
    'quantlab/desktop_runtime.py': [
        [
            'from .job_stages import normalize_stage, stage_from_traceback\nfrom .runtime_support import WindowsAppMutex as WindowsAppMutex, WINDOWS_APP_MUTEX as WINDOWS_APP_MUTEX, atomic_write, _sync_directory, _durable_replace, validate_analysis_request\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n',
            'from .job_stages import normalize_stage, stage_from_traceback\nfrom .runtime_support import (\n    WindowsAppMutex as WindowsAppMutex,\n    WINDOWS_APP_MUTEX as WINDOWS_APP_MUTEX,\n    atomic_write,\n    _sync_directory,\n    _durable_replace,\n    validate_analysis_request,\n)\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n',
        ]
    ],
    'tests/fixtures/layered_paths/page_service_line_relocations.json': [
        ['      },\n      "current_line": 234\n    },\n', '      },\n      "current_line": 235\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 252\n    },\n', '      },\n      "current_line": 253\n    },\n'],
        ['      },\n      "current_line": 268\n    },\n', '      },\n      "current_line": 269\n    },\n'],
        ['      },\n      "current_line": 273\n    },\n', '      },\n      "current_line": 274\n    },\n'],
        [
            '      "original": {\n        "file": "tests/test_notifications_c8.py",\n',
            '      "original": {\n        "file": "tests/test_desktop_walk_forward.py",\n        "line": 340,\n        "name": "start_job",\n        "kind": "patch.object",\n        "receiver": "w"\n      },\n      "current_line": 341\n    },\n    {\n      "original": {\n        "file": "tests/test_desktop_walk_forward.py",\n        "line": 358,\n        "name": "start_job",\n        "kind": "patch.object",\n        "receiver": "w"\n      },\n      "current_line": 359\n    },\n    {\n      "original": {\n        "file": "tests/test_notifications_c8.py",\n',
        ],
        ['      },\n      "current_line": 70\n    },\n', '      },\n      "current_line": 72\n    },\n'],
        ['      },\n      "current_line": 70\n    },\n', '      },\n      "current_line": 72\n    },\n'],
        [
            '      "current_line": 334\n    }\n',
            '      "current_line": 334\n    },\n    {\n      "original": {\n        "file": "tests/test_t9_timeinput.py",\n        "line": 181,\n        "name": "end_date",\n        "kind": "setattr",\n        "receiver": "old"\n      },\n      "current_line": 184\n    },\n    {\n      "original": {\n        "file": "tests/test_t9_timeinput.py",\n        "line": 220,\n        "name": "end_date",\n        "kind": "setattr",\n        "receiver": "old"\n      },\n      "current_line": 223\n    }\n',
        ],
    ],
    'tests/layered_source_fixtures.py': [
        [
            '        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n        from quantlab.reporting import demo_config\n        from quantlab.research import demo_campaign_config\n',
            '        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n        from quantlab.research import demo_campaign_config\n',
        ],
        [
            '    def test_runtime_rejects_unbounded_auth_before_spawn(self):\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_runtime_rejects_unbounded_auth_before_spawn(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError\n\n',
        ],
        [
            '    def test_reconciliation_requires_same_manager_subtree_proof(self):\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n        from desktop_app.shell.main_window import execute_ui_operation\n',
            '    def test_reconciliation_requires_same_manager_subtree_proof(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError\n        from desktop_app.shell.main_window import execute_ui_operation\n',
        ],
        [
            '        from unittest.mock import Mock\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import RuntimeSafetyError\n\n',
        ],
        [
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import _WindowsProcessTree\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import _WindowsProcessTree, RuntimeSafetyError\n\n',
        ],
    ],
    'tests/test_desktop_history_smoke.py': [
        [
            '        from desktop import _history_smoke_fixture\n        from quantlab.market_history import COLUMNS, PRODUCT_SOURCES, session_from_dict\n        import csv\n',
            '        from desktop import _history_smoke_fixture\n        from quantlab.market_history import COLUMNS\n        from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES, session_from_dict\n        import csv\n',
        ]
    ],
    'tests/test_desktop_saved_candidate_pool.py': [
        [
            'from quantlab.core import ValidationError, to_dict\nfrom quantlab.desktop_runtime import AppPaths, JobManager, validate_walk_forward_request\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\nfrom quantlab.reporting import demo_config, save_dataset\n',
            'from quantlab.core import ValidationError, to_dict\nfrom quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError, validate_walk_forward_request\nfrom quantlab.reporting import demo_config, save_dataset\n',
        ]
    ],
    'tests/test_desktop_smoke_isolation.py': [
        [
            '    def test_read_only_redirect_rejects_invalid_paths(self):\n        from quantlab.desktop_runtime import WorkspaceLocator\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_read_only_redirect_rejects_invalid_paths(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError, WorkspaceLocator\n\n',
        ],
        [
            '    def test_read_only_redirect_rejects_symlink_when_supported(self):\n        from quantlab.desktop_runtime import WorkspaceLocator\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_read_only_redirect_rejects_symlink_when_supported(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError, WorkspaceLocator\n\n',
        ],
    ],
    'tests/test_desktop_ui.py': [
        [
            '    def test_historical_provider_budget_survives_older_backup_and_workspace_change(self):\n        from quantlab.research_core.adapters.ui_repository.WorkerRepository import research_controls\n        from quantlab.research import CompatibleProvider\n',
            '    def test_historical_provider_budget_survives_older_backup_and_workspace_change(self):\n        research_controls = _c_create_operation_ports().inputs.research_controls\n        from quantlab.research import CompatibleProvider\n',
        ]
    ],
    'tests/test_desktop_ui_p0_correctness.py': [
        [
            'from quantlab.desktop_errors import ERROR_TABLE, error_message, exception_code, startup_error_code\nfrom quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore, RedactedEventLog\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            'from quantlab.desktop_errors import ERROR_TABLE, error_message, exception_code, startup_error_code\nfrom quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore, RuntimeSafetyError, RedactedEventLog\n\n',
        ]
    ],
    'tests/test_desktop_worker_import.py': [
        [
            'assert window.__class__ is desktop_app.shell.window.MainWindow\nassert PySide6.QtWidgets.QMainWindow is QMainWindow\nmanager.close()\n',
            'assert window.__class__ is desktop_app.shell.window.MainWindow\nassert desktop_app.shell.main_window.QMainWindow is QMainWindow\nmanager.close()\n',
        ]
    ],
    'tests/test_idea_research.py': [
        [
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports\n\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n\n',
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports\n\n',
        ],
        [
            'from quantlab.core import ValidationError, content_hash, to_dict\nfrom quantlab.desktop_runtime import AppPaths, JobManager\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\nfrom quantlab.idea_research import IdeaResearch, IdeaStore, adoption_candidate, new_task, verify_candidates\n',
            'from quantlab.core import ValidationError, content_hash, to_dict\nfrom quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError\nfrom quantlab.idea_research import IdeaResearch, IdeaStore, adoption_candidate, new_task, verify_candidates\n',
        ],
        [
            "        with self.assertRaises(ValidationError):\n            _c_JobPresenter(shell).start_job('ui_idea_research', {})\n        shell.jobs.start.assert_not_called()\n",
            "        with self.assertRaises(ValidationError):\n            # Load the concrete owner only when this test path is exercised.\n            from desktop_app.shell.job_presenter import JobPresenter\n\n            JobPresenter(shell).start_job('ui_idea_research', {})\n        shell.jobs.start.assert_not_called()\n",
        ],
    ],
    'tests/test_idea_research_ui.py': [
        [
            'from desktop_app.features.strategy.idea_labels import COLUMNS as _c_page_COLUMNS\nfrom PySide6.QtGui import QDesktopServices as _c_page_QDesktopServices\nfrom desktop_app.features.strategy.idea_events import event as _c_page_event\n',
            'from desktop_app.features.strategy.idea_labels import COLUMNS as _c_page_COLUMNS\nfrom desktop_app.features.strategy.idea_events import event as _c_page_event\n',
        ],
        [
            'from desktop_app.features.strategy.idea_links import open_url as _c_page_open_url\nfrom PySide6.QtCore import QUrl as _c_page_QUrl\nfrom desktop_app.shell.host import PageState\n',
            'from desktop_app.features.strategy.idea_links import open_url as _c_page_open_url\nfrom desktop_app.features.strategy import idea_links as _c_idea_links\nfrom desktop_app.shell.host import PageState\n',
        ],
        [
            "        self.assertEqual(self.dialog.sources.item(1, _c_page_COLUMNS.index('origin')).text(), ui_text('idea.origin.search_only'))\n        with patch.object(_c_page_QDesktopServices, 'openUrl', return_value=True) as opened:\n            for row in range(2):\n",
            "        self.assertEqual(self.dialog.sources.item(1, _c_page_COLUMNS.index('origin')).text(), ui_text('idea.origin.search_only'))\n        with patch.object(_c_idea_links.QDesktopServices, 'openUrl', return_value=True) as opened:\n            for row in range(2):\n",
        ],
        [
            '            self.dialog.sources.cellDoubleClicked.emit(0, column)\n        self.assertEqual([call.args[0].toString() for call in opened.call_args_list], [urls[0], _c_page_QUrl(urls[1]).toString(), urls[0]])\n        # A cited URL the app refused to fetch is still listed and clickable.\n',
            '            self.dialog.sources.cellDoubleClicked.emit(0, column)\n        self.assertEqual([call.args[0].toString() for call in opened.call_args_list], [urls[0], _c_idea_links.QUrl(urls[1]).toString(), urls[0]])\n        # A cited URL the app refused to fetch is still listed and clickable.\n',
        ],
        [
            "        self.assertEqual(self.dialog.sources.item(2, _c_page_COLUMNS.index('reason')).text(), 'policy_blocked')\n        with patch.object(_c_page_QDesktopServices, 'openUrl', return_value=True) as opened:\n            self.dialog.sources.cellWidget(2, _c_page_COLUMNS.index('open')).click()\n",
            "        self.assertEqual(self.dialog.sources.item(2, _c_page_COLUMNS.index('reason')).text(), 'policy_blocked')\n        with patch.object(_c_idea_links.QDesktopServices, 'openUrl', return_value=True) as opened:\n            self.dialog.sources.cellWidget(2, _c_page_COLUMNS.index('open')).click()\n",
        ],
        [
            "        self.assertEqual(opened.call_args.args[0].toString(), refused)\n        with patch.object(_c_page_QDesktopServices, 'openUrl') as opened:\n            self.assertFalse(_c_page_open_url('http://alpha.example.org/'))\n",
            "        self.assertEqual(opened.call_args.args[0].toString(), refused)\n        with patch.object(_c_idea_links.QDesktopServices, 'openUrl') as opened:\n            self.assertFalse(_c_page_open_url('http://alpha.example.org/'))\n",
        ],
    ],
    'tests/test_import_graph.py': [
        [
            "                        'quantlab/research_core/adapters/market_layout.py',\n                    )\n",
            "                        'quantlab/research_core/adapters/market_layout.py',\n                        'quantlab/shared/runtime_errors.py',\n                    )\n",
        ],
        [
            "        graph = import_graph(self.sources)\n        self.assertEqual(graph['quantlab.runtime_support'], {'quantlab.windows_paths'})\n        self.assertNotIn('quantlab.desktop_runtime', graph['quantlab.analysis_recovery_windows'])\n",
            "        graph = import_graph(self.sources)\n        self.assertEqual(graph['quantlab.runtime_support'], {'quantlab.windows_paths', 'quantlab.shared.runtime_errors'})\n        self.assertNotIn('quantlab.desktop_runtime', graph['quantlab.analysis_recovery_windows'])\n",
        ],
        [
            "        self.assertEqual(\n            graph['desktop_app.features.settings.preferences'], {'quantlab.ui_preferences', 'quantlab.runtime_support', 'desktop_app.strings.catalog'}\n        )\n",
            "        self.assertEqual(\n            graph['desktop_app.features.settings.preferences'], {'quantlab.ui_preferences', 'quantlab.shared.runtime_errors', 'desktop_app.strings.catalog'}\n        )\n",
        ],
    ],
    'tests/test_market_history.py': [
        [
            'from quantlab.market import InstrumentRef, MarketValidationError\nfrom quantlab.market_history import MarketSession, PRODUCT_SOURCES, import_history, load_history, list_history, session_from_dict\n\n',
            'from quantlab.market import InstrumentRef, MarketValidationError\nfrom quantlab.market_history import MarketSession, PRODUCT_SOURCES, session_from_dict\nfrom quantlab.market_history import import_history, load_history, list_history\n\n',
        ]
    ],
    'tests/test_market_history_ui.py': [
        [
            '    def test_contract_day_utc_product_source_and_weekly(self):\n        from quantlab.market_history import PRODUCT_SOURCES\n\n',
            '    def test_contract_day_utc_product_source_and_weekly(self):\n        from quantlab.research_core.domain.market_sessions import PRODUCT_SOURCES\n\n',
        ]
    ],
    'tests/test_notifications_c8.py': [
        [
            '\nfrom desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n',
            '\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n\nfrom desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n',
        ],
        [
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n\n',
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n\n',
        ],
    ],
    'tests/test_page_services_r1.py': [
        [
            '\nfrom desktop_app.shell.window import MainWindow as _c_ui_MainWindow\nfrom quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS as _c_ui_UI_OPERATIONS\n',
            '\nfrom desktop_app.strings.catalog import ui_text as _c_ui_ui_text\nfrom quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS as _c_ui_UI_OPERATIONS\n',
        ],
        [
            'from quantlab.research_core.application.ui_operations.registry import _UI_OPERATION_HANDLERS as _c_ui__UI_OPERATION_HANDLERS\nfrom desktop_app.strings.catalog import ui_text as _c_ui_ui_text\nfrom desktop_app.shell.bindings import HostMethod, PageContext, StateField\n',
            'from quantlab.research_core.application.ui_operations.registry import _UI_OPERATION_HANDLERS as _c_ui__UI_OPERATION_HANDLERS\nfrom desktop_app.shell.window import MainWindow as _c_ui_MainWindow\nfrom desktop_app.shell.bindings import HostMethod, PageContext, StateField\n',
        ],
    ],
    'tests/test_preferences_u8.py': [
        [
            '        from desktop_app.features.settings.settings import SettingsPage\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '        from desktop_app.features.settings.settings import SettingsPage\n        from quantlab.runtime_support import RuntimeSafetyError\n\n',
        ]
    ],
    'tests/test_product_ai_boundary.py': [
        [
            '    def test_removed_job_and_provider_requests_fail_before_spawn(self):\n        from quantlab.desktop_runtime import AppPaths, JobManager\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_removed_job_and_provider_requests_fail_before_spawn(self):\n        from quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError\n\n',
        ]
    ],
    'tests/test_r7_characterization.py': [
        [
            "                'MarketRows',\n                'QAbstractItemView',\n",
            "                'MarketRows',\n                'MarketSeries',\n                'MarketValidationError',\n                'QAbstractItemView',\n",
        ],
        [
            "                'deepcopy',\n                'ui_text',\n",
            "                'deepcopy',\n                'sample_market_series',\n                'ui_text',\n",
        ],
    ],
    'tests/test_r7_function_lengths.py': [
        [
            "        stages.update(\n            dict.fromkeys(('desktop_app/components/chart_geometry.py', 'desktop_app/components/chart_paint.py', 'desktop_app/components/chart_paint_footer.py'))\n        )\n",
            "        stages.update(\n            dict.fromkeys(\n                (\n                    'desktop_app/features/market/layout.py',\n                    'desktop_app/features/market/indicator_controls.py',\n                    'desktop_app/components/chart_geometry.py',\n                    'desktop_app/components/chart_paint.py',\n                    'desktop_app/components/chart_paint_footer.py',\n                )\n            )\n        )\n",
        ]
    ],
    'tests/test_restart_availability_contract.py': [
        [
            '\nfrom quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, SettingsStore, WorkspaceLocator\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '\nfrom quantlab.desktop_runtime import AppPaths, BackupManager, JobManager, RuntimeSafetyError, SettingsStore, WorkspaceLocator\n\n',
        ]
    ],
    'tests/test_t16_presentation.py': [
        [
            '\nfrom desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n',
            '\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n\nfrom desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n',
        ],
        [
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n\nfrom desktop_app.shell.job_presenter import JobPresenter as _c_JobPresenter\n\n',
            'from desktop_app.bootstrap import create_operation_ports as _c_create_operation_ports, create_ui_services as _c_create_ui_services\n\n',
        ],
    ],
    'tests/test_ui_operations_registry.py': [
        [
            'import desktop_app.shell.main_window as ui\nfrom quantlab.reporting import read_json as _c_ui_read_json\n',
            'import desktop_app.shell.main_window as ui\nfrom quantlab.research_core.application.ui_operations.registry import _UI_OPERATION_HANDLERS as _c_ui__UI_OPERATION_HANDLERS\nfrom quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS as _c_ui_UI_OPERATIONS\nfrom quantlab.reporting import read_json as _c_ui_read_json\n',
        ],
        [
            'from quantlab.reporting import read_json as _c_ui_read_json\nfrom quantlab.research_core.application.ui_operations.registry import UI_OPERATIONS as _c_ui_UI_OPERATIONS\nfrom desktop_app.strings.catalog import ui_text as _c_ui_ui_text\nfrom quantlab.research_core.application.ui_operations.assistant import plan_provider as _c_ui_plan_provider\n',
            'from quantlab.reporting import read_json as _c_ui_read_json\nfrom quantlab.research_core.application.ui_operations.assistant import plan_provider as _c_ui_plan_provider\n',
        ],
        [
            'from quantlab.research_core.application.ui_operations.assistant import plan_provider as _c_ui_plan_provider\nfrom quantlab.research_core.application.ui_operations.registry import _UI_OPERATION_HANDLERS as _c_ui__UI_OPERATION_HANDLERS\nfrom quantlab.core import ValidationError, content_hash, to_dict\n',
            'from quantlab.research_core.application.ui_operations.assistant import plan_provider as _c_ui_plan_provider\nfrom quantlab.core import ValidationError, content_hash, to_dict\n',
        ],
        [
            "    def test_unknown_operations_fail_before_dispatch_or_workspace_access(self):\n        expected = _c_ui_ui_text('ui.execute_ui_operation.unknown_operation')\n        with patch.dict(_c_ui__UI_OPERATION_HANDLERS, {'': unittest.mock.Mock(), 'ui_unknown': unittest.mock.Mock()}):\n",
            "    def test_unknown_operations_fail_before_dispatch_or_workspace_access(self):\n        from desktop_app.strings.catalog import ui_text\n\n        expected = ui_text('ui.execute_ui_operation.unknown_operation')\n        with patch.dict(_c_ui__UI_OPERATION_HANDLERS, {'': unittest.mock.Mock(), 'ui_unknown': unittest.mock.Mock()}):\n",
        ],
    ],
    'tests/test_workspace_wal_guard.py': [
        [
            '\nfrom quantlab.desktop_runtime import AppPaths, BackupManager, WorkspaceLocator, WORKSPACE_FORMAT, REPLAY_REQUIREMENT, _write_workspace_format\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '\nfrom quantlab.desktop_runtime import (\n    AppPaths,\n    BackupManager,\n    RuntimeSafetyError,\n    WorkspaceLocator,\n    WORKSPACE_FORMAT,\n    REPLAY_REQUIREMENT,\n    _write_workspace_format,\n)\n\n',
        ]
    ],
    'tools/ui_readability_audit.py': [
        [
            "                jobs = JobManager(paths)\n                window = create_window(paths, jobs, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, jobs))\n                try:\n",
            "                jobs = JobManager(paths)\n                window = create_window(\n                    paths,\n                    jobs,\n                    SettingsStore(paths.state / 'settings.json'),\n                    BackupManager(paths, jobs),\n                )\n                try:\n",
        ]
    ],
    'tools/ui_snapshot.py': [
        [
            "                _header.CLOCK_OVERRIDE = lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)\n                window = create_window(paths, jobs, SettingsStore(paths.state / 'settings.json'), BackupManager(paths, jobs))\n                # Stop polling before dispatching Qt events: snapshots never run jobs.\n",
            "                _header.CLOCK_OVERRIDE = lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)\n                window = create_window(\n                    paths,\n                    jobs,\n                    SettingsStore(paths.state / 'settings.json'),\n                    BackupManager(paths, jobs),\n                )\n                # Stop polling before dispatching Qt events: snapshots never run jobs.\n",
        ]
    ],
    'tools/validate_market_history_import.py': [
        [
            'from quantlab.market import InstrumentRef\nfrom quantlab.market_history import MarketSession, PRODUCT_SOURCES, import_history\nfrom quantlab.chart_data import aggregate_bars, TIMEFRAMES\n',
            'from quantlab.market import InstrumentRef\nfrom quantlab.market_history import MarketSession, PRODUCT_SOURCES\nfrom quantlab.market_history import import_history\nfrom quantlab.chart_data import aggregate_bars, TIMEFRAMES\n',
        ]
    ],
}


RULES['desktop_app/features/market/market.py'] = [
    ('series = self.host.sample_market_series()', 'series = sample_market_series()'),
]


# Retain compatibility imports explicitly exercised by these runtime tests.
EXTRA_RULES = {
    'tests/test_capital_scenario_b5.py': [
        [
            '\n        # Load the concrete owner only when this test path is exercised.\n        from PySide6.QtWidgets import QMessageBox as QMessageBox\n        # Load the concrete owner only when this test path is exercised.\n\n        with workspace() as paths:\n',
            '\n        with workspace() as paths:\n',
        ]
    ],
    'tests/test_chatgpt_reconciliation_ui.py': [
        [
            'from quantlab.research_core.application.ui_operations.assistant import connection_event_from_payload\nfrom quantlab.desktop_runtime import JobManager\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            'from quantlab.research_core.application.ui_operations.assistant import connection_event_from_payload\nfrom quantlab.desktop_runtime import JobManager, RuntimeSafetyError\n\n',
        ]
    ],
    'tests/test_desktop_analysis.py': [
        [
            'from quantlab.reporting import save_dataset, synthetic_dataset\nfrom quantlab.desktop_runtime import AppPaths, JobManager\nfrom quantlab.shared.runtime_errors import RuntimeSafetyError\nfrom tests import test_desktop_ui as ui_support\n',
            'from quantlab.reporting import save_dataset, synthetic_dataset\nfrom quantlab.desktop_runtime import AppPaths, JobManager, RuntimeSafetyError\nfrom tests import test_desktop_ui as ui_support\n',
        ]
    ],
    'tests/test_desktop_automatic_backup.py': [
        [
            '    def test_ui_can_disable_with_unchanged_unavailable_folder(self):\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_ui_can_disable_with_unchanged_unavailable_folder(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError\n\n',
        ]
    ],
    'tests/test_desktop_chatgpt_integration.py': [
        [
            '        _dataset = _c_create_operation_ports().inputs._dataset\n        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n',
            '        _dataset = _c_create_operation_ports().inputs._dataset\n        from quantlab.reporting import demo_config\n        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n',
        ],
        [
            '        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n        from quantlab.reporting import demo_config\n        from quantlab.research import demo_campaign_config\n',
            '        from quantlab.research_core.application.ui_operations.assistant import plan_provider\n        from quantlab.research import demo_campaign_config\n',
        ],
        [
            '    def test_runtime_rejects_unbounded_auth_before_spawn(self):\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '    def test_runtime_rejects_unbounded_auth_before_spawn(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError\n\n',
        ],
        [
            '    def test_reconciliation_requires_same_manager_subtree_proof(self):\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n        from desktop_app.shell.main_window import execute_ui_operation\n',
            '    def test_reconciliation_requires_same_manager_subtree_proof(self):\n        from quantlab.desktop_runtime import RuntimeSafetyError\n        from desktop_app.shell.main_window import execute_ui_operation\n',
        ],
        [
            '        from unittest.mock import Mock\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import RuntimeSafetyError\n\n',
        ],
        [
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import _WindowsProcessTree\n        from quantlab.shared.runtime_errors import RuntimeSafetyError\n\n',
            '        from unittest.mock import Mock\n        from quantlab.desktop_runtime import _WindowsProcessTree, RuntimeSafetyError\n\n',
        ],
    ],
}
for _name, _pairs in EXTRA_RULES.items():
    RULES.setdefault(_name, []).extend(_pairs)


def apply(root):
    for name, pairs in RULES.items():
        path = root / name
        source = path.read_text(encoding='utf-8')
        for before, after in pairs:
            if before in source:
                source = source.replace(before, after, 1)
        path.write_text(source, encoding='utf-8', newline='\n')
    path = root / 'desktop_app/features/market/market.py'
    source = path.read_text(encoding='utf-8')
    binding = 'from desktop_app.features.market.dashboard import sample_market_series\n'
    if binding not in source:
        path.write_text(binding + source, encoding='utf-8', newline='\n')
    path = root / 'tests/fixtures/layered_paths/page_service_line_relocations.json'
    table = json.loads(path.read_text(encoding='utf-8'))
    digest = hashlib.sha256(json.dumps(table, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    helper = root / 'tests/layered_source_fixtures.py'
    source = helper.read_text(encoding='utf-8')
    prefix, rest = source.split('def project_page_service_lines', 1)
    rest = re.sub(r"(hexdigest\(\) != ')[a-f0-9]{64}(')", lambda m: m[1] + digest + m[2], rest, count=1)
    helper.write_text(prefix + 'def project_page_service_lines' + rest, encoding='utf-8', newline='\n')


if __name__ == '__main__':
    apply(Path(__file__).resolve().parents[2])
