"""Offline evidence/ownership tests; no real download, Windows process, or model call."""
import copy
from contextlib import closing
import ctypes
from dataclasses import replace
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch
import zlib

from quantlab import local_ai

ROOT = Path(__file__).resolve().parents[1]
MODULE_SPEC = importlib.util.spec_from_file_location('markauto_local_ai_ci', ROOT / 'packaging/validate_local_ai.py')
ci = importlib.util.module_from_spec(MODULE_SPEC)
# dataclasses resolves annotations through sys.modules, not the installed packaging package.
sys.modules[MODULE_SPEC.name] = ci
MODULE_SPEC.loader.exec_module(ci)

OWNER = {'pid': 123, 'created': 456}
CANDIDATE = {'schema_version': 1, 'strategy_id': 'offline_ci_fixture', 'family': 'trend',
             'parameters': {'fast': 5, 'slow': 20}, 'rules': {}}


def pin(raw, filename, url='https://github.com/fixture/runtime.zip'):
    return {'filename': filename, 'url': url, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def chunk(kind, payload):
    return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload) & 0xffffffff)


def png(*, width=640, height=360, image_data=None, header=None):
    # A genuinely decodable RGB image, < 1 KiB compressed, never a placeholder file.
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0) if header is None else header
    if image_data is None:
        image_data = zlib.compress((b'\0' + b'\x12\x34\x56' * width) * height)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', image_data) + chunk(b'IEND', b'')


class DownloadResponse(io.BytesIO):
    def __init__(self, raw, url):
        super().__init__(raw)
        self.url = url
        self.status = 200
        self.headers = {'Content-Length': str(len(raw))}

    def geturl(self):
        return self.url


class CIFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'checkout with spaces; inert'
        self.executable = self.root / 'dist' / 'MarkAuto' / 'MarkAuto.exe'
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b'INERT EXE: never execute')
        self.raw = {'runtime': b'INERT ZIP fixture', 'model': b'GGUF INERT model fixture'}
        self.spec = {'runtime': pin(self.raw['runtime'], 'runtime.zip'),
                     'model': pin(self.raw['model'], 'model.gguf', 'https://huggingface.co/fixture/model.gguf'),
                     'runtime_members': {'llama-server.exe': pin(b'inert server', 'llama-server.exe')},
                     'support_dlls': {'vcruntime140.dll': pin(b'inert vc', 'vcruntime140.dll')},
                     'licenses': {'LICENSE.txt': pin(b'inert notice', 'LICENSE.txt')}}
        for target, name, kwargs in (
            (ci, 'ROOT', {'new': self.root}),
            (ci, 'manifest', {'return_value': self.spec}),
            (ci.subprocess, 'Popen', {'side_effect': AssertionError('No real processes in offline fixtures')}),
        ):
            guard = patch.object(target, name, **kwargs)
            guard.start()
            self.addCleanup(guard.stop)
        for name in ('socket.create_connection', 'os.system'):
            guard = patch(name, side_effect=AssertionError('Offline test must not reach network or shell'))
            guard.start()
            self.addCleanup(guard.stop)
        self.config = self.new_config()

    def new_config(self, suffix=''):
        return ci.Config(self.executable, self.base / ('cache' + suffix), self.base / ('work' + suffix),
                         self.root / 'dist' / 'validation' / suffix / 'local-ai-smoke.json')

    def cache_files(self, config=None):
        config = config or self.config
        config.cache.mkdir(parents=True, exist_ok=True)
        for name, raw in self.raw.items():
            (config.cache / self.spec[name]['filename']).write_bytes(raw)

    def write_report(self, value, config=None):
        config = config or self.config
        config.report.parent.mkdir(parents=True, exist_ok=True)
        config.report.write_text(json.dumps(value), encoding='utf-8')

    def fixture_probe(self, config=None):
        config = config or self.config
        transport = Mock(return_value={'choices': [{'message': {'content': json.dumps(CANDIDATE)}}]})
        with patch.object(local_ai, 'HTTPTransport', return_value=transport), \
             patch.object(local_ai, 'health', return_value=True), patch.object(local_ai, 'verify_owner'):
            result = local_ai.probe(config.attempt / 'control-v1', OWNER)
        self.assertEqual(transport.call_count, 1)
        return result, transport

    def complete_evidence(self, config=None):
        config = config or self.config
        probe, _ = self.fixture_probe(config)
        result = {'status': 'passed', 'frozen': True, 'platform': 'win32', 'profile': ci.PROFILE,
                  'manifest_sha256': ci.MANIFEST_SHA256, 'model_calls': 1, 'cleanup_verified': True,
                  'external_api_spend': '0', 'paid_fallback': False, 'research_evaluations': 0,
                  'oos_or_holdout_access': False, 'real_model_status': 'not_verified',
                  'clean_windows_client_status': 'not_verified', 'native_window_screenshot_saved': True,
                  'model_sha256': self.spec['model']['sha256'], 'runtime_sha256': self.spec['runtime']['sha256'],
                  'runtime_members_verified': len(self.spec['runtime_members']), 'licenses_verified': len(self.spec['licenses']),
                  'application_vc_dependencies_verified': len(self.spec['support_dlls']),
                  'owned_server': copy.deepcopy(OWNER), 'probe': probe,
                  'stages': [{'stage': stage, 'cap_seconds': cap, 'status': 'passed', 'seconds': 1.2}
                             for stage, cap in (('verified_setup', 300), ('owned_server_start', 150), ('one_schema_probe', 135))],
                  'loaded_vc_runtime_modules': [{'filename': name, 'sha256': value['sha256'],
                                               'loaded_from': 'pinned_app_local_runtime'}
                                              for name, value in self.spec['support_dlls'].items()]}
        self.write_report(result, config)
        config.report.with_suffix('.png').write_bytes(png())
        return result

    def mutate_db(self, sql, config=None):
        config = config or self.config
        with closing(sqlite3.connect(config.attempt / 'control-v1' / 'local-ai-v1.sqlite3')) as db, db:
            db.execute(sql)

    def argv(self, config=None, phase=None):
        config = config or self.config
        args = []
        for key in ('executable', 'cache', 'work', 'report'):
            args.extend(['--' + key, str(getattr(config, key))])
        if phase:
            args.extend(['--internal-phase', phase])
        return args


