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
        self.permission = 'read_only'
        self.consent = None

    @property
    def declarations(self):
        return self.__registry.declarations

    def call(self, name, arguments_json):
        declaration = self.declarations.get(name) if type(name) is str else None
        if declaration is None or declaration.get('effect') != 'read' or name not in TOOL_NAMES:
            # Consent is per attempt, never an executable grant. This release
            # has no mutation route, even after an explicit dialog approval.
            if self.permission == 'confirm_each_time' and callable(self.consent):
                try:
                    self.consent()
                except Exception:
                    pass
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
