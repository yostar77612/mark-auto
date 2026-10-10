"""Opt-in frozen Python TLS proof against an ephemeral loopback HTTPS fixture.

Never contacts a public service, changes global trust, or loads a named TLS DLL.
This does not validate public trust stores, Qt Schannel, accounts or models.
"""
from __future__ import annotations

import ctypes
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import stat
import ssl
import sys
import tempfile
import threading
import time

NOTICE_SHA256 = '71043b02fdedfd821fb505f7fb46ee9520cdaa74e9dd2754e98647f0ebc61a2c'
DLL_NAMES = ('libssl-3.dll', 'libcrypto-3.dll')
VERSION = (3, 5, 9)
FIXTURE_SECONDS = 10
BODY = b'MarkAuto frozen Python HTTPS fixture v1\n'
BODY_SHA256 = hashlib.sha256(BODY).hexdigest()
SCOPE = 'ephemeral loopback Python HTTPS only; public trust-store, Qt Schannel, account and model acceptance not tested'


def safe_path(path, *, file=False):
    """Local absolute evidence paths only; no symlink, reparse or linked files."""
    path = Path(path)
    if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
        raise ValueError('TLS evidence requires a local absolute path')
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('TLS evidence path must not use links')
    if file:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('TLS evidence requires an unlinked regular file')
    return path


def read_pins(path):
    path = safe_path(Path(path), file=True)
    if path.stat().st_size > 65536:
        raise ValueError('TLS notice manifest exceeds bound')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != NOTICE_SHA256:
        raise ValueError('TLS notice manifest differs')
    value = json.loads(raw)['native_binaries']
    result = {name: value[name] for name in DLL_NAMES}
    if any(item['version'] != [*VERSION, 0] for item in result.values()):
        raise ValueError('TLS native version pin differs')
    return result


def loaded_module(name):
    if name not in DLL_NAMES or sys.platform != 'win32':
        raise ValueError('Only native Python TLS modules may be inspected')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    kernel.GetModuleHandleW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
    kernel.GetModuleFileNameW.restype = ctypes.c_uint
    handle = kernel.GetModuleHandleW(name)
    if not handle:
        raise ValueError('Expected TLS module is not already loaded')
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetModuleFileNameW(handle, buffer, len(buffer))
    if not length or length >= len(buffer):
        raise ValueError('Loaded TLS module path unavailable')
    return Path(buffer.value)


def runtime_evidence():
    # Importing Python ssl normally is the only operation selecting its TLS runtime.
    # GetModuleHandle/FileName merely inspect modules already present in this process.
    if sys.platform != 'win32' or getattr(sys, 'frozen', False) is not True:
        raise ValueError('Actual frozen Windows TLS runtime required')
    root = safe_path(Path(sys._MEIPASS)).resolve()
    pins = read_pins(root/'licenses'/'qt'/'manifest.json')
    if ssl.OPENSSL_VERSION_INFO[:3] != VERSION:
        raise ValueError('Actual Python TLS version differs')
    modules = []
    for name, pin in pins.items():
        path = safe_path(loaded_module(name), file=True)
        if path.resolve() != root/name or path.stat().st_size != pin['bytes']:
            raise ValueError('Python TLS module is outside the exact frozen location')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != pin['sha256']:
            raise ValueError('Actual loaded Python TLS module digest differs')
        modules.append({'filename': name, 'relative_path': name, 'sha256': digest, 'bytes': pin['bytes']})
    return {'frozen': True, 'platform': 'win32', 'openssl_version': ssl.OPENSSL_VERSION,
            'openssl_version_info': list(VERSION), 'notice_sha256': NOTICE_SHA256,
            'loaded_from': 'exact_frozen_bundle', 'modules': modules}