class DownloadAndPathTests(CIFixture):
    def test_only_exact_official_pins_download_once_then_reuse_verified_cache(self):
        requests = []
        def opened(request, timeout):
            requests.append((request.full_url, timeout))
            name = next(name for name in self.raw if self.spec[name]['url'] == request.full_url)
            return DownloadResponse(self.raw[name], request.full_url)
        opener = Mock()
        opener.open.side_effect = opened
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener):
            first = ci.download_phase(self.config)
        self.assertEqual(requests, [(self.spec[name]['url'], 20) for name in ('runtime', 'model')])
        with patch.object(local_ai.urllib.request, 'build_opener', side_effect=AssertionError('Cache reuse may not download')):
            second = ci.download_phase(self.config)
        for name in ('runtime', 'model'):
            self.assertEqual(first[name], {'sha256': self.spec[name]['sha256'], 'bytes': self.spec[name]['bytes'], 'cache_hit': False})
            self.assertEqual(second[name], {**first[name], 'cache_hit': True})
        self.assertFalse(list(self.config.cache.glob('*.partial')))
        self.assertFalse(self.config.work.exists())

    def test_corrupt_cache_never_replaced_or_downloaded(self):
        self.cache_files()
        bad = self.config.cache / self.spec['runtime']['filename']
        bad.write_bytes(b'x' * len(self.raw['runtime']))
        with patch.object(local_ai.urllib.request, 'build_opener') as network:
            with self.assertRaises(local_ai.LocalAIError):
                ci.download_phase(self.config)
        network.assert_not_called()
        self.assertEqual(bad.read_bytes(), b'x' * len(self.raw['runtime']))

    def test_bad_download_pin_stops_without_model_download_or_execution(self):
        opener = Mock()
        opener.open.return_value = DownloadResponse(b'x' * len(self.raw['runtime']), self.spec['runtime']['url'])
        with patch.object(local_ai.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(local_ai.LocalAIError):
                ci.download_phase(self.config)
        self.assertEqual(opener.open.call_count, 1)
        self.assertFalse((self.config.cache / self.spec['runtime']['filename']).exists())
        self.assertFalse((self.config.cache / self.spec['model']['filename']).exists())

    def test_unapproved_url_fails_before_network(self):
        self.spec['runtime']['url'] = 'https://untrusted.invalid/runtime.zip'
        with patch.object(local_ai.urllib.request, 'build_opener') as network:
            with self.assertRaises(local_ai.LocalAIError):
                ci.download_phase(self.config)
        network.assert_not_called()

    def test_fresh_separate_external_work_and_cache_are_accepted(self):
        self.config.validate()
        self.assertFalse(self.config.cache.is_relative_to(self.root))
        self.assertFalse(self.config.work.is_relative_to(self.root))

    def test_cache_and_work_cannot_live_in_checkout_or_published_artifacts(self):
        for name in ('cache', 'work'):
            for folder in (self.root / 'scratch', self.root / 'dist' / 'validation', self.root / 'dist' / 'MarkAuto'):
                with self.subTest(name=name, folder=folder):
                    with self.assertRaises(ValueError):
                        replace(self.config, **{name: folder}).validate()

    def test_cache_and_attempt_cannot_overlap_even_through_dotdot(self):
        cases = [replace(self.config, work=self.config.cache),
                 replace(self.config, work=self.config.cache / 'work'),
                 replace(self.config, cache=self.config.work / 'cache'),
                 replace(self.config, work=self.base / 'alias' / '..' / 'cache' / 'nested')]
        for config in cases:
            with self.subTest(cache=config.cache, work=config.work):
                with self.assertRaises(ValueError):
                    config.validate()

    def test_report_destination_cannot_escape_validation_by_dotdot(self):
        report = self.root / 'dist' / 'validation' / '..' / '..' / 'elsewhere' / 'local-ai-smoke.json'
        with self.assertRaises(ValueError):
            replace(self.config, report=report).validate()

    def test_only_exact_build_executable_and_report_name_are_accepted(self):
        other = self.executable.with_name('Other.exe')
        other.write_bytes(b'inert')
        for config in (replace(self.config, executable=other),
                       replace(self.config, report=self.config.report.with_name('other.json')),
                       replace(self.config, report=self.base / 'local-ai-smoke.json')):
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    config.validate()

    def test_all_stale_evidence_refuses_retry_before_any_network_or_process(self):
        for index, destination in enumerate(('report', 'screenshot', 'controller', 'marker', 'work')):
            config = self.new_config('stale-' + str(index))
            path = {'report': config.report, 'screenshot': config.report.with_suffix('.png'),
                    'controller': config.controller_report, 'marker': config.work / 'attempt.json',
                    'work': config.work / 'prior-failure.txt'}[destination]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'KEEP PRIOR EVIDENCE')
            with self.subTest(destination=destination), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'supervise') as supervisor, patch.object(ci, 'download') as download:
                self.assertEqual(ci.main(self.argv(config)), 1)
                supervisor.assert_not_called()
                download.assert_not_called()
                self.assertEqual(path.read_bytes(), b'KEEP PRIOR EVIDENCE')
                if destination != 'marker':
                    self.assertFalse((config.work / 'attempt.json').exists())

    def test_platform_refusal_before_attempt_or_worker(self):
        with patch.object(ci.sys, 'platform', 'linux'), patch.object(ci, 'supervise') as supervisor:
            self.assertEqual(ci.main(self.argv()), 1)
        supervisor.assert_not_called()
        self.assertFalse(self.config.work.exists())


