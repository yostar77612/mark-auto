"""Retire an explicitly connected legacy read-only SDK before unified login."""

from threading import Event, Thread

from quantlab.trading.application.contracts import UiReceipt


def disconnect_legacy(bundle):
    with bundle.lock:
        if bundle.legacy_disconnected:
            return UiReceipt(True, 'completed', '')
        if bundle.legacy_disconnecting or bundle.legacy_cleanup_unconfirmed:
            return UiReceipt(False, 'outcome_unknown', '')
        bundle.legacy_disconnecting = True
        bundle.query_caches = ()
    done, errors = Event(), []

    def release():
        try:
            connection = bundle.market_connection
            worker = connection.worker
            if worker is not None and worker.is_alive():
                worker.join(7.0)
            with connection.lock:
                if connection.worker is not None and connection.worker.is_alive():
                    raise RuntimeError('legacy transition pending')
                session = connection.session
                connection.session, connection.status = None, 'DISCONNECTED'
            connection.on_disconnected()
            if session is not None:
                if session.disconnect() is False:
                    raise RuntimeError('legacy logout unconfirmed')
            if bundle.engine is not None and bundle.launch.environment.value != 'LOCAL':
                seen = set()
                for gateway in bundle.engine.gateways.values():
                    if id(gateway) not in seen:
                        seen.add(id(gateway))
                        gateway.disconnect()
            bundle.legacy_disconnected = True
            connection.error = ''
        except Exception:
            bundle.legacy_cleanup_unconfirmed = True
            bundle.market_connection.error = 'logout_unconfirmed'
            errors.append('outcome_unknown')
        finally:
            bundle.legacy_disconnecting = False
            done.set()

    Thread(target=release, name='markauto-legacy-session-release', daemon=True).start()
    if not done.wait(7.5) or errors:
        bundle.legacy_cleanup_unconfirmed = True
        bundle.market_connection.error = 'logout_unconfirmed'
        return UiReceipt(False, 'outcome_unknown', '')
    return UiReceipt(True, 'completed', '')
