"""Optional explicit certificate activation using a password reference only."""

from dataclasses import replace
from pathlib import Path
from time import monotonic

from quantlab.trading.domain.validation import DomainError


def activate_certificate(owner, settings, ticket):
    if settings is None or settings.environment is not owner.configuration.environment:
        raise DomainError('validation_failed', 'accepted connection environment required')
    path = Path(settings.certificate_path)
    if not settings.certificate_path or path.suffix.lower() != '.pfx' or not path.is_file():
        raise DomainError('capability_missing', 'certificate file unavailable')
    selected = tuple(account for account in owner.accounts if account.alias in owner.selected)
    people = {getattr(account.native, 'person_id', None) for account in selected}
    if not selected or len(people) != 1 or not all(isinstance(person, str) and person for person in people):
        raise DomainError('capability_missing', 'selected account certificate identity unavailable')
    configuration = replace(owner.configuration, certificate_path=settings.certificate_path, certificate_secret_ref=settings.certificate_secret_ref)
    with owner.lock:
        owner.publish(certificate_status='ACTIVATING')
    password = owner.secrets.certificate_password(configuration.certificate_secret_ref)
    try:
        activated = owner.shared.facade.activate_ca(ca_path=str(path), ca_passwd=password, person_id=next(iter(people)))
    finally:
        del password
    if activated is not True:
        raise DomainError('capability_missing', 'certificate activation unconfirmed')
    with owner.lock:
        if owner.closed or ticket != owner.ticket or monotonic() >= owner.deadline:
            raise DomainError('outcome_unknown', 'late certificate result')
        owner.preferences.save(configuration, owner.selected)
        owner.configuration = configuration
        owner.publish(settings=configuration, certificate_status='READY', error_code='')