class ReportTests(CIFixture):
    def test_complete_evidence_matches_permanent_real_fixture_receipt_and_valid_png(self):
        value = self.complete_evidence()
        ledger = self.config.attempt / 'control-v1' / 'local-ai-v1.sqlite3'
        before = ledger.read_bytes()
        proof = ci.validate_result(self.config, 0)
        self.assertEqual(proof['response_hash'], value['probe']['response_hash'])
        self.assertEqual(proof['candidate_hash'], value['probe']['candidate_hash'])
        self.assertEqual(proof['reserved_tokens'], value['probe']['usage']['tokens'])
        self.assertEqual(proof['model_calls'], 1)
        self.assertEqual(proof['screenshot'], {'width': 640, 'height': 360,
            'sha256': hashlib.sha256(self.config.report.with_suffix('.png').read_bytes()).hexdigest()})
        self.assertEqual(ledger.read_bytes(), before, 'Validation must open the durable receipt read-only')

    def test_nonzero_frozen_exit_refuses_otherwise_valid_evidence(self):
        self.complete_evidence()
        for code in (1, -1, 259):
            with self.subTest(code=code), self.assertRaises(ValueError):
                ci.validate_result(self.config, code)

    def test_missing_or_wrong_top_level_semantics_always_fail_closed(self):
        value = self.complete_evidence()
        required = ['status', 'frozen', 'platform', 'profile', 'manifest_sha256', 'model_calls',
                    'cleanup_verified', 'external_api_spend', 'paid_fallback', 'research_evaluations',
                    'oos_or_holdout_access', 'real_model_status', 'clean_windows_client_status',
                    'native_window_screenshot_saved', 'model_sha256', 'runtime_sha256',
                    'runtime_members_verified', 'licenses_verified', 'application_vc_dependencies_verified']
        for key in required:
            for replacement in ('missing', None, []):
                candidate = copy.deepcopy(value)
                if replacement == 'missing':
                    del candidate[key]
                else:
                    candidate[key] = replacement
                with self.subTest(key=key, replacement=replacement):
                    self.write_report(candidate)
                    with self.assertRaises(ValueError):
                        ci.validate_result(self.config, 0)
        for key, replacement in (('model_calls', True), ('frozen', 1), ('cleanup_verified', 1),
                                 ('research_evaluations', False), ('paid_fallback', 0), ('external_api_spend', 0)):
            candidate = copy.deepcopy(value)
            candidate[key] = replacement
            self.write_report(candidate)
            with self.subTest(key=key, replacement=replacement), self.assertRaises(ValueError):
                ci.validate_result(self.config, 0)

    def test_stage_order_status_and_elapsed_caps_are_part_of_pass_evidence(self):
        value = self.complete_evidence()
        cases = [None, [], value['stages'][:-1], list(reversed(value['stages']))]
        for index in range(3):
            for key, wrong in (('stage', 'fixture_fake'), ('status', 'failed'), ('cap_seconds', 999),
                               ('seconds', -0.1), ('seconds', True), ('seconds', '1'),
                               ('seconds', value['stages'][index]['cap_seconds'] + .001)):
                stages = copy.deepcopy(value['stages'])
                stages[index][key] = wrong
                cases.append(stages)
        for stages in cases:
            candidate = copy.deepcopy(value)
            candidate['stages'] = stages
            self.write_report(candidate)
            with self.subTest(stages=stages), self.assertRaises(ValueError):
                ci.validate_result(self.config, 0)

    def test_owned_identity_and_loaded_dependency_proof_are_required(self):
        value = self.complete_evidence()
        cases = [('owned_server', {}), ('owned_server', {'pid': True, 'created': 456}),
                 ('owned_server', {'pid': 123, 'created': 0}),
                 ('owned_server', {**OWNER, 'adopted': True}), ('loaded_vc_runtime_modules', []),
                 ('loaded_vc_runtime_modules', [{'filename': 'vcruntime140.dll', 'sha256': '0' * 64,
                                                'loaded_from': 'pinned_app_local_runtime'}]),
                 ('loaded_vc_runtime_modules', [{'filename': 'vcruntime140.dll',
                    'sha256': self.spec['support_dlls']['vcruntime140.dll']['sha256'], 'loaded_from': 'system32'}])]
        for key, wrong in cases:
            candidate = copy.deepcopy(value)
            candidate[key] = wrong
            self.write_report(candidate)
            with self.subTest(key=key, wrong=wrong), self.assertRaises(ValueError):
                ci.validate_result(self.config, 0)

    def test_probe_must_be_actual_single_schema_receipt_with_canonical_hashes(self):
        value = self.complete_evidence()
        cases = [('status', 'passed'), ('real_model_status', 'verified'), ('research_evaluations', 1),
                 ('research_evaluations', False), ('response_hash', 'a' * 63), ('response_hash', 'G' * 64),
                 ('candidate_hash', 'A' * 64), ('candidate_hash', None),
                 ('usage', {'calls': True, 'tokens': value['probe']['usage']['tokens'], 'max_calls': 100, 'max_tokens': 1000000}),
                 ('usage', {'calls': 1, 'tokens': value['probe']['usage']['tokens'] + 1, 'max_calls': 100, 'max_tokens': 1000000})]
        for key, wrong in cases:
            candidate = copy.deepcopy(value)
            candidate['probe'][key] = wrong
            self.write_report(candidate)
            with self.subTest(key=key, wrong=wrong), self.assertRaises(ValueError):
                ci.validate_result(self.config, 0)

    def test_durable_ledger_mismatch_is_not_replaced_by_report_claims(self):
        edits = ["UPDATE budget SET calls=0", "UPDATE budget SET calls=2", "UPDATE budget SET tokens=0",
                 "UPDATE budget SET tokens=1000001", "UPDATE budget SET spend='0.01'",
                 "INSERT INTO budget SELECT * FROM budget", "DELETE FROM budget", "DELETE FROM calls",
                 "UPDATE calls SET sequence=2", "UPDATE calls SET status='failed_or_interrupted'",
                 "UPDATE calls SET response_hash='" + '0' * 64 + "'", "UPDATE calls SET reserved_tokens=1",
                 "UPDATE calls SET reserved_spend='0.01'",
                 "INSERT INTO calls SELECT 2,request_hash,status,response_hash,reserved_tokens,reserved_spend FROM calls"]
        for index, sql in enumerate(edits):
            config = self.new_config('ledger-' + str(index))
            self.complete_evidence(config)
            self.mutate_db(sql, config)
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                ci.validate_result(config, 0)

    def test_missing_ledger_cannot_be_created_as_validation_side_effect(self):
        self.complete_evidence()
        ledger = self.config.attempt / 'control-v1' / 'local-ai-v1.sqlite3'
        ledger.unlink()
        with self.assertRaises(local_ai.LocalAIError):
            ci.validate_result(self.config, 0)
        self.assertFalse(ledger.exists())

    def test_json_rejects_duplicates_nonfinite_oversize_and_nonobjects(self):
        path = self.base / 'report.json'
        for raw in ('{"status":"passed","status":"failed"}', '{"n": NaN}', '{"n": Infinity}',
                    '{"n": -Infinity}', '[]', 'true', '0', 'null', ' ' * (ci.MAX_REPORT_BYTES + 1)):
            with self.subTest(raw=raw[:60]):
                path.write_text(raw, encoding='utf-8')
                with self.assertRaises(ValueError):
                    ci.read_json(path)

    def test_original_probe_contract_still_1024_tokens_120_seconds_single_call(self):
        probe, transport = self.fixture_probe()
        endpoint, request, timeout = transport.call_args.args
        self.assertEqual(endpoint, local_ai.ENDPOINT)
        self.assertEqual(timeout, 120)
        self.assertEqual(request['max_tokens'], 1024)
        self.assertEqual(request['response_format']['type'], 'json_schema')
        self.assertEqual(request['model'], local_ai.MODEL)
        context = json.loads(request['messages'][-1]['content'])
        self.assertEqual(context['task'], 'technical_schema_probe')
        self.assertEqual(context['training'], {'bar_count': 240})
        self.assertEqual(set(context), {'family', 'task', 'training', 'instruction', 'output_contract'})
        self.assertEqual(probe['usage']['calls'], 1)
        self.assertEqual(probe['usage']['max_calls'], 100)
        self.assertEqual(probe['usage']['max_tokens'], 1000000)
        self.assertEqual(probe['research_evaluations'], 0)
        self.assertEqual(probe['real_model_status'], 'not_verified')


