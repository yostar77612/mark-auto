from quantlab.research_core.ports.ui_operations import UiOperationPorts


def recover_state(ports: UiOperationPorts, paths, backups):
    with ports.recovery.admission(paths) as token:
        try:
            ports.recovery.recover_control_journal(paths, admission=token)
            disposition = ports.recovery.inspect_recovery(paths)
        except ports.recovery.RecoveryError:
            disposition = None
        if disposition is None or disposition.unresolved:
            if not ports.files.is_dir(paths.state) or any(
                (
                    ports.files.exists(path) or ports.files.is_symlink(path)
                    for path in (paths.root / 'state-v1.rollback', paths.root / 'restore-transaction.json', paths.state / '.restore-transaction')
                )
            ):
                raise ports.recovery.RecoveryError(ports.text('ui.quiesce_and_recover.unknown_stop_evidence'))
            return
        if backups is not None:
            backups.recover()
        else:
            ports.backups.BackupManager(paths).recover()
