"""Bounded, offline manual exchange. Origin is unverified; no inference is made.

Import/export never evaluates a candidate. Call preflight before passing the
sealed generator to research.run_campaign with the existing shared controls.
"""
from __future__ import annotations

import copy
import json
import math
import os
import secrets
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .core import ValidationError, canonical_json, content_hash, to_dict
from .research import (PARAMETER_CONTRACTS, PROMPT, _campaign_config,
                       _dataset_identity, candidate_fingerprint,
                       registry_json_schema, training_summary, validate_dsl)

MAX_BYTES = 131072
SCHEMA_VERSION = 1
PROMPT_VERSION = 'quantlab-v2'
REGISTRY_VERSION = 'manual-registry-v1'


def _strict(raw):
    if type(raw) not in (str, bytes):
        raise ValidationError('Manual response must be UTF-8 JSON text')
    try:
        data = raw.encode('utf-8') if type(raw) is str else raw
        if len(data) > MAX_BYTES:
            raise ValidationError('Manual JSON byte budget exceeded')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValidationError('Duplicate manual JSON key')
                result[key] = value
            return result
        def invalid(_):
            raise ValidationError('Nonfinite manual JSON number')
        result = json.loads(data.decode('utf-8'), object_pairs_hook=unique, parse_constant=invalid)
        count = 0
        def walk(value, depth=0):
            nonlocal count
            count += 1
            if depth > 24 or count > 8192:
                raise ValidationError('Manual JSON depth/node budget exceeded')
            if type(value) is dict:
                for item in value.values(): walk(item, depth + 1)
            elif type(value) is list:
                for item in value: walk(item, depth + 1)
            elif type(value) is float and not math.isfinite(value):
                raise ValidationError('Nonfinite manual JSON number')
        walk(result)
        return result
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValidationError('Invalid bounded manual JSON') from exc


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValidationError('Unknown or missing manual envelope keys')


def _source_hash():
    return content_hash(Path(__file__).read_text(encoding='utf-8'))


def export_request(dataset, config):
    """Return a safe public request; config and whole-data identities are opaque hashes."""
    splits = _campaign_config(dataset, config)
    if config['max_improvements'] != 0:
        raise ValidationError('Manual v1 requires max_improvements=0')
    if config['max_trials'] < len(config['families']):
        raise ValidationError('Manual v1 requires one trial per requested family')
    families = []
    schemas = []
    for family in config['families']:
        context = {'family': family, 'iteration': 0, 'seed': config['seed'],
                   'parameter_contract': copy.deepcopy(PARAMETER_CONTRACTS[family]),
                   'training': training_summary(splits['train']),
                   'validation': {'bar_count': len(splits['validation'].bars),
                                  'hash': content_hash(splits['validation'].bars)},
                   'previous': None}
        families.append({'family': family, 'context_hash': content_hash(context), 'context': context})
        schemas.append({'type': 'object', 'additionalProperties': False,
            'required': ['family', 'context_hash', 'candidate'], 'properties': {
                'family': {'const': family}, 'context_hash': {'const': content_hash(context)},
                'candidate': registry_json_schema(family)}})
    request = {'schema_version': SCHEMA_VERSION,
               'data_hash': _dataset_identity(dataset), 'config_hash': content_hash(to_dict(config)),
               'prompt_version': PROMPT_VERSION, 'prompt_hash': content_hash(PROMPT),
               'registry_version': REGISTRY_VERSION,
               'registry_hash': content_hash({f: registry_json_schema(f) for f in config['families']}),
               'module_source_hash': _source_hash(), 'families': families}
    request['request_id'] = content_hash(request)
    request['instructions'] = (PROMPT + '\nManual exchange: return exactly one response envelope following response_schema. '
        'Copy all envelope identities exactly. Supply one candidate for each requested family, in that order. '
        'In this manual v1 mode, rules MUST be {} and every parameter MUST be an integer as specified by response_schema. '
        'Return JSON only. Origin cannot be verified by this application.')
    props = {key: {'const': request[key]} for key in ('schema_version', 'request_id', 'data_hash', 'config_hash')}
    props['candidates'] = {'type': 'array', 'minItems': len(families), 'maxItems': len(families),
                           'prefixItems': schemas, 'items': False}
    request['response_schema'] = {'type': 'object', 'additionalProperties': False,
        'required': list(props), 'properties': props}
    encoded = canonical_json(request).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValidationError('Manual export exceeds byte budget')
    return request


def _checked_directory(path):
    """Reject symlinks/reparse points in every existing destination ancestor."""
    path = Path(os.path.abspath(os.fspath(path)))
    for ancestor in reversed((path, *path.parents)):
        info = ancestor.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                getattr(info, 'st_file_attributes', 0) & 0x400 or
                not stat.S_ISDIR(info.st_mode)):
            raise ValidationError('Manual export directory contains a link or reparse point')
    return path


@contextmanager
def _export_directory(path):
    path = _checked_directory(path)
    descriptor = None
    try:
        if os.name == 'posix':
            # Walk through directory handles: replacing an ancestor with a
            # symlink during export cannot redirect writes outside this tree.
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(path.anchor, flags)
            for part in path.parts[1:]:
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
        yield path, descriptor
    finally:
        if descriptor is not None:
            os.close(descriptor)