class PNGTests(CIFixture):
    def test_png_is_decodable_not_just_existing_file(self):
        path = self.base / 'capture.png'
        path.write_bytes(png())
        self.assertEqual(ci.verify_png(path)['width'], 640)
        cases = [b'not an image' * 20, b'\x89PNG\r\n\x1a\n' + b'x' * 100,
                 png()[:-3], png() + b'extra', png(width=639), png(height=359),
                 png(image_data=b'this is not a zlib stream'), png(image_data=zlib.compress(b'\0')),
                 png(image_data=zlib.compress((b'\x05' + b'\0' * (640 * 3)) * 360)),
                 png(header=struct.pack('>IIBBBBB', 640, 360, 7, 2, 0, 0, 0)),
                 png(header=struct.pack('>IIBBBBB', 640, 360, 8, 7, 0, 0, 0))]
        broken_crc = bytearray(png())
        broken_crc[29] ^= 1
        cases.append(bytes(broken_crc))
        for index, raw in enumerate(cases):
            path.write_bytes(raw)
            with self.subTest(case=index), self.assertRaises((ValueError, zlib.error)):
                ci.verify_png(path)

    def test_screenshot_missing_or_fake_refuses_otherwise_valid_report(self):
        self.complete_evidence()
        screenshot = self.config.report.with_suffix('.png')
        screenshot.unlink()
        with self.assertRaises(local_ai.LocalAIError):
            ci.validate_result(self.config, 0)
        screenshot.write_bytes(b'fake screenshot' * 20)
        with self.assertRaises(ValueError):
            ci.validate_result(self.config, 0)


