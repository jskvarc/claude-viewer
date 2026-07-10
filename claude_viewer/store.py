"""Parse Claude Code session logs from ~/.claude/projects."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / '.claude' / 'projects'

# User-record texts that are session plumbing rather than typed prompts.
_NOISE_PREFIXES = (
    '<command-name>',
    '<local-command-stdout',
    '<local-command-stderr',
    '<system-reminder',
    'Caveat: The messages below were generated',
    '[Request interrupted',
)


@dataclass
class Message:
    uuid: str
    role: str  # 'user' | 'assistant' | 'tool'
    text: str
    timestamp: str = ''


@dataclass
class SessionData:
    path: Path
    title: str
    messages: list[Message] = field(default_factory=list)
    started: str = ''
    ended: str = ''

    @property
    def prompt_count(self) -> int:
        return sum(1 for m in self.messages if m.role == 'user')


@dataclass
class Project:
    dir_path: Path
    real_path: str
    session_files: list[Path]

    @property
    def name(self) -> str:
        return Path(self.real_path).name or self.real_path


def format_timestamp(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return ts


def _clean_user_text(text: str) -> str:
    text = text.strip()
    if any(text.startswith(prefix) for prefix in _NOISE_PREFIXES):
        return ''
    return text


def _user_text(content) -> str:
    """Extract the typed prompt from a user record, ignoring tool results."""
    if isinstance(content, str):
        return _clean_user_text(content)
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                cleaned = _clean_user_text(block.get('text') or '')
                if cleaned:
                    parts.append(cleaned)
        return '\n\n'.join(parts)
    return ''


def _tool_summary(block: dict) -> str:
    name = block.get('name') or 'tool'
    params = block.get('input') or {}
    detail = ''
    for key in ('description', 'command', 'file_path', 'pattern', 'query', 'prompt'):
        if params.get(key):
            detail = str(params[key]).replace('\n', ' ')
            break
    if len(detail) > 120:
        detail = f'{detail[:120]}…'
    return f'{name}: {detail}' if detail else name


def parse_session_file(path: Path) -> SessionData:
    data = SessionData(path=path, title='')
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            record_type = obj.get('type')
            if record_type == 'ai-title':
                data.title = obj.get('aiTitle') or data.title
                continue
            if record_type not in ('user', 'assistant') or obj.get('isSidechain') or obj.get('isMeta'):
                continue
            message = obj.get('message') or {}
            uuid = obj.get('uuid') or ''
            ts = obj.get('timestamp') or ''
            if ts:
                data.started = data.started or ts
                data.ended = ts
            if record_type == 'user':
                text = _user_text(message.get('content'))
                # A prompt re-sent after e.g. a login error appears twice in
                # the log; collapse consecutive identical prompts.
                if text and not (data.messages and data.messages[-1].role == 'user'
                                 and data.messages[-1].text == text):
                    data.messages.append(Message(uuid, 'user', text, ts))
            else:
                if message.get('model') == '<synthetic>':
                    continue
                for block in message.get('content') or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get('type') == 'text' and (block.get('text') or '').strip():
                        text = block['text'].strip()
                        # Streaming writes one record per content block; merge
                        # consecutive assistant text into a single message.
                        if data.messages and data.messages[-1].role == 'assistant':
                            data.messages[-1].text += f'\n\n{text}'
                        else:
                            data.messages.append(Message(uuid, 'assistant', text, ts))
                    elif block.get('type') == 'tool_use':
                        tool_uuid = f'{uuid}-tool-{len(data.messages)}'
                        data.messages.append(Message(tool_uuid, 'tool', _tool_summary(block), ts))
    if not data.title:
        first_prompt = next((m.text for m in data.messages if m.role == 'user'), path.stem)
        data.title = first_prompt[:80]
    return data


_session_cache: dict[str, tuple[float, SessionData]] = {}


def load_session(path: Path) -> SessionData:
    mtime = path.stat().st_mtime
    cached = _session_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    data = parse_session_file(path)
    _session_cache[str(path)] = (mtime, data)
    return data


def _real_path(session_files: list[Path], dir_name: str) -> str:
    """Read the original working directory from the session records."""
    for session_file in session_files[:3]:
        try:
            with session_file.open(encoding='utf-8') as fh:
                for _, line in zip(range(50), fh):
                    try:
                        cwd = json.loads(line).get('cwd')
                    except json.JSONDecodeError:
                        continue
                    if cwd:
                        return cwd
        except OSError:
            continue
    return dir_name.replace('-', '/')  # lossy fallback


def list_projects() -> list[Project]:
    if not PROJECTS_DIR.is_dir():
        return []
    projects = []
    for entry in PROJECTS_DIR.iterdir():
        if not entry.is_dir():
            continue
        session_files = sorted(entry.glob('*.jsonl'), key=lambda f: f.stat().st_mtime, reverse=True)
        if not session_files:
            continue
        projects.append(Project(entry, _real_path(session_files, entry.name), session_files))
    projects.sort(key=lambda p: p.session_files[0].stat().st_mtime, reverse=True)
    return projects
