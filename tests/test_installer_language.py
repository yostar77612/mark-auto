"""Cheap, offline installer language and unchanged security-contract checks."""
import ast
import hashlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
LANGUAGE = 'packaging/languages/ChineseTraditional.isl'
LANGUAGE_SHA256 = 'ab22b0ebf82969d1c9a7208e0e9f60e5119c0c95b9dacc00eb8e5582c7d3c604'
SOURCE_URL = ('https://raw.githubusercontent.com/jrsoftware/issrc/is-6_4_3/'
              'Files/Languages/Unofficial/ChineseTraditional.isl')
# Captured from git show b6777a86d2bf1167e361de3d52f61aa6f15e7e63:packaging/markauto.iss.
# Byte-identical line bodies; checkout LF/CRLF and source BOM are canonicalized.
SECURITY_LINES = (
    b'AppId={{58788303-95B7-491B-A67A-B1EBA50DA420}',
    br'DefaultDirName={localappdata}\Programs\MarkAuto',
    b'PrivilegesRequired=lowest',
    b'UsePreviousAppDir=no',
    b'CloseApplications=no',
    b'RestartApplications=no',
    br'AppMutex=Local\MarkAuto.Desktop.58788303-95B7-491B-A67A-B1EBA50DA420',
    br'; Deliberately no [UninstallDelete]: %LOCALAPPDATA%\MarkAuto is never removed.',
)
# Pins the WHOLE original script, including uninstall/data handling, except the
# bodies of UI literals below. No variable, condition, flag, path or log is masked.
BASELINE_NON_UI_SHA256 = '89527e67d1e93ab766d363df8217f54935c31df48ea331eee61e1500474043f5'
# English tokens permitted in UI: the immutable product identity only. Pascal
# identifiers (mbError, MB_OK, IDOK), paths and MARKAUTO_* Log keys are not UI.
UI_IDENTIFIER_ALLOWLIST = {'Mark Auto': 'Product and upgrade/shortcut identity'}
UI_CALL = r"((?:RaiseException|SuppressibleMsgBox|MsgBox)\(\s*)'((?:[^']|'')*)'"


def section(source, name):
    match = re.search(r'^\[' + name + r'\]\n(.*?)(?=^\[|\Z)', source, re.M | re.S)
    return match.group(1) if match else ''


class InstallerLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'packaging/markauto.iss').read_text(encoding='utf-8-sig')

    def test_single_language_resolves_from_script_directory(self):
        entries = [line for line in section(self.source, 'Languages').splitlines()
                   if line.strip() and not line.lstrip().startswith(';')]
        self.assertEqual(entries, [
            'Name: "chinesetraditional"; MessagesFile: "languages\\ChineseTraditional.isl"'])
        self.assertNotRegex(self.source, r'(?im)^\s*SourceDir\s*=')
        relative = re.search(r'MessagesFile: "([^"]+)"', entries[0]).group(1)
        resolved = ROOT / 'packaging' / Path(relative.replace('\\', '/'))
        self.assertEqual(resolved, ROOT / LANGUAGE)
        self.assertTrue(resolved.is_file())

    def test_upstream_bytes_and_documented_provenance(self):
        data = (ROOT / LANGUAGE).read_bytes()
        self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(hashlib.sha256(data).hexdigest(), LANGUAGE_SHA256)
        for name in ('README.md', 'THIRD_PARTY_NOTICES.md'):
            notice = (ROOT / 'packaging' / name).read_text(encoding='utf-8')
            for value in (LANGUAGE_SHA256, SOURCE_URL, 'is-6_4_3',
                          'Inno Setup license', 'Enfeng Tsao', 'Samuel Lee'):
                self.assertIn(value, notice, name)
        self.assertIn('packaging/languages/ChineseTraditional.isl -text',
                      (ROOT / '.gitattributes').read_text(encoding='utf-8'))

    def test_all_custom_ui_messages_are_chinese(self):
        messages = [match[1] for match in re.findall(UI_CALL, section(self.source, 'Code'))]
        self.assertEqual(len(messages), 16)  # 14 errors and two refusal dialogs.
        for line in section(self.source, 'CustomMessages').splitlines():
            if line.strip() and not line.lstrip().startswith(';'):
                messages.append(line.split('=', 1)[1])
        for name in ('Run', 'Tasks'):
            messages.extend(re.findall(r'Description: "([^"]+)"', section(self.source, name)))
        for message in messages:
            with self.subTest(message=message):
                self.assertRegex(message, r'[\u4e00-\u9fff]')
                for allowed in UI_IDENTIFIER_ALLOWLIST:
                    message = message.replace(allowed, '')
                # Also catches mixed English/Chinese messages, not just omissions.
                self.assertNotRegex(message, r'[A-Za-z]{2,}')

    def test_security_lines_and_entire_non_message_script_match_head(self):
        lines = self.source.encode('utf-8').splitlines()
        for expected in SECURITY_LINES:
            self.assertEqual(lines.count(expected), 1, expected)
        for name in ('UninstallDelete', 'InstallDelete'):
            self.assertNotRegex(self.source, r'(?m)^\[' + name + r'\]')
        normalized = re.sub(r'^\[Languages\]\n.*?(?=^\[)', '', self.source, flags=re.M | re.S)
        normalized = re.sub(UI_CALL, r"\1'<UI>'", normalized)
        normalized = re.sub(r'Description: "[^"]*"', 'Description: "<UI>"', normalized)
        self.assertEqual(hashlib.sha256(normalized.encode('utf-8')).hexdigest(),
                         BASELINE_NON_UI_SHA256)

    def test_translation_is_build_input_only(self):
        # Evaluate only the real glob comprehension: no manifest generation,
        # filesystem mutation, subprocess, installed metadata or fixture payload.
        source = (ROOT / 'packaging/build_manifest.py').read_text(encoding='utf-8')
        main = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == 'main')
        assignment = next(node for node in main.body if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'inputs' for t in node.targets))
        patterns = assignment.value.generators[0].iter
        names = {p.relative_to(ROOT).as_posix() for pattern in ast.literal_eval(patterns)
                 for p in ROOT.glob(pattern) if p.is_file()}
        self.assertIn(LANGUAGE, names)
        spec = (ROOT / 'packaging/markauto.spec').read_text(encoding='utf-8')
        self.assertNotIn('ChineseTraditional.isl', spec)
        self.assertNotIn('packaging/languages', spec)
        self.assertNotIn("'languages'", spec)
        self.assertNotIn('ChineseTraditional.isl', section(self.source, 'Files'))


if __name__ == '__main__':
    unittest.main()