class PhaseTests(CIFixture):
    def test_frozen_argv_is_fixed_no_shell_and_no_probe_contract_overrides(self):
        self.cache_files()
        process = Mock()
        process.wait.return_value = 0
        expected = {'proof': 'inert'}
        with patch.object(ci.subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), \
             patch.object(ci.subprocess, 'Popen', return_value=process) as spawn, \
             patch.object(ci, 'validate_result', return_value=expected) as validate:
            self.assertEqual(ci.frozen_phase(self.config), expected)
        command = spawn.call_args.args[0]
        self.assertEqual(command, [str(self.config.executable), '--local-ai-smoke', str(self.config.report),
            '--local-ai-runtime-archive', str(self.config.cache / 'runtime.zip'),
            '--local-ai-model', str(self.config.cache / 'model.gguf'), '--local-ai-root', str(self.config.attempt)])
        self.assertIs(spawn.call_args.kwargs['shell'], False)
        self.assertEqual(spawn.call_args.kwargs['cwd'], str(self.root))
        self.assertEqual(spawn.call_args.kwargs['creationflags'], 0x08000000)
        for stream in ('stdin', 'stdout', 'stderr'):
            self.assertEqual(spawn.call_args.kwargs[stream], ci.subprocess.DEVNULL)
        process.wait.assert_called_once_with()
        validate.assert_called_once_with(self.config, 0)

    def test_corrupt_cache_fails_before_frozen_process_start(self):
        self.cache_files()
        (self.config.cache / 'model.gguf').write_bytes(b'bad')
        with patch.object(ci.subprocess, 'Popen') as spawn:
            with self.assertRaises(local_ai.LocalAIError):
                ci.frozen_phase(self.config)
        spawn.assert_not_called()

    def test_worker_argv_uses_same_python_exact_driver_and_explicit_paths(self):
        for phase in ('download', 'probe'):
            command = ci.child_command(self.config, phase)
            self.assertIsInstance(command, list)
            self.assertEqual(command[:4], [sys.executable, str(ROOT / 'packaging/validate_local_ai.py'), '--internal-phase', phase])
            self.assertEqual(command[4:], self.argv())

    def test_parent_caps_are_predeclared_and_original_probe_budget_unchanged(self):
        self.assertEqual(ci.DOWNLOAD_SECONDS, 300)
        self.assertEqual(ci.FROZEN_SECONDS, 660)
        self.assertEqual(ci.CLEANUP_SECONDS, 10)

    def test_timeout_exit_or_cleanup_failure_stops_before_next_phase_and_keeps_attempt(self):
        outcomes = [{'exit_code': None, 'timed_out': True, 'cleanup_verified': True, 'seconds': 301},
                    {'exit_code': 7, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1},
                    {'exit_code': 0, 'timed_out': False, 'cleanup_verified': False, 'seconds': 1},
                    {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 310.001}]
        for index, outcome in enumerate(outcomes):
            config = self.new_config('stop-' + str(index))
            with self.subTest(outcome=outcome), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'supervise', return_value=outcome) as supervise, \
                 patch.object(ci, 'validate_result') as validate:
                self.assertEqual(ci.run(config), 1)
                self.assertEqual(supervise.call_count, 1)
                self.assertEqual(supervise.call_args.args[1], 300)
                validate.assert_not_called()
                report = ci.read_json(config.controller_report)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(set(report['phases']), {'download'})
                marker = ci.read_json(config.work / 'attempt.json')
                self.assertIs(marker['retry'], False)
                with self.assertRaises(ValueError):
                    ci.run(config)
                self.assertEqual(supervise.call_count, 1, 'Stale evidence may not trigger a second attempt')

    def test_worker_missing_or_failed_evidence_stops_next_phase(self):
        for index, contents in enumerate((None, {'status': 'failed'}, {'status': 'passed'})):
            config = self.new_config('evidence-' + str(index))
            def supervise(command, seconds):
                if contents is not None:
                    (config.work / 'download-phase.json').write_text(json.dumps(contents), encoding='utf-8')
                return {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1.0}
            with self.subTest(contents=contents), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'supervise', side_effect=supervise) as supervisor:
                self.assertEqual(ci.run(config), 1)
                self.assertEqual(supervisor.call_count, 1)
                self.assertEqual(ci.read_json(config.controller_report)['status'], 'failed')

    def test_success_requires_both_owned_phases_and_independent_final_evidence(self):
        order = []
        def supervise(command, seconds):
            phase = command[command.index('--internal-phase') + 1]
            order.append((phase, seconds))
            evidence = {'cache': 'inert fixture'}
            if phase == 'probe':
                self.complete_evidence()
                evidence = ci.validate_result(self.config, 0)
            (self.config.work / (phase + '-phase.json')).write_text(json.dumps({'status': 'passed', 'evidence': evidence}), encoding='utf-8')
            return {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1.0}
        with patch.object(ci.sys, 'platform', 'win32'), patch.object(ci, 'supervise', side_effect=supervise):
            self.assertEqual(ci.run(self.config), 0)
        report = ci.read_json(self.config.controller_report)
        self.assertEqual(order, [('download', 300), ('probe', 660)])
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(report['proof']['model_calls'], 1)
        self.assertEqual(report['frozen_executable_sha256'], hashlib.sha256(self.executable.read_bytes()).hexdigest())
        self.assertIs(report['retry'], False)

    def test_forged_phase_success_without_native_evidence_refuses_pass(self):
        def supervise(command, seconds):
            phase = command[command.index('--internal-phase') + 1]
            (self.config.work / (phase + '-phase.json')).write_text(json.dumps({'status': 'passed', 'evidence': {'status': 'passed'}}), encoding='utf-8')
            return {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1.0}
        with patch.object(ci.sys, 'platform', 'win32'), patch.object(ci, 'supervise', side_effect=supervise):
            self.assertEqual(ci.run(self.config), 1)
        self.assertEqual(ci.read_json(self.config.controller_report)['status'], 'failed')

    def test_internal_worker_without_parent_marker_cannot_download_or_probe(self):
        self.config.work.mkdir()
        with patch.object(ci.sys, 'platform', 'win32'), patch.object(ci, 'download_phase') as download, \
             patch.object(ci, 'frozen_phase') as probe:
            self.assertEqual(ci.main(self.argv(phase='download')), 1)
            self.assertEqual(ci.main(self.argv(phase='probe')), 1)
        download.assert_not_called()
        probe.assert_not_called()


    def test_probe_phase_failure_has_no_retry_or_final_pass(self):
        for index, outcome in enumerate((
            {'exit_code': None, 'timed_out': True, 'cleanup_verified': True, 'seconds': 665},
            {'exit_code': 1, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1},
            {'exit_code': 0, 'timed_out': False, 'cleanup_verified': False, 'seconds': 1},
            {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 670.001},
        )):
            config = self.new_config('probe-failure-' + str(index))
            def supervise(command, seconds):
                phase = command[command.index('--internal-phase') + 1]
                if phase == 'download':
                    (config.work / 'download-phase.json').write_text(
                        json.dumps({'status': 'passed', 'evidence': {}}), encoding='utf-8')
                    return {'exit_code': 0, 'timed_out': False, 'cleanup_verified': True, 'seconds': 1}
                return outcome
            with self.subTest(outcome=outcome), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'supervise', side_effect=supervise) as supervisor, \
                 patch.object(ci, 'validate_result') as validate:
                self.assertEqual(ci.run(config), 1)
                self.assertEqual(supervisor.call_count, 2)
                validate.assert_not_called()
                self.assertEqual(ci.read_json(config.controller_report)['status'], 'failed')

    def worker_marker(self, config):
        config.work.mkdir(parents=True, exist_ok=True)
        marker = {'profile': ci.PROFILE, 'manifest_sha256': ci.MANIFEST_SHA256,
                  'download_cap_seconds': ci.DOWNLOAD_SECONDS, 'frozen_cap_seconds': ci.FROZEN_SECONDS,
                  'cleanup_cap_seconds_per_phase': ci.CLEANUP_SECONDS, 'retry': False}
        (config.work / 'attempt.json').write_text(json.dumps(marker), encoding='utf-8')

    def test_internal_phase_is_once_only_after_success_or_failed_download(self):
        for index, fail in enumerate((False, True)):
            config = self.new_config('once-' + str(index))
            self.worker_marker(config)
            with self.subTest(fail=fail), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'download_phase', side_effect=RuntimeError('inert failure') if fail else None,
                              return_value={'fixture': True}) as download:
                self.assertEqual(ci.main(self.argv(config, phase='download')), 1 if fail else 0)
                phase_report = config.work / 'download-phase.json'
                before = phase_report.read_bytes()
                self.assertEqual(ci.main(self.argv(config, phase='download')), 1)
                download.assert_called_once_with(config)
                self.assertEqual(phase_report.read_bytes(), before)
                self.assertTrue((config.work / 'download-started.json').is_file())

    def test_claimed_interrupted_worker_cannot_retry_network_or_model(self):
        for phase in ('download', 'probe'):
            config = self.new_config('claimed-' + phase)
            self.worker_marker(config)
            claim = config.work / (phase + '-started.json')
            claim.write_text(json.dumps({'phase': phase, 'retry': False}), encoding='utf-8')
            before = claim.read_bytes()
            with self.subTest(phase=phase), patch.object(ci.sys, 'platform', 'win32'), \
                 patch.object(ci, 'download_phase') as download, patch.object(ci, 'frozen_phase') as probe:
                self.assertEqual(ci.main(self.argv(config, phase=phase)), 1)
                download.assert_not_called()
                probe.assert_not_called()
                self.assertEqual(claim.read_bytes(), before)
                self.assertFalse((config.work / (phase + '-phase.json')).exists())

    def test_internal_phase_revalidates_external_paths_and_manifest_marker(self):
        self.worker_marker(self.config)
        marker = self.config.work / 'attempt.json'
        marker.write_text(json.dumps({'manifest_sha256': '0' * 64}), encoding='utf-8')
        with patch.object(ci.sys, 'platform', 'win32'), patch.object(ci, 'download_phase') as download:
            self.assertEqual(ci.main(self.argv(phase='download')), 1)
            self.assertEqual(ci.main(self.argv(replace(self.config, cache=self.root / 'dist' / 'cache'), phase='download')), 1)
        download.assert_not_called()
        self.assertFalse((self.config.work / 'download-started.json').exists())


