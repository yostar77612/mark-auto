"""The sector calls travel through the facade the desktop really uses (ContextIpcFacade) and the real dispatcher.

The installed 0.4.0 showed '族群資料讀取失敗' on every refresh because ContextIpcFacade.request did not accept the sector
keywords: the widget tests used fake facades, so no test crossed that boundary.
"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from quantlab.trading.adapters.storage.sector_store import SectorGroupStore
from quantlab.trading.application.codec import dumps, loads
from quantlab.trading.application.sector_contracts import SectorBoardView, SectorGroupsCommand, SectorGroupsView, SectorQuery
from quantlab.trading.application.sector_group_editor import SectorGroupEditor
from quantlab.trading.application.sector_service import SectorService
from quantlab.trading.domain.models import Environment
from quantlab.trading.domain.sector_alerts import SectorAlertParams
from quantlab.trading.runtime.config import RuntimeLaunch
from quantlab.trading.runtime.context_client import ContextIpcFacade
from quantlab.trading.runtime.protocol import Operation
from quantlab.trading.runtime.sector_settings import SectorAlertSettings
from quantlab.trading.runtime.server import _dispatch


class Offline:
    connected = False

    def snapshots(self, instruments):
        return ()


class SectorTransportTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.launch = RuntimeLaunch(root, Environment.BROKER_SIMULATION, account_ref='sinopac-pending', sinopac=True)
        service = SectorService(lambda: (), Offline(), lambda: datetime.now(timezone.utc))
        store = SectorGroupStore(root / 'sector_groups.json')
        self.bundle = SimpleNamespace(
            launch=self.launch,
            account_refs=('sinopac-pending',),
            sector=service,
            sector_groups=SectorGroupEditor(store, lambda: (), service.recompute),
            sector_settings=SectorAlertSettings(root / 'settings.json'),
        )
        self.client = ContextIpcFacade(self.launch)

    def call(self, method, *args):
        with patch('quantlab.trading.runtime.ipc.read_session') as session, patch('quantlab.trading.runtime.ipc.Client') as connection:
            session.return_value.key = b'test'
            wire = connection.return_value.__enter__.return_value
            wire.poll.return_value = True

            def reply(_):
                request = loads(wire.send_bytes.call_args.args[0].decode('utf-8'))
                return dumps(replace(_dispatch(self.bundle, request), request_id=request.request_id)).encode('utf-8')

            wire.recv_bytes.side_effect = reply
            result = getattr(self.client, method)(*args)
            return result, loads(wire.send_bytes.call_args.args[0].decode('utf-8'))

    def test_board_goes_through_the_context_facade_and_the_dispatcher(self):
        view, sent = self.call('sector_board', SectorQuery(''))
        self.assertIsInstance(view, SectorBoardView)
        self.assertEqual((view.state, sent.operation, sent.sector), ('OFFLINE', Operation.SECTOR_BOARD, SectorQuery('')))

    def test_group_list_goes_through_the_context_facade_and_the_dispatcher(self):
        view, sent = self.call('sector_groups', SectorGroupsCommand())
        self.assertIsInstance(view, SectorGroupsView)
        self.assertEqual(sent.operation, Operation.SECTOR_GROUPS)

    def test_settings_read_and_save_go_through_the_context_facade_and_the_dispatcher(self):
        params, sent = self.call('sector_settings')
        self.assertEqual((params, sent.operation, sent.sector_params), (SectorAlertParams(), Operation.SECTOR_SETTINGS, None))
        saved, sent = self.call('sector_settings', params)
        self.assertEqual((saved, sent.sector_params), (params, params))


if __name__ == '__main__':
    unittest.main()
