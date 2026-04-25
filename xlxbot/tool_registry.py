import importlib.util
import json
import os
from dataclasses import dataclass


@dataclass
class ToolDefinition:
    name: str
    capability: str
    risk: str
    env_constraints: list[str]


@dataclass
class ToolRegistry:
    version: int
    tools: list[ToolDefinition]

    def get(self, name: str):
        target = (name or '').strip()
        for tool in self.tools:
            if tool.name == target:
                return tool
        return None

    def get_missing_env_constraints(self, tool: ToolDefinition, config):
        if tool is None:
            return ['tool_definition_missing']

        checks = {
            'KNOWLEDGE_FILE': bool(getattr(config, 'knowledge_file', '')),
            'OLLAMA_API_URL': bool(getattr(config, 'ollama_api_url', '')),
            'OLLAMA_MODEL_NAME': bool(getattr(config, 'ollama_model_name', '')),
            'LINE_ACCESS_TOKEN': bool(getattr(config, 'line_access_token', '')),
            'LINE_CHANNEL_SECRET': bool(getattr(config, 'line_channel_secret', '')),
            'PUBLIC_BASE_URL': bool(getattr(config, 'public_base_url', '') or getattr(config, 'ngrok_api_url', '')),
            'MEMORY_DIR': bool(getattr(config, 'memory_dir', '')),
            'SIDECAR_ENABLED': bool(getattr(config, 'sidecar_enabled', False)),
            'OPENCLAW_BASE_URL': bool(getattr(config, 'openclaw_base_url', '')),
            'OPENCLAW_API_KEY': bool(getattr(config, 'openclaw_api_key', '')),
        }

        missing = []
        for constraint in tool.env_constraints:
            if not checks.get(constraint, bool(os.getenv(constraint, '').strip())):
                missing.append(constraint)
        return missing


_YAML_AVAILABLE = importlib.util.find_spec('yaml') is not None
if _YAML_AVAILABLE:
    import yaml
else:
    yaml = None


def _load_raw_registry(path):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if yaml is not None:
        data = yaml.safe_load(content)
        return data or {}

    # Fallback: parse a limited YAML subset used by config/tool_registry.yaml.
    return _parse_simple_tool_registry_yaml(content)


def _parse_simple_tool_registry_yaml(content):
    data = {'version': 1, 'tools': []}
    current_tool = None
    in_env_constraints = False

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        if line.startswith('version:'):
            data['version'] = int(stripped.split(':', 1)[1].strip())
            continue

        if stripped == 'tools:':
            continue

        if stripped.startswith('- name:'):
            if current_tool is not None:
                data['tools'].append(current_tool)
            current_tool = {
                'name': stripped.split(':', 1)[1].strip(),
                'capability': '',
                'risk': 'unknown',
                'env_constraints': [],
            }
            in_env_constraints = False
            continue

        if current_tool is None:
            continue

        if stripped.startswith('capability:'):
            current_tool['capability'] = stripped.split(':', 1)[1].strip()
            in_env_constraints = False
            continue

        if stripped.startswith('risk:'):
            current_tool['risk'] = stripped.split(':', 1)[1].strip()
            in_env_constraints = False
            continue

        if stripped.startswith('env_constraints:'):
            in_env_constraints = True
            continue

        if in_env_constraints and stripped.startswith('- '):
            current_tool['env_constraints'].append(stripped[2:].strip())
            continue

        in_env_constraints = False

    if current_tool is not None:
        data['tools'].append(current_tool)

    if not data['tools']:
        return json.loads(content)
    return data


def load_tool_registry(path='config/tool_registry.yaml'):
    if not os.path.exists(path):
        return ToolRegistry(version=1, tools=[])

    data = _load_raw_registry(path)
    raw_tools = data.get('tools') or []
    tools = []
    for raw in raw_tools:
        tools.append(
            ToolDefinition(
                name=str(raw.get('name', '')).strip(),
                capability=str(raw.get('capability', '')).strip(),
                risk=str(raw.get('risk', 'unknown')).strip().lower(),
                env_constraints=[str(item).strip() for item in (raw.get('env_constraints') or []) if str(item).strip()],
            )
        )
    return ToolRegistry(version=int(data.get('version', 1)), tools=tools)