class FailureDiagnosticTests(CIFixture):
    def http_error(self, code=403):
        return urllib.error.HTTPError('https://github.com/private?token=SECRET_URL', code,
                                      'SECRET_EXCEPTION', {'Authorization':'SECRET_HEADER'}, None)

    def test_real_download_wrapper_keeps_runtime_http_status_without_secrets(self):
        opener=Mock();opener.open.side_effect=self.http_error()
        with patch.object(local_ai.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(local_ai.LocalAIError) as caught:ci.download_phase(self.config)
        self.assertEqual(ci.failure_detail(caught.exception,'worker_preflight'),
            {'stage':'runtime_download','category':'local_ai_network','http_status':403})
        opener.open.assert_called_once()
        self.assertFalse((self.config.cache/'model.gguf').exists())

    def test_model_failure_is_distinct_after_verified_runtime_without_retry(self):
        opener=Mock();opener.open.side_effect=[DownloadResponse(self.raw['runtime'],self.spec['runtime']['url']),
                                              self.http_error(429)]
        with patch.object(local_ai.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(local_ai.LocalAIError) as caught:ci.download_phase(self.config)
        self.assertEqual(ci.failure_detail(caught.exception,'worker_preflight'),
            {'stage':'model_download','category':'local_ai_network','http_status':429})
        self.assertEqual(opener.open.call_count,2)
        self.assertEqual((self.config.cache/'runtime.zip').read_bytes(),self.raw['runtime'])

    def test_manifest_and_cache_failures_are_not_labelled_http(self):
        with patch.object(ci,'manifest',side_effect=local_ai.LocalAIError('artifact')), \
             patch.object(ci,'download') as download:
            with self.assertRaises(local_ai.LocalAIError) as caught:ci.download_phase(self.config)
        self.assertEqual(ci.failure_detail(caught.exception,'worker_preflight'),
            {'stage':'manifest','category':'local_ai_artifact'})
        download.assert_not_called()
        with patch.object(Path,'mkdir',side_effect=PermissionError('SECRET_PATH')), \
             patch.object(ci,'download') as download:
            with self.assertRaises(PermissionError) as caught:ci.download_phase(self.config)
        self.assertEqual(ci.failure_detail(caught.exception,'worker_preflight'),
            {'stage':'cache_prepare','category':'os_error'})
        download.assert_not_called()

    def test_failed_actual_worker_report_survives_nonzero_exit_gate(self):
        opener=Mock();opener.open.side_effect=self.http_error()
        def supervise(command,seconds):
            self.assertEqual(seconds,300)
            code=ci.main(command[2:])
            return {'exit_code':code,'timed_out':False,'cleanup_verified':True,'seconds':.616}
        with patch.object(ci.sys,'platform','win32'), \
             patch.object(local_ai.ssl,'create_default_context',return_value=Mock()), \
             patch.object(local_ai.urllib.request,'build_opener',return_value=opener), \
             patch.object(ci,'supervise',side_effect=supervise) as supervisor, \
             patch.object(ci,'frozen_phase') as frozen,patch.object(ci,'validate_result') as validate:
            self.assertEqual(ci.run(self.config),1)
        report=ci.read_json(self.config.controller_report)
        self.assertEqual(report['status'],'failed')
        self.assertEqual(report['phases']['download']['failure'],
            {'stage':'runtime_download','category':'local_ai_network','http_status':403})
        self.assertEqual(report['phases']['download']['phase_report'],'failed')
        self.assertEqual(set(report['phases']),{'download'})
        supervisor.assert_called_once();opener.open.assert_called_once()
        frozen.assert_not_called();validate.assert_not_called()
        text=self.config.controller_report.read_text(encoding='utf-8')
        self.assertNotIn('SECRET',text);self.assertNotIn('https://',text)
        self.assertTrue((self.config.work/'download-started.json').is_file())
        with patch.object(ci.sys,'platform','win32'),patch.object(ci,'supervise') as supervisor:
            with self.assertRaises(ValueError):ci.run(self.config)
        supervisor.assert_not_called()

    def test_worker_diagnostic_drops_raw_text_headers_urls_and_extra_keys(self):
        diagnostic=ci.worker_diagnostic({'status':'failed','exception':'SECRET_EXCEPTION',
            'failure':{'stage':'model_download','category':'local_ai_network','http_status':503,
                       'url':'SECRET_URL','headers':{'Authorization':'SECRET_TOKEN'}}})
        self.assertEqual(diagnostic,{'phase_report':'failed','failure':
            {'stage':'model_download','category':'local_ai_network','http_status':503}})
        self.assertNotIn('SECRET',json.dumps(diagnostic))

    def test_malformed_or_unallowlisted_diagnostic_is_not_published(self):
        failures=[None,[],{'stage':[],'category':'exception'},
            {'stage':'SECRET_URL','category':'exception'},
            {'stage':'manifest','category':'SECRET_EXCEPTION'},
            *({'stage':'runtime_download','category':'http_error','http_status':code}
              for code in (True,'403',99,600))]
        for failure in failures:
            with self.subTest(failure=failure):
                self.assertEqual(ci.worker_diagnostic({'status':'failed','failure':failure}),
                                 {'phase_report':'invalid'})

    def test_unverified_cleanup_never_reads_worker_report(self):
        outcome={'exit_code':1,'timed_out':False,'cleanup_verified':False,'seconds':1}
        with patch.object(ci.sys,'platform','win32'),patch.object(ci,'supervise',return_value=outcome), \
             patch.object(ci,'read_json',side_effect=AssertionError('Worker may still be writing')) as read:
            self.assertEqual(ci.run(self.config),1)
        read.assert_not_called()
        report=ci.read_json(self.config.controller_report)
        self.assertEqual(report['phases']['download']['phase_report'],'not_read_unverified_cleanup')

    def test_exception_context_cycle_is_bounded_and_message_is_never_inspected(self):
        error=RuntimeError('SECRET_MESSAGE');error.__context__=error
        self.assertEqual(ci.failure_detail(error,'phase_report'),
                         {'stage':'phase_report','category':'runtime_error'})


class APIFunction:
    """ctypes-style callable exposing signatures, backed solely by Python fixtures."""
    def __init__(self, kernel, name, implementation):
        self.kernel, self.name, self.implementation = kernel, name, implementation
        self.argtypes = self.restype = None

    def __call__(self, *args):
        self.kernel.events.append((self.name, args))
        return self.implementation(*args)


class KernelFixture:
    def __init__(self, *, wait=(0, 0), exit_code=0, assignment=True, cleanup=True, resume=True,
                 create=True, terminate=True):
        # Values exceed DWORD on x64, detecting accidental HANDLE truncation assumptions.
        self.process = (1 << 40) + 17 if ctypes.sizeof(ctypes.c_void_p) == 8 else 101
        self.thread = self.process + 1
        self.job = self.process + 2
        self.opened = self.process + 3
        self.events = []
        self.waits = iter(wait)
        def created(*args):
            if create:
                info = args[-1]._obj
                info.process, info.thread, info.pid, info.tid = self.process, self.thread, 234, 235
            return create
        def exit_status(handle, code):
            code._obj.value = exit_code
            return True
        def queried(handle, kind, info, size, returned):
            info._obj.ActiveProcesses = 0
            return cleanup
        implementations = {
            'CreateProcessW': created, 'ResumeThread': lambda handle: 1 if resume else 0xffffffff,
            'WaitForSingleObject': lambda handle, milliseconds: next(self.waits),
            'GetExitCodeProcess': exit_status, 'TerminateProcess': lambda *args: terminate,
            'CloseHandle': lambda *args: True, 'CreateJobObjectW': lambda *args: self.job,
            'SetInformationJobObject': lambda *args: True, 'OpenProcess': lambda *args: self.opened,
            'AssignProcessToJobObject': lambda *args: assignment,
            'TerminateJobObject': lambda *args: cleanup, 'QueryInformationJobObject': queried,
        }
        for name, implementation in implementations.items():
            setattr(self, name, APIFunction(self, name, implementation))

    def names(self):
        return [name for name, args in self.events]

    def args(self, name):
        return [args for found, args in self.events if found == name]


class WindowsSupervisorTests(CIFixture):
    def supervise(self, kernel, seconds=300):
        with patch.object(ci.sys, 'platform', 'win32'), \
             patch.object(ctypes, 'WinDLL', return_value=kernel, create=True), \
             patch.object(ci.time, 'monotonic', return_value=100.0):
            return ci.supervise([sys.executable, 'inert worker.py', '--fixture'], seconds)

    def test_suspend_assign_job_then_resume_and_pointer_width_handles(self):
        from ctypes import wintypes as w
        kernel = KernelFixture()
        result = self.supervise(kernel)
        names = kernel.names()
        self.assertLess(names.index('CreateProcessW'), names.index('AssignProcessToJobObject'))
        self.assertLess(names.index('AssignProcessToJobObject'), names.index('ResumeThread'))
        self.assertLess(names.index('TerminateJobObject'), names.index('QueryInformationJobObject'))
        create = kernel.args('CreateProcessW')[0]
        self.assertEqual(create[0], sys.executable)
        self.assertIn('"inert worker.py"', create[1].value)
        self.assertFalse(create[4], 'Handles must not be inherited accidentally')
        self.assertTrue(create[5] & 0x4, 'Worker must start suspended')
        self.assertTrue(create[5] & 0x08000000, 'No console window')
        limits = kernel.args('SetInformationJobObject')[0][2]._obj
        self.assertTrue(limits.BasicLimitInformation.LimitFlags & 0x2000)
        self.assertEqual(kernel.args('AssignProcessToJobObject'), [(kernel.job, kernel.opened)])
        self.assertEqual(kernel.args('ResumeThread'), [(kernel.thread,)])
        self.assertEqual(kernel.args('WaitForSingleObject'), [(kernel.process, 300000), (kernel.process, 3000)])
        self.assertEqual(kernel.CreateJobObjectW.restype, w.HANDLE)
        self.assertEqual(kernel.OpenProcess.restype, w.HANDLE)
        for function in ('ResumeThread', 'WaitForSingleObject', 'GetExitCodeProcess',
                         'TerminateProcess', 'CloseHandle', 'AssignProcessToJobObject'):
            self.assertEqual(getattr(kernel, function).argtypes[0], w.HANDLE)
        process_fields = dict(kernel.CreateProcessW.argtypes[-1]._type_._fields_)
        self.assertEqual(ctypes.sizeof(process_fields['process']), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ctypes.sizeof(process_fields['thread']), ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['timed_out'])
        self.assertTrue(result['cleanup_verified'])
        self.assertEqual({args[0] for args in kernel.args('CloseHandle')},
                         {kernel.opened, kernel.job, kernel.thread, kernel.process})

    def test_timeout_stops_and_joins_owned_tree_before_closing_handles(self):
        kernel = KernelFixture(wait=(258, 0))
        result = self.supervise(kernel, 660)
        self.assertTrue(result['timed_out'])
        self.assertIsNone(result['exit_code'])
        self.assertTrue(result['cleanup_verified'])
        names = kernel.names()
        self.assertLess(names.index('TerminateJobObject'), names.index('QueryInformationJobObject'))
        self.assertNotIn('GetExitCodeProcess', names)
        self.assertEqual(kernel.args('TerminateJobObject'), [(kernel.job, 1)])
        self.assertEqual(kernel.args('WaitForSingleObject'), [(kernel.process, 660000), (kernel.process, 3000)])
        self.assertNotIn('TerminateProcess', names, 'Assigned trees must use the owned Job Object')

    def test_assignment_failure_kills_still_suspended_child_and_never_resumes(self):
        kernel = KernelFixture(assignment=False, wait=(0,))
        result = self.supervise(kernel)
        self.assertNotIn('ResumeThread', kernel.names())
        self.assertNotIn('GetExitCodeProcess', kernel.names())
        self.assertEqual(kernel.args('TerminateProcess'), [(kernel.process, 1)])
        self.assertTrue(result['cleanup_verified'])
        self.assertIsNone(result['exit_code'])
        self.assertIn('error_type', result)
        self.assertEqual(kernel.args('WaitForSingleObject'), [(kernel.process, 3000)])

    def test_resume_failure_still_stops_and_joins_job(self):
        kernel = KernelFixture(resume=False, wait=(0,))
        result = self.supervise(kernel)
        self.assertIsNone(result['exit_code'])
        self.assertIn('error_type', result)
        self.assertTrue(result['cleanup_verified'])
        self.assertIn('TerminateJobObject', kernel.names())
        self.assertIn('QueryInformationJobObject', kernel.names())

    def test_cleanup_failure_cannot_be_success_even_after_zero_exit(self):
        kernel = KernelFixture(cleanup=False, wait=(0,))
        result = self.supervise(kernel)
        self.assertEqual(result['exit_code'], 0)
        self.assertFalse(result['cleanup_verified'])
        self.assertIn('cleanup_error_type', result)
        closed = {args[0] for args in kernel.args('CloseHandle')}
        self.assertTrue({kernel.job, kernel.process, kernel.thread} <= closed)
        with patch.object(ci.sys, 'platform', 'win32'), patch.object(ci, 'supervise', return_value=result) as supervised:
            self.assertEqual(ci.run(self.config), 1)
        self.assertEqual(supervised.call_count, 1)
        self.assertEqual(ci.read_json(self.config.controller_report)['status'], 'failed')

    def test_direct_child_not_joined_or_failed_termination_is_not_cleanup_proof(self):
        for kernel in (KernelFixture(wait=(0, 258)), KernelFixture(assignment=False, terminate=False, wait=())):
            with self.subTest(events=kernel.events):
                result = self.supervise(kernel)
                self.assertFalse(result['cleanup_verified'])
                self.assertIn('cleanup_error_type', result)

    def test_native_create_failure_does_not_resume_or_adopt_any_process(self):
        kernel = KernelFixture(create=False, wait=())
        result = self.supervise(kernel)
        self.assertIsNone(result['exit_code'])
        self.assertIn('error_type', result)
        self.assertEqual(kernel.names(), ['CreateProcessW'])


if __name__ == '__main__':
    unittest.main()
