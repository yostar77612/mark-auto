"""One explicitly consented question answered by the Claude Code installed on this computer.

Claude Code is run headless with every tool switched off, no saved session, no user or project settings and
an empty working directory, so it can only turn the supplied text into text. The prompt travels on stdin; no
credential is read, stored or passed by this program: the user's Claude Code uses its own sign-in.
"""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

MODELS = ('haiku', 'sonnet', 'opus')


def _refusal():
    # Same fixed shape as the agent tools' refusal; the UI owns all human text and nothing here is echoed.
    return {'ok': False, 'error': {'code': 'agent_tool_refused', 'params': {}}}


INSTRUCTIONS = 'You are an unverified read-only research assistant. Interpret only the supplied text. Never operate, execute code, or request protected data.'
TIMEOUT_SECONDS = 90
MAX_PROMPT_BYTES = 4096
MAX_TEXT_BYTES = 8192
MAX_OUTPUT_BYTES = 1024 * 1024
UNAVAILABLE = {'ok': False, 'code': 'claude_unavailable'}
LOGIN_REQUIRED = {'ok': False, 'code': 'claude_login_required'}


def find_claude(which=shutil.which):
    found = which('claude')
    return found if found and Path(found).is_file() else None


def command(executable, model):
    return [
        executable,
        '-p',
        '--output-format',
        'json',
        '--no-session-persistence',
        '--model',
        model,
        '--tools',
        '',  # no tool of any kind
        '--disable-slash-commands',
        '--setting-sources',
        'project',  # never the user's own hooks, memory or instructions; the working directory is empty
        '--system-prompt',
        INSTRUCTIONS,
    ]


def _valid(request):
    return (
        type(request) is dict
        and set(request) == {'consent', 'prompt', 'provider', 'model'}
        and request['consent'] is True
        and request['provider'] == 'claude_code'
        and type(request['prompt']) is str
        and 1 <= len(request['prompt'].encode('utf-8')) <= MAX_PROMPT_BYTES
        and request['model'] in MODELS
    )


def _answer(done):
    if len(done.stdout.encode('utf-8', 'replace')) > MAX_OUTPUT_BYTES:
        return _refusal()
    try:
        body = json.loads(done.stdout)
    except ValueError:
        return _refusal()
    if type(body) is not dict or type(body.get('result')) is not str:
        return _refusal()
    if body.get('is_error') is not False or body.get('subtype') != 'success':
        return LOGIN_REQUIRED if '/login' in body['result'] else _refusal()
    text = body['result'].strip()
    if not text or len(text.encode('utf-8')) > MAX_TEXT_BYTES:
        return _refusal()
    return {'ok': True, 'text': text}


def claude_code_reply(request, *, runner=subprocess.run, which=shutil.which):
    try:
        if not _valid(request):
            return _refusal()
        executable = find_claude(which)
        if executable is None:
            return dict(UNAVAILABLE)
        extra = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        with tempfile.TemporaryDirectory(prefix='markauto-claude-') as empty:
            done = runner(
                command(executable, request['model']),
                input=request['prompt'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                cwd=empty,
                timeout=TIMEOUT_SECONDS,
                shell=False,
                **extra,
            )
        if done.returncode != 0 and not done.stdout.strip():
            return _refusal()
        return _answer(done)
    except Exception:
        # No process output, path or exception text crosses the process boundary.
        return _refusal()
