from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


CONFIG_ENV = "REFGATE_AUTH_CONFIG"


@dataclass(frozen=True)
class AuthSource:
    key: str
    label: str
    config_key: str
    env_names: tuple[str, ...]
    required_for: str


AUTH_SOURCES: dict[str, AuthSource] = {
    "semantic-scholar": AuthSource(
        key="semantic-scholar",
        label="Semantic Scholar",
        config_key="semantic_scholar_api_key",
        env_names=("REFGATE_SEMANTIC_SCHOLAR_API_KEY", "S2_API_KEY"),
        required_for="higher-rate Semantic Scholar discovery",
    ),
    "crossref-mailto": AuthSource(
        key="crossref-mailto",
        label="Crossref mailto",
        config_key="crossref_mailto",
        env_names=("REFGATE_CROSSREF_MAILTO",),
        required_for="polite Crossref discovery",
    ),
    "openalex-mailto": AuthSource(
        key="openalex-mailto",
        label="OpenAlex mailto",
        config_key="openalex_mailto",
        env_names=("REFGATE_OPENALEX_MAILTO",),
        required_for="polite OpenAlex discovery",
    ),
}


def auth_config_path() -> Path:
    configured = os.environ.get(CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    xdg_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_home:
        return Path(xdg_home).expanduser() / "refgate" / "auth.json"
    return Path.home() / ".config" / "refgate" / "auth.json"


def load_auth_config(path: str | Path | None = None) -> dict[str, str]:
    target = Path(path) if path else auth_config_path()
    if not target.exists():
        return {}
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Refgate auth config must be a JSON object.")
    return {str(key): str(value) for key, value in data.items() if value is not None}


def save_auth_value(source_key: str, value: str, path: str | Path | None = None) -> Path:
    if source_key not in AUTH_SOURCES:
        raise ValueError(f"Unknown auth source: {source_key}")
    target = Path(path) if path else auth_config_path()
    config = load_auth_config(target)
    config[AUTH_SOURCES[source_key].config_key] = value.strip()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def select_auth_sources() -> list[str]:
    """Select auth sources with a tiny dependency-free TUI when possible."""
    keys = sorted(AUTH_SOURCES)
    try:
        import curses
        import sys
        if sys.stdin.isatty() and sys.stdout.isatty():
            return curses.wrapper(_curses_select_auth_sources, keys)
    except Exception:
        pass
    print("Select Refgate auth values to configure:")
    for index, key in enumerate(keys, start=1):
        source = AUTH_SOURCES[key]
        print(f"{index}. {source.label} - {source.required_for}")
    raw = input("Enter numbers separated by comma: ").strip()
    selected = []
    for item in re_split_numbers(raw):
        if 1 <= item <= len(keys):
            selected.append(keys[item - 1])
    return selected


def re_split_numbers(value: str) -> list[int]:
    numbers = []
    for part in value.replace(" ", "").split(","):
        if part.isdigit():
            numbers.append(int(part))
    return numbers


def _curses_select_auth_sources(stdscr: Any, keys: list[str]) -> list[str]:
    selected: set[str] = set()
    cursor = 0
    while True:
        stdscr.clear()
        stdscr.addstr(0, 0, "Refgate auth setup: Up/Down move, Space toggle, Enter save, q cancel")
        for index, key in enumerate(keys):
            source = AUTH_SOURCES[key]
            marker = "[x]" if key in selected else "[ ]"
            prefix = ">" if index == cursor else " "
            stdscr.addstr(index + 2, 0, f"{prefix} {marker} {source.label} - {source.required_for}")
        key_code = stdscr.getch()
        if key_code in (ord("q"), 27):
            return []
        if key_code in (curses.KEY_UP, ord("k")):
            cursor = (cursor - 1) % len(keys)
        elif key_code in (curses.KEY_DOWN, ord("j")):
            cursor = (cursor + 1) % len(keys)
        elif key_code == ord(" "):
            key = keys[cursor]
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
        elif key_code in (10, 13, curses.KEY_ENTER):
            return [key for key in keys if key in selected]


def mask_value(value: str | None) -> str | None:
    if not value:
        return None
    if "@" in value:
        local, _, domain = value.partition("@")
        visible_local = local[:2] if len(local) > 2 else local[:1]
        return f"{visible_local}***@{domain}"
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def get_auth_value(source_key: str) -> tuple[str | None, str | None]:
    source = AUTH_SOURCES[source_key]
    for env_name in source.env_names:
        value = os.environ.get(env_name)
        if value:
            return value, f"env:{env_name}"
    config = load_auth_config()
    value = config.get(source.config_key)
    if value:
        return value, f"config:{auth_config_path()}"
    return None, None


def auth_status() -> dict[str, Any]:
    sources = []
    for source in AUTH_SOURCES.values():
        value, origin = get_auth_value(source.key)
        sources.append(
            {
                "source": source.key,
                "label": source.label,
                "configured": bool(value),
                "origin": origin,
                "display": mask_value(value),
                "env_names": list(source.env_names),
                "required_for": source.required_for,
            }
        )
    return {"config_path": str(auth_config_path()), "sources": sources}


def auth_doctor() -> dict[str, Any]:
    status = auth_status()
    warnings = []
    for source in status["sources"]:
        if not source["configured"]:
            warnings.append(
                {
                    "code": "AUTH_VALUE_MISSING",
                    "source": source["source"],
                    "message": f"{source['label']} is not configured; related live discovery still works where the upstream service allows anonymous requests.",
                }
            )
    return {"status": status, "warnings": warnings}


def semantic_scholar_api_key() -> str | None:
    value, _origin = get_auth_value("semantic-scholar")
    return value


def crossref_mailto() -> str | None:
    value, _origin = get_auth_value("crossref-mailto")
    return value


def openalex_mailto() -> str | None:
    value, _origin = get_auth_value("openalex-mailto")
    return value


def append_query_param(url: str, key: str, value: str | None) -> str:
    if not value:
        return url
    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    if key not in params:
        params[key] = value
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))
