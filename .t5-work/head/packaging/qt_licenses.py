"""Pinned Qt license texts and a fail-closed frozen Windows module-scope audit.

This is a packaging check, not a legal-clearance assertion. It never loads DLLs.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat

QT_VERSION = (6, 12, 0)
QT_DEPENDENCY_VERSIONS = {
    'PySide6': '6.12.0', 'PySide6_Essentials': '6.12.0',
    'PySide6_Addons': '6.12.0', 'shiboken6': '6.12.0',
}
MANIFEST_SHA256 = '71043b02fdedfd821fb505f7fb46ee9520cdaa74e9dd2754e98647f0ebc61a2c'
MAX_NOTICE_BYTES = 256 * 1024
MODULES = frozenset({
    'Core', 'Gui', 'Network', 'OpenGL', 'Qml', 'QmlMeta', 'QmlModels',
    'QmlWorkerScript', 'Quick', 'Svg', 'Widgets',
})
BINDINGS = frozenset({'QtCore.pyd', 'QtGui.pyd', 'QtNetwork.pyd', 'QtWidgets.pyd'})
PLUGINS = frozenset({
    'generic/qtuiotouchplugin.dll', 'iconengines/qsvgicon.dll',
    'imageformats/qgif.dll', 'imageformats/qicns.dll', 'imageformats/qico.dll',
    'imageformats/qjpeg.dll', 'imageformats/qsvg.dll', 'imageformats/qtga.dll',
    'imageformats/qtiff.dll', 'imageformats/qwbmp.dll', 'imageformats/qwebp.dll',
    'networkinformation/qnetworklistmanager.dll',
    'platforms/qdirect2d.dll', 'platforms/qminimal.dll',
    'platforms/qoffscreen.dll', 'platforms/qwindows.dll',
    'styles/qmodernwindowsstyle.dll', 'tls/qcertonlybackend.dll',
    'tls/qschannelbackend.dll',
})
REQUIRED = frozenset({
    'pyside6/qt6core.dll', 'pyside6/qt6gui.dll', 'pyside6/qt6widgets.dll',
    'pyside6/qtcore.pyd', 'pyside6/qtgui.pyd', 'pyside6/qtwidgets.pyd',
    'pyside6/plugins/platforms/qwindows.dll',
    'pyside6/plugins/tls/qschannelbackend.dll',
    'pyside6/plugins/tls/qcertonlybackend.dll',
})
NATIVE_REQUIRED = frozenset({'libssl-3.dll', 'libcrypto-3.dll'})


def reject_links(path):
    path = Path(path).absolute()
    for entry in (*reversed(path.parents), path):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('Qt notice/payload path contains a link or reparse point')


def bounded_bytes(path):
    path = Path(path)
    reject_links(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise RuntimeError('Required Qt notice file is missing') from None
    if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_NOTICE_BYTES:
        raise RuntimeError('Qt notice must be a bounded regular file')
    with path.open('rb') as stream:
        raw = stream.read(MAX_NOTICE_BYTES + 1)
    if len(raw) > MAX_NOTICE_BYTES:
        raise RuntimeError('Qt notice exceeds size bound')
    return raw


def reviewed_notice_bytes(folder):
    folder = Path(folder)
    raw = bounded_bytes(folder / 'manifest.json')
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError('Qt notice manifest checksum mismatch')
    manifest = json.loads(raw)
    expected = {'manifest.json', *manifest['files']}
    if {path.name for path in folder.iterdir()} != expected:
        raise RuntimeError('Qt notice directory has missing or unreviewed entries')
    result = {'manifest.json': raw}
    for name, item in manifest['files'].items():
        if PurePosixPath(name).name != name or '\\' in name:
            raise RuntimeError('Unsafe Qt notice filename')
        data = bounded_bytes(folder / name)
        if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise RuntimeError('Qt notice checksum mismatch')
        result[name] = data
    return result


def copy_notice_bytes(reviewed, destination):
    destination = Path(destination)
    reject_links(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name, raw in reviewed.items():
        target = destination / name
        reject_links(target)
        if target.exists() and not stat.S_ISREG(target.lstat().st_mode):
            raise RuntimeError('Qt notice destination must be a regular file')
        target.write_bytes(raw)


def _normalized(path):
    return str(path).replace('\\', '/').casefold()


def unused_component(path):
    value = _normalized(path)
    name = PurePosixPath(value).name
    # Qt's optional OpenSSL backend uses a distinct affected 3.5.5 DLL pair.
    # Preserve the unsuffixed 3.5.9 pair imported by Python HTTPS.
    if name in {'qopensslbackend.dll', 'libssl-3-x64.dll', 'libcrypto-3-x64.dll'}:
        return True
    # Include module, plugin, QML/resource directories and translation variants.
    if ('pyside6/' in value and 'virtualkeyboard' in value) or (
            name.startswith(('qtvirtualkeyboard', 'qt6virtualkeyboard')) and
            PurePosixPath(name).suffix in {'.dll', '.pyd', '.rcc', '.qm', '.qml'}):
        return True
    if name in {'qt6virtualkeyboard.dll', 'qtvirtualkeyboardplugin.dll', 'qtvirtualkeyboard.pyd'}:
        return True
    # No QtPdf/QPdfWriter/QPrinter use exists in the application's report export.
    if name in {'qt6pdf.dll', 'qt6pdfwidgets.dll', 'qtpdf.pyd', 'qtpdfwidgets.pyd'}:
        return True
    return value.endswith('pyside6/plugins/imageformats/qpdf.dll') or (
        'pyside6/translations/' in value and name.startswith('qtpdf_'))


def audit_paths(paths, require_core=True):
    present = set()
    modules = set()
    plugins = set()
    for path in paths:
        value = _normalized(path)
        if PurePosixPath(value).is_absolute() or any(part in {'.', '..'} for part in value.split('/')) or ':' in value:
            raise RuntimeError('Unsafe Qt payload destination: ' + str(path))
        if value.startswith('_internal/'):
            value = value[len('_internal/'):]
        if unused_component(value):
            raise RuntimeError('Excluded Qt component remains in payload: ' + str(path))
        if value.startswith(('pyside6/qml/', 'pyside6/resources/')):
            raise RuntimeError('Unreviewed Qt QML/resource payload: ' + str(path))
        present.add(value)
        name = PurePosixPath(value).name
        match = re.fullmatch(r'qt6(.+)\.dll', name)
        if match:
            allowed = {module.casefold(): module for module in MODULES}
            if match[1] not in allowed:
                raise RuntimeError('Unreviewed Qt module in payload: ' + str(path))
            modules.add(allowed[match[1]])
        if value.startswith('pyside6/') and name.startswith('qt') and name.endswith('.pyd'):
            if name not in {entry.casefold() for entry in BINDINGS}:
                raise RuntimeError('Unreviewed Qt Python binding in payload: ' + str(path))
        marker = 'pyside6/plugins/'
        if marker in value:
            plugin = value.split(marker, 1)[1]
            if plugin not in PLUGINS:
                raise RuntimeError('Unreviewed Qt plugin in payload: ' + str(path))
            plugins.add(plugin)
    if require_core and not REQUIRED <= present:
        raise RuntimeError('Required Qt Widgets/native Windows input payload missing: ' + ', '.join(sorted(REQUIRED - present)))
    return {'qt_modules': sorted(modules), 'qt_plugins': sorted(plugins)}


def filter_payload_toc(entries):
    """Remove only explicitly reviewed optional/affected components."""
    kept = []
    for entry in entries:
        if unused_component(entry[0]):
            print('Excluded reviewed Qt/TLS component:', entry[0])
        else:
            kept.append(entry)
    audit_paths([entry[0] for entry in kept], require_core=False)
    return kept


def pe_version(path):
    import pefile
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
        values = getattr(pe, 'VS_FIXEDFILEINFO', [])
        if len(values) != 1:
            raise RuntimeError('Qt binary has no unambiguous version resource: ' + str(path))
        value = values[0]
        return (value.FileVersionMS >> 16, value.FileVersionMS & 65535,
                value.FileVersionLS >> 16, value.FileVersionLS & 65535)
    finally:
        pe.close()


def audit_payload(payload):
    payload = Path(payload)
    reject_links(payload)
    internal = payload / '_internal'
    reject_links(internal)
    if not internal.is_dir():
        raise RuntimeError('Actual frozen _internal directory is missing')
    entries = sorted(internal.rglob('*'))
    for path in entries:
        reject_links(path)
    paths = [path for path in entries if path.is_file()]
    result = audit_paths([path.relative_to(internal).as_posix() for path in paths])
    notices = reviewed_notice_bytes(internal / 'licenses/qt')
    versions = {}
    hashes = {}
    native_expected = json.loads(notices['manifest.json'])['native_binaries']
    native_hashes = {}
    for path in paths:
        name = path.name.casefold()
        relative = path.relative_to(internal).as_posix()
        if name == 'opengl32sw.dll' or re.fullmatch(r'lib(?:ssl|crypto)-.*\.dll', name):
            # A version/hash change requires native notice provenance review.
            expected = native_expected.get(relative.casefold())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if not expected or digest != expected['sha256']:
                raise RuntimeError('Unreviewed native Qt/OpenSSL dependency: ' + relative)
            if expected.get('version') and list(pe_version(path)) != expected['version']:
                raise RuntimeError('Native dependency version differs from reviewed notice source: ' + relative)
            native_hashes[relative] = digest
        if re.fullmatch(r'qt6.+\.dll', name):
            value = pe_version(path)
            if value[:3] != QT_VERSION:
                raise RuntimeError('Qt binary version differs from reviewed source version: ' + str(path))
            relative = path.relative_to(internal).as_posix()
            versions[relative] = list(value)
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not NATIVE_REQUIRED <= {name.casefold() for name in native_hashes}:
        raise RuntimeError('Required reviewed Python HTTPS libraries are missing')
    return result | {
        'status': 'PASS', 'scope': 'Qt module/plugin selection, versions, fixed native dependency notices and required license-text copies; not full third-party legal clearance',
        'qt_version': '.'.join(map(str, QT_VERSION)),
        'binary_versions': versions, 'binary_sha256': hashes,
        'reviewed_native_dependency_sha256': native_hashes,
        'notice_sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in notices.items()},
        'virtual_keyboard_present': False, 'qt_pdf_present': False,
        'qwindows_platform_plugin_present': True,
        'qt_tls_backend_scope': 'Schannel and certificate-only; optional OpenSSL backend excluded',
        'python_tls_scope': 'Retained unsuffixed OpenSSL 3.5.9 DLL hashes and version resources; live frozen Python HTTPS not tested here',
        'native_ime_behavior': 'NOT TESTED by static payload audit',
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    result = audit_payload(args.payload)
    reject_links(args.report)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