def export_request_file(dataset, config, path):
    """Atomically publish a new file, never replace an existing destination.

    A same-directory hard link provides create-only atomic publication. Filesystems
    without hard links fail closed. No overwrite fallback or directory creation.
    """
    request = export_request(dataset, config)
    encoded = (canonical_json(request) + '\n').encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValidationError('Manual export exceeds byte budget')
    target = Path(os.path.abspath(os.fspath(path)))
    temporary = '.manual-export-' + secrets.token_hex(16) + '.tmp'
    try:
        with _export_directory(target.parent) as (parent, directory_fd):
            kwargs = {'dir_fd': directory_fd} if directory_fd is not None else {}
            tmp_name = temporary if directory_fd is not None else str(parent / temporary)
            dst_name = target.name if directory_fd is not None else str(target)
            descriptor = os.open(tmp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600, **kwargs)
            owned = os.fstat(descriptor)
            try:
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                _checked_directory(parent)
                link_kwargs = ({'src_dir_fd': directory_fd, 'dst_dir_fd': directory_fd}
                               if directory_fd is not None else {})
                current = os.stat(tmp_name, follow_symlinks=False, **kwargs)
                if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
                    raise ValidationError('Manual export temporary file changed')
                os.link(tmp_name, dst_name, follow_symlinks=False, **link_kwargs)
            finally:
                # Remove only our own temporary inode. Never unlink a destination
                # or a file that another process substituted into the temp name.
                try:
                    current = os.stat(tmp_name, follow_symlinks=False, **kwargs)
                    if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                        os.unlink(tmp_name, **kwargs)
                except FileNotFoundError:
                    pass
    except OSError as exc:
        raise ValidationError('Manual export requires a new file in a safe writable directory; existing files are never overwritten') from exc
    return request


def _validate_response(response, request):
    _exact(response, ('schema_version', 'request_id', 'data_hash', 'config_hash', 'candidates'))
    for key in ('schema_version', 'request_id', 'data_hash', 'config_hash'):
        if type(response[key]) is not type(request[key]) or response[key] != request[key]:
            raise ValidationError('Manual request identity mismatch')
    entries = response['candidates']
    if type(entries) is not list or len(entries) != len(request['families']):
        raise ValidationError('Exactly one manual candidate per family is required')
    fingerprints = set()
    for entry, expected in zip(entries, request['families']):
        _exact(entry, ('family', 'context_hash', 'candidate'))
        if entry['family'] != expected['family'] or entry['context_hash'] != expected['context_hash']:
            raise ValidationError('Manual family/context mismatch')
        spec = validate_dsl(entry['candidate'])
        properties = registry_json_schema(expected['family'])['properties']['parameters']['properties']
        for name, bounds in properties.items():
            value = entry['candidate']['parameters'][name]
            if type(value) is not int or not bounds['minimum'] <= value <= bounds['maximum']:
                raise ValidationError('Manual parameter does not match response schema')
        if spec.family != expected['family']:
            raise ValidationError('Manual candidate changed family')
        # V1 response schema deliberately limits output to the built-in causal
        # registry rules. DSL validation still provides the semantic safety gate.
        if entry['candidate']['rules'] != {} or entry['candidate'].get('schema_version') != 1:
            raise ValidationError('Manual v1 requires schema_version=1 and registry rules={}')
        fingerprint = candidate_fingerprint(spec)
        if fingerprint in fingerprints:
            raise ValidationError('Duplicate manual candidate')
        fingerprints.add(fingerprint)


def import_response(dataset, config, raw):
    request = export_request(dataset, config)
    response = _strict(raw)
    _validate_response(response, request)
    package = {'request': request, 'response': response}
    return ManualGenerator(canonical_json(package).encode('utf-8'))


def import_response_file(dataset, config, path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES or
            getattr(info, 'st_file_attributes', 0) & 0x400):
        raise ValidationError('Manual import requires a bounded regular JSON file')
    # Nonblocking on POSIX also prevents a raced-in FIFO from blocking the UI.
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_BYTES or
                (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
            raise ValidationError('Manual import file changed or exceeds the byte limit')
        raw = stream.read(MAX_BYTES + 1)
    return import_response(dataset, config, raw)


@dataclass(frozen=True, init=False)
class ManualGenerator:
    """Immutable canonical bytes survive subprocess spawn, with fresh output copies.

    model binds package and this module's source into unchanged campaign identity.
    This is provenance, never proof of an actual ChatGPT response or model usage.
    """
    _package_json: bytes
    _seal: str
    mode = 'manual_unverified'
    endpoint = None
    real_model_status = 'not_verified'

    def __init__(self, package_json):
        package = _strict(package_json)
        _exact(package, ('request', 'response'))
        _validate_response(package['response'], package['request'])
        if package['request']['module_source_hash'] != _source_hash():
            raise ValidationError('Manual provider source changed')
        encoded = canonical_json(package).encode('utf-8')
        object.__setattr__(self, '_package_json', encoded)
        object.__setattr__(self, '_seal', content_hash({'package': package, 'source': _source_hash()}))

    @property
    def model(self):
        return 'manual:' + self._seal

    def _verified(self):
        package = _strict(self._package_json)
        seal = content_hash({'package': package, 'source': _source_hash()})
        if seal != self._seal:
            raise ValidationError('Manual sealed package or provider source changed')
        return package

    def preflight(self, dataset, config):
        package = self._verified()
        current = export_request(dataset, config)
        if current != package['request']:
            raise ValidationError('Manual campaign data/config/request changed; export and import again')
        return None

    def generate(self, context):
        package = self._verified()
        # Strictly finite/bounded JSON, then exact equality and hash; no partial match.
        try:
            context = _strict(canonical_json(context))
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValidationError('Invalid manual generation context') from exc
        for requested, entry in zip(package['request']['families'], package['response']['candidates']):
            if context == requested['context'] and content_hash(context) == entry['context_hash']:
                return copy.deepcopy(entry['candidate'])
        raise ValidationError('No sealed manual candidate matches the exact current context')

    def improve(self, context):
        raise ValidationError('Manual v1 does not support improvements')
