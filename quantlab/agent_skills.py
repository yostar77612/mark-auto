"""D7 local prompt data, never authority. Host sessions only narrow D1 grants.

Front matter uses exactly four single-line keys with JSON string/list values.
This deliberately small Markdown dialect has no YAML tags, aliases or programs.
Only the registered docs/skills directory is read; model text cannot choose it.
"""

from dataclasses import dataclass
from pathlib import Path
import re

from quantlab.agent_return import MAX_FIELD_CHARS, bounded_return
from quantlab.agent_tool_contract import MAX_LIMIT, strict_json
from quantlab.agent_tools import _refusal


SKILLS_DIRECTORY = Path(__file__).resolve().parents[1] / 'docs' / 'skills'
MAX_SKILL_BYTES = 16384
MAX_SKILLS = 128
READ_CAPABILITIES = frozenset({'research.read', 'paper.read'})
_FIELDS = frozenset({'name', 'description', 'allowed_tools', 'output_format'})


def _name(value):
    if type(value) is not str or re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', value) is None or len(value) > 64:
        raise ValueError
    return value


def _link(path):
    # Reparse points include Windows junctions, also on Python 3.11.
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    allowed_tools: tuple[str, ...]
    output_format: str
    body: str


def _tools(names, registry):
    if type(names) not in (list, tuple) or not 1 <= len(names) <= MAX_LIMIT or any(type(name) is not str for name in names):
        raise ValueError
    if len(set(names)) != len(names):
        raise ValueError
    declarations = registry.declarations
    for name in names:
        declaration = declarations.get(name)
        if not declaration or declaration['effect'] != 'read' or declaration['capability'] not in READ_CAPABILITIES:
            raise ValueError
    return tuple(names)


def parse_skill(raw, registry):
    """Strict hand-written front-matter parser; body is immutable inert text."""
    if type(raw) is not bytes or len(raw) > MAX_SKILL_BYTES:
        raise ValueError
    text = raw.decode('utf-8', errors='strict')
    if '\x00' in text:
        raise ValueError
    lines = text.splitlines()
    if not lines or lines[0] != '---':
        raise ValueError
    fields = {}
    end = None
    for index, line in enumerate(lines[1:], 1):
        if line == '---':
            end = index
            break
        key, separator, value = line.partition(': ')
        if not separator or key not in _FIELDS or key in fields:
            raise ValueError
        parsed = strict_json('{"value":' + value + '}')
        if parsed.keys() != {'value'}:
            raise ValueError
        fields[key] = parsed['value']
    if end is None or fields.keys() != _FIELDS:
        raise ValueError
    for key in ('description', 'output_format'):
        value = fields[key]
        if type(value) is not str or not value.strip() or len(value) > MAX_FIELD_CHARS or any(ord(char) < 32 for char in value):
            raise ValueError
    body = '\n'.join(lines[end + 1 :]).strip()
    if not body:
        raise ValueError
    return Skill(_name(fields['name']), fields['description'], _tools(fields['allowed_tools'], registry), fields['output_format'], body)


class SkillLoader:
    """Host-owned registry; no registration, permission or capability-grant API.

    list/read accept model arguments only as strict JSON. All returned prompt
    text is untrusted. There is no dataset, provider or credential reader here.
    Invalid catalogs refuse atomically, without paths or exception messages.
    """

    def __init__(self, registry):
        self._registry = registry

    def _catalog(self):
        root = SKILLS_DIRECTORY
        if any(_link(path) for path in (root, *root.parents)):
            raise ValueError
        root = root.resolve(strict=True)
        skills = {}
        for index, path in enumerate(root.iterdir()):
            if index >= MAX_SKILLS or _link(path) or not path.is_file() or path.suffix != '.md':
                raise ValueError
            name = _name(path.stem)
            if path.resolve(strict=True).parent != root:
                raise ValueError
            with path.open('rb') as stream:
                raw = stream.read(MAX_SKILL_BYTES + 1)
            skill = parse_skill(raw, self._registry)
            if skill.name != name or name in skills:
                raise ValueError
            skills[name] = skill
        return dict(sorted(skills.items()))

    def list(self, arguments_json='{}'):
        try:
            args = strict_json(arguments_json)
            if args.keys() - {'limit', 'cursor'}:
                raise ValueError
            rows = [
                {'name': skill.name, 'description': skill.description, 'allowed_tools': list(skill.allowed_tools), 'output_format': skill.output_format}
                for skill in self._catalog().values()
            ]
            return bounded_return(rows, limit=args.get('limit', MAX_LIMIT), cursor=args.get('cursor'), scope='skills.list')
        except (OSError, TypeError, ValueError, RecursionError):
            return _refusal()

    def read(self, arguments_json):
        try:
            args = strict_json(arguments_json)
            if args.keys() - {'name', 'limit', 'cursor'} or 'name' not in args:
                raise ValueError
            name = _name(args['name'])  # Validate before any filesystem access.
            skill = self._catalog().get(name)
            if skill is None:
                raise ValueError
            rows = [
                {'name': name, 'index': i // MAX_FIELD_CHARS, 'text': skill.body[i : i + MAX_FIELD_CHARS]} for i in range(0, len(skill.body), MAX_FIELD_CHARS)
            ]
            return bounded_return(rows, limit=args.get('limit', MAX_LIMIT), cursor=args.get('cursor'), scope='skills.read:' + name)
        except (OSError, TypeError, ValueError, RecursionError):
            return _refusal()

    def activate(self, name, *, capabilities=()):
        """Host supplies existing grants; prompt text never supplies grants."""
        try:
            name = _name(name)
            skill = self._catalog().get(name)
            if skill is None:
                raise ValueError
            return SkillSession(self._registry, skill, capabilities)
        except (OSError, TypeError, ValueError, RecursionError):
            return _refusal()


@dataclass(frozen=True, init=False)
class SkillSession:
    """Runtime entry point while active. No body is parsed as model authority."""

    _registry: object
    skill: Skill
    capabilities: frozenset[str]

    def __init__(self, registry, skill, capabilities):
        _tools(skill.allowed_tools, registry)
        required = {registry.declarations[name]['capability'] for name in skill.allowed_tools}
        object.__setattr__(self, '_registry', registry)
        object.__setattr__(self, 'skill', skill)
        object.__setattr__(self, 'capabilities', frozenset(capabilities) & READ_CAPABILITIES & required)

    def call(self, name, arguments_json, *, context=()):
        if type(name) is not str or name not in self.skill.allowed_tools:
            return _refusal()
        return self._registry.call(name, arguments_json, capabilities=self.capabilities, context=context)
