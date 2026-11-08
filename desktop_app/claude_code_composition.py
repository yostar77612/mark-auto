"""Claude Code reply wiring at the desktop process composition boundary."""

import json

from quantlab.agent_tools import _refusal
from quantlab.assistant.adapters.claude_code.reply import claude_code_reply
from quantlab.assistant.ports.reply import configure_reply_provider

# Claude Code needs several seconds just to start; the ChatGPT route keeps its own, shorter limit.
DEADLINE_SECONDS = 100


def claude_reply_worker(sender, gate, request, bootstrap):
    """Spawned child entry point: exactly one consented question, one bounded answer."""
    try:
        if not gate.wait(15):
            return
        try:
            result = claude_code_reply(request)
        except Exception:
            result = _refusal()
        sender.send_bytes(json.dumps(result).encode('utf-8'))
    finally:
        sender.close()


def configure():
    configure_reply_provider('claude_code', claude_reply_worker, DEADLINE_SECONDS)
