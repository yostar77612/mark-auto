"""Concept group edits for the sector board: validates through the store, flags codes the directory lacks."""

from typing import Callable

from quantlab.trading.domain.watch import WatchInstrument
from quantlab.trading.ports.sector import GroupStorePort
from .sector_contracts import GroupEditView, SectorGroupsCommand, SectorGroupsView


class SectorGroupEditor:
    def __init__(self, store: GroupStorePort, directory: Callable[[], tuple[WatchInstrument, ...]], changed: Callable[[], None] = lambda: None):
        self.store, self.directory, self.changed = store, directory, changed

    def view(self, selected_id: str = '') -> SectorGroupsView:
        known = {item.code for item in self.directory()}
        groups = tuple(
            GroupEditView(
                record.id,
                record.name,
                record.codes,
                # A short directory (offline, not refreshed yet) must not flag every code as missing.
                tuple(code for code in record.codes if code not in known) if len(known) > 10 else (),
                record.builtin,
                record.edited,
                record.deleted,
            )
            for record in self.store.records()
        )
        return SectorGroupsView(groups, selected_id, self.store.warning)

    def execute(self, command: SectorGroupsCommand) -> SectorGroupsView:
        selected = command.group_id
        if command.action == 'CREATE':
            selected = self.store.create(command.name, command.codes)
        elif command.action == 'RENAME':
            self.store.rename(command.group_id, command.name)
        elif command.action == 'SET_CODES':
            self.store.set_codes(command.group_id, command.codes)
        elif command.action == 'DELETE':
            self.store.delete(command.group_id)
        elif command.action == 'RESTORE':
            self.store.restore(command.group_id)
        if command.action != 'LIST':
            self.changed()
        return self.view(selected)
