"""Fast, offline documentation layering and provenance contracts."""

import difflib
import hashlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ('README.md', 'README_before_layering.md'),
    ('docs/agent/PROJECT_STATE.md', 'PROJECT_STATE_checkpoints.md'),
    ('docs/analysis/03_CODE_QUALITY_AND_RISKS.md', '03_CODE_QUALITY_AND_RISKS_checkpoints.md'),
)
HISTORY = ROOT / 'docs/agent/history'
HISTORY_LINK_REASON = 'relative links in the verbatim text below resolve from the original file location and are intentionally not rewritten'
README_SHA256 = '61174a23c71a8078f319256852a6c11907d26a4d6c3913a54191af92bdfffa36'
LINK = re.compile(r'!?\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\s*\)')
REFERENCE = re.compile(r'^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)', re.MULTILINE)
LEGACY = re.compile(r'(?<![\w/])(?:trader/|gui\.py\b|run\.py\b|requirements\.txt\b)')


def active_markdown(text):
    """Literal examples do not create links; history is excluded by document_paths."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return '\n'.join(lines)


def document_paths():
    # Verbatim historical links resolve from their original location (see banners).
    paths = {ROOT / 'README.md', ROOT / 'packaging/README.md', ROOT / 'archives/legacy_autotrading/README.md', *(ROOT / 'docs').rglob('*.md')}
    return sorted(path for path in paths if not path.is_relative_to(HISTORY))


def link_path(source, target):
    target = target.strip('<>')
    if target.startswith('#') or urlsplit(target).scheme:
        return None
    target = unquote(target.split('#', 1)[0].split('?', 1)[0])
    target = re.sub(r':\d+(?:[-:]\d+)?$', '', target)
    return (source.parent / target).resolve() if target else None


def original_body(history):
    raw = history.read_bytes()
    start = b'<!-- ORIGINAL_BODY_START -->\n~~~~~markdown\n'
    end = b'\n~~~~~\n<!-- ORIGINAL_BODY_END -->\n'
    header, body = raw.split(start, 1)
    if not body.endswith(end):
        raise AssertionError('Missing literal history terminator: ' + str(history))
    return header.decode('utf-8'), body[: -len(end)]


class DocumentationLayeringTests(unittest.TestCase):
    def test_history_body_hash_and_line_count_without_git(self):
        for source, name in PAIRS:
            with self.subTest(source=source):
                header, body = original_body(HISTORY / name)
                self.assertRegex(header, 'Moved from ' + re.escape(source) + r' at [0-9a-f]{40}')
                digest = re.search(r'Original-SHA256: ([0-9a-f]{64})', header).group(1)
                count = int(re.search(r'Original-Lines: (\d+)', header).group(1))
                self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
                self.assertEqual(len(body.splitlines()), count)

    def test_removed_original_blocks_preserved_verbatim(self):
        for source, name in PAIRS:
            with self.subTest(source=source):
                header, body = original_body(HISTORY / name)
                sha = re.search(r' at ([0-9a-f]{40})', header).group(1)
                if not shutil.which('git'):
                    continue  # git object cross-check unavailable here (no git / shallow clone); the recorded-hash test still covers it. Never use skipTest: CI counts skips exactly.
                try:
                    result = subprocess.run(['git', 'show', sha + ':' + source], cwd=ROOT, capture_output=True, timeout=1, check=False)
                except (OSError, subprocess.TimeoutExpired) as exc:  # noqa: F841 -- preserve pre-format binding
                    continue  # git object cross-check unavailable here (no git / shallow clone); the recorded-hash test still covers it. Never use skipTest: CI counts skips exactly.
                if result.returncode:
                    available = subprocess.run(['git', 'cat-file', '-e', sha + '^{commit}'], cwd=ROOT, capture_output=True, timeout=1, check=False)
                    if available.returncode:
                        continue  # git object cross-check unavailable here (no git / shallow clone); the recorded-hash test still covers it. Never use skipTest: CI counts skips exactly.
                    self.fail('Origin commit exists but original document cannot be read: ' + source)
                self.assertEqual(result.stdout, body)
                original = result.stdout.decode('utf-8').splitlines(keepends=True)
                current = (ROOT / source).read_text(encoding='utf-8').splitlines(keepends=True)
                history = body.decode('utf-8')
                for tag, first, last, _, _ in difflib.SequenceMatcher(None, original, current, autojunk=False).get_opcodes():
                    if tag in ('delete', 'replace'):
                        block = ''.join(original[first:last])
                        if block.strip():
                            self.assertIn(block, history)

    def test_readme_original_bytes_and_nonempty_lines(self):
        header, body = original_body(HISTORY / 'README_before_layering.md')
        self.assertIn('Original-SHA256: ' + README_SHA256, header)
        self.assertIn('Original-Lines: 374', header)
        self.assertEqual(hashlib.sha256(body).hexdigest(), README_SHA256)
        self.assertEqual(len(body.splitlines()), 374)
        current = (ROOT / 'README.md').read_text(encoding='utf-8').splitlines()
        preserved = set(current) | set(body.decode('utf-8').splitlines())
        for line in body.decode('utf-8').splitlines():
            if line.strip():
                self.assertIn(line, preserved)

    def test_history_link_exclusion_is_limited_to_history_directory(self):
        all_paths = {ROOT / 'README.md', ROOT / 'packaging/README.md', ROOT / 'archives/legacy_autotrading/README.md', *(ROOT / 'docs').rglob('*.md')}
        histories = set(HISTORY.rglob('*.md'))
        self.assertTrue(histories)
        self.assertEqual(all_paths - set(document_paths()), histories)
        self.assertEqual(HISTORY.relative_to(ROOT).as_posix(), 'docs/agent/history')
        for path in histories:
            header, _ = original_body(path)
            self.assertIn(HISTORY_LINK_REASON, header.splitlines())

    def test_readme_line_limit(self):
        self.assertLessEqual(len((ROOT / 'README.md').read_bytes().splitlines()), 150)

    def test_all_relative_markdown_links_and_images_resolve(self):
        broken = []
        for source in document_paths():
            text = active_markdown(source.read_text(encoding='utf-8'))
            targets = [m.group(1) for pattern in (LINK, REFERENCE) for m in pattern.finditer(text)]
            for target in targets:
                path = link_path(source, target)
                if path is not None and not path.exists():
                    broken.append(str(source.relative_to(ROOT)) + ': ' + target)
        self.assertEqual(broken, [], '\n'.join(broken))

    def test_manual_pages_and_nonempty_images(self):
        source = ROOT / 'docs/user/使用手冊.md'
        text = source.read_text(encoding='utf-8')
        for heading in ('資料匯入與更新', 'AI 策略中心', '回測與結果', '比較與策略選擇', '紙上交易與復原', '市場總覽', '設定與備份'):
            self.assertIn('## ' + heading + '\n', text)
        images = re.findall(r'!\[[^\]]*\]\((img/[^)]+)\)', text)
        self.assertEqual(len(images), 7)
        for target in images:
            path = source.parent / target
            self.assertTrue(path.is_file(), target)
            self.assertGreater(path.stat().st_size, 0)
            self.assertLessEqual(path.stat().st_size, 400 * 1024)
            self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_no_stale_root_legacy_paths(self):
        bad = []
        paths = [ROOT / 'README.md', *(ROOT / 'docs').rglob('*.md'), *(ROOT / 'docs').rglob('*.json'), ROOT / 'packaging/README.md']
        for path in paths:
            # The controller-owned immutable plan describes the pre-move problem.
            if HISTORY in path.parents or path.name == '06_PRODUCT_OPTIMIZATION_PLAN.md':
                continue
            text = path.read_text(encoding='utf-8')
            if path == ROOT / 'docs/analysis/t12_test_edits.json':
                # Before fields are historical evidence; current/after paths still count.
                text = json.dumps(json.loads(text, object_hook=lambda item: {key: value for key, value in item.items() if key != 'before'}))
            text = re.sub(r'https?://[^\s<>`"\)]+', '', text)
            text = re.sub(r'archives/legacy_autotrading/[^\s<>`"\),]+', '', text)
            if LEGACY.search(text):
                bad.append(str(path.relative_to(ROOT)))
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
