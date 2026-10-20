"""Session-only research assistant boundary. Model requests never carry authority."""

import json

from quantlab.agent_read_tools import ReadContext, TOOL_NAMES, create_registry
from quantlab.agent_tools import _refusal
from quantlab.agent_tool_contract import MAX_RETURN_BYTES


class ChatDispatcher:
    """The host supplies provenance once; tools cannot change it or register handlers."""

    def __init__(self, context):
        if type(context) is not ReadContext:
            raise ValueError
        self.__context = context
        self.__registry = create_registry()

    @property
    def declarations(self):
        return self.__registry.declarations

    def call(self, name, arguments_json):
        if type(name) is not str or name not in TOOL_NAMES:
            return _refusal()
        return self.__registry.call(name, arguments_json, capabilities=('research.read', 'paper.read'), context=self.__context)

    def render_tool(self, name, arguments_json):
        # D3 is the only success path, and every D3 handler uses bounded_return.
        result = self.call(name, arguments_json)
        raw = json.dumps(result, ensure_ascii=True, sort_keys=True)
        if len(raw.encode()) > MAX_RETURN_BYTES:
            raw = json.dumps(_refusal(), sort_keys=True)
        return raw


def fixture_reply(prompt):
    """Fixed replies selected by an exact prompt, without a provider or network."""
    return 'help' if prompt.strip().casefold() in ('help', '/help') else 'research'