def fixture_certificates(directory, address='127.0.0.1'):
    """One ephemeral CA and leaf; keys stay in the caller-owned temporary directory."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    now = datetime.now(timezone.utc)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'MarkAuto ephemeral fixture CA')])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(minutes=5))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    leaf_key = ec.generate_private_key(ec.SECP256R1())
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'MarkAuto local fixture')]))
            .issuer_name(ca_name).public_key(leaf_key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(minutes=5))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), critical=False)
            .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_key, hashes.SHA256()))
    cert, key = Path(directory)/'leaf.pem', Path(directory)/'leaf-key.pem'
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return ca.public_bytes(serialization.Encoding.PEM).decode('ascii'), cert, key


def https_fixture(root):
    start = time.monotonic(); deadline = start+FIXTURE_SECONDS
    def remaining():
        value = deadline-time.monotonic()
        if value <= 0: raise TimeoutError('Local TLS fixture deadline expired')
        return value
    listener = client = worker = None
    active = []; lock = threading.Lock(); state = {'requests': 0, 'error': False}
    cleanup = False
    with tempfile.TemporaryDirectory(prefix='tls-fixture-', dir=root) as directory:
        try:
            ca, cert, key = fixture_certificates(directory)
            server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            server_context.minimum_version = ssl.TLSVersion.TLSv1_2
            server_context.load_cert_chain(cert, key)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            # No default/system roots: only this short-lived fixture CA is trusted.
            context.load_verify_locations(cadata=ca)
            if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
                raise ValueError('Fixture certificate and hostname checks required')
            timeout = min(2, remaining())
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.settimeout(timeout)
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            def serve():
                connection = None
                try:
                    connection, peer = listener.accept()
                    if peer[0] != '127.0.0.1': raise ValueError('Nonlocal fixture client refused')
                    connection.settimeout(min(2, remaining()))
                    with lock: active.append(connection)
                    secure = server_context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
                    with lock: active.append(secure)
                    connection = secure; secure.do_handshake()
                    request = b''
                    while b'\r\n\r\n' not in request:
                        secure.settimeout(min(2, remaining()))
                        part = secure.recv(4097-len(request))
                        if not part: raise ValueError('Incomplete fixture request')
                        request += part
                        if len(request) > 4096: raise ValueError('Fixture request exceeds bound')
                    if (not request.startswith(b'GET /markauto-tls-fixture HTTP/1.1\r\n')
                        or b'authorization:' in request.lower() or b'cookie:' in request.lower()):
                        raise ValueError('Unexpected fixture request')
                    state['requests'] += 1
                    secure.settimeout(min(2, remaining()))
                    secure.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: '+str(len(BODY)).encode()+
                                   b'\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n'+BODY)
                except BaseException: state['error'] = True
                finally:
                    if connection is not None: connection.close()
            worker = threading.Thread(target=serve, name='markauto-owned-tls-fixture')
            worker.start()
            client = http.client.HTTPSConnection('127.0.0.1', listener.getsockname()[1],
                                                context=context, timeout=min(2, remaining()))
            client.connect()
            protocol, cipher = client.sock.version(), client.sock.cipher()[0]
            client.sock.settimeout(min(2, remaining()))
            client.request('GET', '/markauto-tls-fixture')
            response = client.getresponse()
            body = response.read(len(BODY)+1)
            if response.status != 200 or body != BODY:
                raise ValueError('Local HTTPS response differs')
        finally:
            if client is not None: client.close()
            if listener is not None: listener.close()
            with lock:
                for connection in active:
                    try: connection.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    connection.close()
            if worker is not None:
                worker.join(timeout=max(0, deadline-time.monotonic()))
                if worker.is_alive(): raise RuntimeError('Owned TLS fixture did not stop')
            cleanup = True
        if state['error'] or state['requests'] != 1 or time.monotonic() > deadline:
            raise ValueError('Local TLS fixture failed')
    if time.monotonic() > deadline: raise TimeoutError('TLS fixture cleanup exceeded deadline')
    return {'status': 'passed', 'transport': 'loopback_fixture', 'requests': state['requests'],
            'certificate_verified': True, 'hostname_verified': True, 'trust_scope': 'ephemeral_fixture_ca',
            'protocol': protocol, 'cipher': cipher, 'status_code': 200, 'response_sha256': BODY_SHA256,
            'cleanup_verified': cleanup, 'external_network_used': False,
            'seconds': round(time.monotonic()-start, 3), 'cap_seconds': FIXTURE_SECONDS}


def run(root):
    result = {'status': 'failed', 'scope': SCOPE}
    try:
        # Fail before opening any fixture socket if DLL provenance differs.
        result['runtime'] = runtime_evidence()
        result['https'] = https_fixture(root)
        if runtime_evidence() != result['runtime']:
            raise ValueError('Python TLS runtime changed during fixture')
        result['status'] = 'passed'
    except Exception as exc:
        result['error_category'] = ('certificate_verification' if isinstance(exc, ssl.SSLCertVerificationError)
                                    else 'timeout' if isinstance(exc, TimeoutError)
                                    else 'io' if isinstance(exc, OSError) else 'validation')
    return result


def validate_report(value, manifest_path):
    if not isinstance(value, dict) or value.get('status') != 'passed' or value.get('scope') != SCOPE:
        raise ValueError('Missing frozen Python TLS proof')
    runtime, proof = value.get('runtime'), value.get('https')
    if not isinstance(runtime, dict) or not isinstance(proof, dict): raise ValueError('Invalid TLS proof')
    expected = {'frozen': True, 'platform': 'win32', 'openssl_version_info': list(VERSION),
                'notice_sha256': NOTICE_SHA256, 'loaded_from': 'exact_frozen_bundle'}
    for key, item in expected.items():
        if type(runtime.get(key)) is not type(item) or runtime[key] != item: raise ValueError('TLS runtime mismatch')
    version = runtime.get('openssl_version')
    if not isinstance(version, str) or len(version) > 128 or not version.startswith('OpenSSL 3.5.9 '):
        raise ValueError('TLS version text mismatch')
    pins = read_pins(manifest_path)
    modules = [{'filename': name, 'relative_path': name, 'sha256': pin['sha256'], 'bytes': pin['bytes']}
               for name, pin in pins.items()]
    if runtime.get('modules') != modules: raise ValueError('TLS loaded module evidence mismatch')
    expected = {'status':'passed', 'transport':'loopback_fixture', 'requests':1, 'certificate_verified':True,
                'hostname_verified':True, 'trust_scope':'ephemeral_fixture_ca', 'status_code':200,
                'response_sha256':BODY_SHA256, 'cleanup_verified':True, 'external_network_used':False,
                'cap_seconds':FIXTURE_SECONDS}
    for key, item in expected.items():
        if type(proof.get(key)) is not type(item) or proof[key] != item: raise ValueError('TLS HTTPS proof mismatch')
    if proof.get('protocol') not in ('TLSv1.2', 'TLSv1.3'): raise ValueError('TLS protocol mismatch')
    if not isinstance(proof.get('cipher'), str) or not 1 <= len(proof['cipher']) <= 128:
        raise ValueError('Missing negotiated TLS cipher')
    if type(proof.get('seconds')) not in (int, float) or not 0 <= proof['seconds'] <= FIXTURE_SECONDS:
        raise ValueError('TLS fixture exceeded deadline')


def write_report(path):
    """Explicit standalone frozen proof, outside user workspace and model paths."""
    path = safe_path(Path(path))
    if path.exists():
        raise ValueError('TLS evidence report already exists; refusing overwrite')
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_path(path.parent)
    with tempfile.TemporaryDirectory(prefix='markauto-tls-proof-') as directory:
        result = run(safe_path(Path(directory)))
    with path.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=True, indent=2)
        stream.write('\n')
    return 0 if result.get('status') == 'passed' else 1
