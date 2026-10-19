"""Verified TLS using only the platform ROOT store as trust anchors.

Windows' CA store may contain expired cross-signed intermediates. Loading those
as anchors can override a valid server chain. Do not enumerate that store here.
Other platforms, unavailable stores and empty stores use verified defaults.
"""

import ssl


def build_trust_context(*, store_loader=None):
    """Build a server-auth context; the injectable loader accepts a store name.

    Entries follow ssl.enum_certificates: (DER bytes, encoding, trust OIDs).
    Selection is by ROOT-store membership and server-auth trust, independently
    of subject names. OpenSSL still checks chain validity and hostname at use.
    """
    loader = store_loader if store_loader is not None else getattr(ssl, 'enum_certificates', None)
    if loader is None:
        return ssl.create_default_context()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    loaded = 0
    try:
        for der, encoding, trust in loader('ROOT'):
            if encoding != 'x509_asn' or not (trust is True or isinstance(trust, (set, frozenset)) and '1.3.6.1.5.5.7.3.1' in trust):
                continue
            try:
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(der))
                loaded += 1
            except (ssl.SSLError, ValueError, TypeError):
                continue
    except OSError:
        return ssl.create_default_context()
    return context if loaded else ssl.create_default_context()
