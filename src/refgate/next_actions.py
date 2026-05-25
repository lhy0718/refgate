from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any


REFGATE_COMMAND_PREFIX = ("python", "-m", "refgate")
NEXT_ACTIONS_SCHEMA_VERSION = "refgate.next_actions.v1"
NEXT_ACTION_SUMMARY_SCHEMA_VERSION = "refgate.next_action_summary.v1"
COMMAND_PLACEHOLDERS = {
    "LOCK",
    "PAPER_BIB",
    "PAPER_TEX",
    "SOURCES_DIR",
    "REFERENCE_CANDIDATES_DIR",
    "REVIEWED_FALLBACK_BIBTEX_DIR",
    "OFFICIAL_BIBTEX_DIR",
    "OFFICIAL_HTML_DIR",
}


def load_next_actions(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    actions = payload.get("next_actions", [])
    if not actions and payload.get("schema_version") == NEXT_ACTIONS_SCHEMA_VERSION:
        actions = payload.get("actions", [])
    if not isinstance(actions, list):
        raise ValueError("Input JSON must contain a next_actions or actions list.")
    return [action for action in actions if isinstance(action, dict)]


def _skip_reason(
    action: dict[str, Any],
    *,
    allow_network: bool,
    allow_writes: bool,
    allow_human_review: bool,
    command: str | None,
    command_field: str,
) -> str | None:
    if not command:
        return "command_missing"
    if _command_placeholders(command):
        return "input_required"
    if command_field != "command" and action.get("missing_inputs") and not _input_options_ready(action.get("input_options", [])):
        return "input_required"
    if action.get("network_required") and not allow_network:
        return "network_required"
    if action.get("writes_files") and not allow_writes:
        return "writes_files"
    if action.get("requires_human_review") and not allow_human_review:
        return "requires_human_review"
    return None


def _command_choices(action: dict[str, Any]) -> dict[str, str]:
    choices = {}
    saved = action.get("command_choices", {})
    if isinstance(saved, dict):
        for key, value in saved.items():
            if isinstance(value, str) and value:
                choices[key] = value
    for key, value in action.items():
        if key == "command" or key.endswith("_command"):
            if isinstance(value, str) and value:
                choices[key] = value
    return choices


def _input_options_ready(input_options: Any) -> bool:
    if not isinstance(input_options, list) or not input_options:
        return False

    def directory_has_files(option: dict[str, Any]) -> bool:
        directory = option.get("directory")
        if not directory:
            return False
        path = Path(str(directory))
        return path.is_dir() and any(child.is_file() for child in path.iterdir())

    options = [option for option in input_options if isinstance(option, dict)]
    html_options = [option for option in options if option.get("kind") == "official_html_fixture"]
    bibtex_options = [
        option
        for option in options
        if option.get("kind") in {"official_bibtex_export_fixture", "reviewed_manual_fallback"}
    ]
    if html_options and not any(directory_has_files(option) for option in html_options):
        return False
    if bibtex_options and not any(directory_has_files(option) for option in bibtex_options):
        return False
    return any(directory_has_files(option) for option in options)


def _command_placeholders(command: str) -> list[str]:
    argv = shlex.split(command)
    found = []
    for item in argv:
        if item in COMMAND_PLACEHOLDERS and item not in found:
            found.append(item)
    return found


def _command_argv(command: str) -> list[str]:
    argv = shlex.split(command)
    if len(argv) < 3 or tuple(argv[:3]) != REFGATE_COMMAND_PREFIX:
        raise ValueError("Only commands beginning with 'python -m refgate' can be executed.")
    return [sys.executable, *argv[1:]]


def _agent_hint(item: dict[str, Any]) -> str:
    if item.get("code") == "FETCH_OFFICIAL_BIBTEX_EXPORT":
        if item.get("selected"):
            return "Ready to fetch the official BibTeX export from the selected authority."
        if item.get("skip_reason") == "network_required":
            return "Official BibTeX export is available; enable --allow-network only after live-network approval."
    if item.get("code") == "ADD_OFFICIAL_BIBTEX_FIXTURE":
        return "Save the reviewed publisher BibTeX export using one of the official_bibtex_file_examples, then rerun reference-check."
    if item.get("code") == "ADD_OFFICIAL_HTML_FIXTURE":
        return "Save reviewed official record HTML using one of the fixture_html_file_examples, then rerun reference-check."
    reason = item.get("skip_reason")
    if item.get("selected"):
        return "Ready to execute with the current gates."
    if reason == "network_required":
        return "Enable --allow-network only after explicit live-network approval."
    if reason == "writes_files":
        return "Enable --allow-writes only when file updates are intended."
    if reason == "requires_human_review":
        return "Enable --allow-human-review only after reviewed inputs or source evidence are available."
    if reason == "input_required":
        missing = ", ".join(item.get("missing_inputs") or item.get("command_placeholders") or [])
        return f"Provide reviewed input paths before execution: {missing}." if missing else "Provide reviewed input paths before execution."
    if reason == "command_missing":
        return "No executable command is attached to this action; handle it manually."
    if reason == "max_actions":
        return "Not selected because the max-actions limit was reached."
    return "Inspect this action before execution."


def _source_guidance_summary(action: dict[str, Any]) -> dict[str, Any]:
    guidance = action.get("source_guidance")
    if not isinstance(guidance, dict):
        return {}
    keys = [
        "source",
        "fixture_html_file_examples",
        "official_bibtex_file_examples",
        "record_url_patterns",
        "official_bibtex_url_pattern",
        "source_pdf_url_pattern",
        "live_fetch_note",
    ]
    return {key: guidance[key] for key in keys if guidance.get(key)}


def _action_summary(action: dict[str, Any]) -> str:
    code = str(action.get("code") or "")
    citation_key = str(action.get("citation_key") or "")
    target = f" for {citation_key}" if citation_key else ""
    if code == "FETCH_OFFICIAL_BIBTEX_EXPORT":
        return f"Fetch official BibTeX export{target}."
    if code == "ADD_OFFICIAL_BIBTEX_FIXTURE":
        return f"Save reviewed official BibTeX fixture{target}."
    if code == "ADD_OFFICIAL_HTML_FIXTURE":
        return f"Save reviewed official HTML fixture{target}."
    if code == "ADD_BIBTEX_PROVENANCE":
        preferred = action.get("preferred_input")
        if preferred == "official_bibtex_export":
            return f"Provide official BibTeX provenance{target}; manual fallback remains secondary."
        return f"Provide reviewed BibTeX provenance{target}."
    if code == "RETRY_OR_CACHE_LIVE_LOOKUP":
        return f"Retry live lookup with cache preference{target}."
    if code == "ADD_REFERENCE_CANDIDATES":
        return f"Add reviewed reference candidate file{target}."
    return str(action.get("message") or code or "Inspect next action.")


def _top_level_next_step(planned: list[dict[str, Any]]) -> dict[str, Any]:
    selected = next((item for item in planned if item.get("selected") and item.get("command")), None)
    if selected:
        return {
            "status": "ready",
            "command": selected.get("command"),
            "command_field": selected.get("command_field"),
            "code": selected.get("code"),
            "action_summary": selected.get("action_summary"),
            "hint": selected.get("agent_hint"),
            "source_guidance": selected.get("source_guidance_summary", {}),
        }
    actionable = next((item for item in planned if item.get("command")), None)
    if actionable:
        return {
            "status": "blocked",
            "command": actionable.get("command"),
            "command_field": actionable.get("command_field"),
            "code": actionable.get("code"),
            "action_summary": actionable.get("action_summary"),
            "skip_reason": actionable.get("skip_reason"),
            "hint": actionable.get("agent_hint"),
            "source_guidance": actionable.get("source_guidance_summary", {}),
        }
    return {
        "status": "none",
        "command": None,
        "hint": "No next-action command is available.",
    }


def plan_next_actions(
    actions: list[dict[str, Any]],
    *,
    allow_network: bool = False,
    allow_writes: bool = False,
    allow_human_review: bool = False,
    max_actions: int | None = None,
    command_field: str = "command",
) -> list[dict[str, Any]]:
    planned = []
    selected_count = 0
    for index, action in enumerate(actions):
        choices = _command_choices(action)
        command = choices.get(command_field)
        reason = _skip_reason(
            action,
            allow_network=allow_network,
            allow_writes=allow_writes,
            allow_human_review=allow_human_review,
            command=command,
            command_field=command_field,
        )
        selected = reason is None and (max_actions is None or selected_count < max_actions)
        if selected:
            selected_count += 1
        elif reason is None:
            reason = "max_actions"
        item = {
                "index": index,
                "selected": selected,
                "skip_reason": reason,
                "code": action.get("code", ""),
                "kind": action.get("kind", ""),
                "requires_human_review": bool(action.get("requires_human_review")),
                "writes_files": bool(action.get("writes_files")),
                "network_required": bool(action.get("network_required")),
                "command": command,
                "command_field": command_field,
                "available_command_fields": sorted(choices),
                "command_choices": choices,
                "message": action.get("message", ""),
                "input_options": action.get("input_options", []),
                "missing_inputs": action.get("missing_inputs", []),
                "command_placeholders": _command_placeholders(command or ""),
                "ready_to_execute": selected,
                "citation_key": action.get("citation_key", ""),
                "official_bibtex_url": action.get("official_bibtex_url"),
                "fixture_html_file_examples": action.get("fixture_html_file_examples", []),
                "official_bibtex_file_examples": action.get("official_bibtex_file_examples", []),
                "preferred_input": action.get("preferred_input"),
                "source_guidance_summary": _source_guidance_summary(action),
                "action_summary": _action_summary(action),
            }
        item["agent_hint"] = _agent_hint(item)
        planned.append(item)
    return planned


def execute_planned_actions(planned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for item in planned:
        if not item["selected"]:
            results.append({**item, "executed": False})
            continue
        try:
            completed = subprocess.run(
                _command_argv(item["command"]),
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            results.append(
                {
                    **item,
                    "executed": True,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"{exc.__class__.__name__}: {exc}",
                }
            )
            continue
        results.append(
            {
                **item,
                "executed": True,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
        )
    return results


def build_next_actions_result(
    actions: list[dict[str, Any]],
    *,
    input_label: str,
    allow_network: bool = False,
    allow_writes: bool = False,
    allow_human_review: bool = False,
    max_actions: int | None = None,
    command_field: str = "command",
    execute: bool = False,
) -> dict[str, Any]:
    planned = plan_next_actions(
        actions,
        allow_network=allow_network,
        allow_writes=allow_writes,
        allow_human_review=allow_human_review,
        max_actions=max_actions,
        command_field=command_field,
    )
    results = execute_planned_actions(planned) if execute else planned
    selected_count = sum(1 for item in planned if item["selected"])
    failed_count = sum(1 for item in results if item.get("executed") and item.get("returncode") not in {0, None})
    return {
        "schema_version": NEXT_ACTIONS_SCHEMA_VERSION,
        "ok": failed_count == 0,
        "input": input_label,
        "execute": execute,
        "gates": {
            "allow_network": allow_network,
            "allow_writes": allow_writes,
            "allow_human_review": allow_human_review,
            "max_actions": max_actions,
            "command_field": command_field,
        },
        "action_count": len(actions),
        "selected_count": selected_count,
        "skipped_count": len(actions) - selected_count,
        "failed_count": failed_count,
        "recommended_next": _top_level_next_step(planned),
        "actions": results,
    }


def run_next_actions(
    path: str | Path,
    *,
    allow_network: bool = False,
    allow_writes: bool = False,
    allow_human_review: bool = False,
    max_actions: int | None = None,
    command_field: str = "command",
    execute: bool = False,
) -> dict[str, Any]:
    actions = load_next_actions(path)
    return build_next_actions_result(
        actions,
        input_label=str(path),
        allow_network=allow_network,
        allow_writes=allow_writes,
        allow_human_review=allow_human_review,
        max_actions=max_actions,
        command_field=command_field,
        execute=execute,
    )


def write_next_actions_result(path: str | Path, result: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compact_action(manifest: str, action: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "manifest": manifest,
        "index": action.get("index"),
        "status": status,
        "code": action.get("code", ""),
        "kind": action.get("kind", ""),
        "citation_key": action.get("citation_key", ""),
        "action_summary": action.get("action_summary", ""),
        "command": action.get("command"),
        "command_field": action.get("command_field"),
        "message": action.get("message", ""),
        "skip_reason": action.get("skip_reason"),
        "agent_hint": action.get("agent_hint", ""),
        "source_guidance_summary": action.get("source_guidance_summary", {}),
        "official_bibtex_url": action.get("official_bibtex_url"),
        "returncode": action.get("returncode"),
        "requires_human_review": bool(action.get("requires_human_review")),
        "writes_files": bool(action.get("writes_files")),
        "network_required": bool(action.get("network_required")),
    }


def _action_status(action: dict[str, Any]) -> str:
    if action.get("executed"):
        return "succeeded" if action.get("returncode") in {0, None} else "failed"
    if action.get("selected"):
        return "planned_not_executed"
    return f"skipped_{action.get('skip_reason') or 'unknown'}"


def summarize_next_action_manifests(paths: list[str | Path]) -> dict[str, Any]:
    manifests = []
    status_counts: dict[str, int] = {}
    failed_actions = []
    remaining_actions = []
    action_count = 0
    for path in paths:
        manifest_path = str(path)
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        actions = [action for action in payload.get("actions", []) if isinstance(action, dict)]
        manifests.append(
            {
                "path": manifest_path,
                "schema_version": payload.get("schema_version", ""),
                "execute": bool(payload.get("execute")),
                "ok": bool(payload.get("ok")),
                "action_count": len(actions),
                "selected_count": int(payload.get("selected_count", 0)),
                "failed_count": int(payload.get("failed_count", 0)),
            }
        )
        for action in actions:
            action_count += 1
            status = _action_status(action)
            status_counts[status] = status_counts.get(status, 0) + 1
            compact = _compact_action(manifest_path, action, status)
            if status == "failed":
                failed_actions.append(compact)
                remaining_actions.append(compact)
            elif status != "succeeded":
                remaining_actions.append(compact)
    return {
        "schema_version": NEXT_ACTION_SUMMARY_SCHEMA_VERSION,
        "ok": not failed_actions and not remaining_actions,
        "manifest_count": len(paths),
        "action_count": action_count,
        "status_counts": status_counts,
        "failed_count": len(failed_actions),
        "remaining_count": len(remaining_actions),
        "recommended_next": _top_level_next_step(remaining_actions),
        "failed_actions": failed_actions,
        "remaining_actions": remaining_actions,
        "manifests": manifests,
    }


def render_next_action_summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Refgate Next-Action Summary",
        "",
        f"- Status: {'pass' if summary.get('ok') else 'needs action'}",
        f"- Manifests: {summary.get('manifest_count', 0)}",
        f"- Actions: {summary.get('action_count', 0)}",
        f"- Remaining: {summary.get('remaining_count', 0)}",
        f"- Failed: {summary.get('failed_count', 0)}",
    ]

    status_counts = summary.get("status_counts") or {}
    if status_counts:
        lines.extend(["", "## Status Counts"])
        for status, count in sorted(status_counts.items()):
            lines.append(f"- `{status}`: {count}")

    recommended = summary.get("recommended_next") or {}
    if recommended and recommended.get("status") != "none":
        lines.extend(["", "## Recommended Next"])
        if recommended.get("code"):
            lines.append(f"- Code: `{recommended.get('code')}`")
        if recommended.get("action_summary"):
            lines.append(f"- Action: {recommended.get('action_summary')}")
        if recommended.get("skip_reason"):
            lines.append(f"- Blocker: `{recommended.get('skip_reason')}`")
        if recommended.get("hint"):
            lines.append(f"- Hint: {recommended.get('hint')}")
        if recommended.get("command"):
            lines.extend(["", "```bash", str(recommended.get("command")), "```"])

    remaining = summary.get("remaining_actions") or []
    if remaining:
        lines.extend(["", "## Remaining Actions"])
        for action in remaining:
            title_parts = [str(action.get("status") or "pending")]
            if action.get("code"):
                title_parts.append(str(action.get("code")))
            if action.get("citation_key"):
                title_parts.append(str(action.get("citation_key")))
            lines.append(f"- {' / '.join(title_parts)}")
            if action.get("action_summary"):
                lines.append(f"  - Action: {action.get('action_summary')}")
            if action.get("agent_hint"):
                lines.append(f"  - Hint: {action.get('agent_hint')}")
            if action.get("command"):
                lines.append(f"  - Command: `{action.get('command')}`")

    failed = summary.get("failed_actions") or []
    if failed:
        lines.extend(["", "## Failed Actions"])
        for action in failed:
            lines.append(f"- `{action.get('code', '')}` returncode={action.get('returncode')}")
            if action.get("command"):
                lines.append(f"  - Command: `{action.get('command')}`")

    return "\n".join(lines).rstrip() + "\n"
