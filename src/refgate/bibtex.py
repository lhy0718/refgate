from __future__ import annotations

import hashlib
import re


ENTRY_RE = re.compile(r"@\s*(?P<type>\w+)\s*\{\s*(?P<key>[^,\s]+)\s*,(?P<body>.*)\}\s*$", re.DOTALL)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_bibtex_entry(text: str) -> dict[str, str]:
    match = ENTRY_RE.search(text.strip())
    if not match:
        raise ValueError("Could not parse BibTeX entry")
    fields = {"entry_type": match.group("type").lower(), "citation_key": match.group("key").strip()}
    body = match.group("body")
    fields.update(_parse_fields(body))
    return fields


def _parse_value(body: str, index: int) -> tuple[str, int]:
    parts: list[str] = []
    length = len(body)
    while index < length:
        while index < length and body[index].isspace():
            index += 1
        value_start = index
        if index < length and body[index] == "{":
            depth = 0
            while index < length:
                char = body[index]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        index += 1
                        break
                index += 1
        elif index < length and body[index] == '"':
            index += 1
            escaped = False
            while index < length:
                char = body[index]
                if char == '"' and not escaped:
                    index += 1
                    break
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
                index += 1
        else:
            while index < length and body[index] not in ",\n#":
                index += 1
        parts.append(clean_bibtex_value(body[value_start:index]))
        while index < length and body[index].isspace():
            index += 1
        if index < length and body[index] == "#":
            index += 1
            continue
        break
    return "".join(parts), index


def _parse_fields(body: str, string_macros: dict[str, str] | None = None) -> dict[str, str]:
    string_macros = {key.lower(): value for key, value in (string_macros or {}).items()}
    fields: dict[str, str] = {}
    index = 0
    length = len(body)
    while index < length:
        while index < length and body[index] in " \t\r\n,":
            index += 1
        name_start = index
        while index < length and re.match(r"[A-Za-z0-9_-]", body[index]):
            index += 1
        if index == name_start:
            break
        name = body[name_start:index].lower()
        while index < length and body[index].isspace():
            index += 1
        if index >= length or body[index] != "=":
            break
        index += 1
        value, index = _parse_value(body, index)
        fields[name] = string_macros.get(value.lower(), value)
        while index < length and body[index] != ",":
            if not body[index].isspace():
                break
            index += 1
        if index < length and body[index] == ",":
            index += 1
    return fields


def clean_bibtex_value(value: str) -> str:
    value = value.strip().rstrip(",").strip()
    if (value.startswith("{") and value.endswith("}")) or (value.startswith('"') and value.endswith('"')):
        value = value[1:-1]
    return re.sub(r"\s+", " ", value).strip()


def normalize_bibtex_fields(entry: dict[str, str]) -> dict[str, str]:
    normalized = dict(entry)

    doi = normalized.get("doi", "").strip()
    if doi:
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"^doi:\s*", "", doi, flags=re.IGNORECASE)
        normalized["doi"] = doi.strip().lower()

    if "pages" in normalized:
        pages = normalized["pages"].strip()
        pages = pages.replace("—", "-").replace("–", "-")
        pages = re.sub(r"\s*--+\s*", "--", pages)
        pages = re.sub(r"(?<!-)\s*-\s*(?!-)", "--", pages)
        normalized["pages"] = pages

    if "url" in normalized:
        normalized["url"] = normalized["url"].strip()

    if "publisher" in normalized:
        publisher = re.sub(r"\s+", " ", normalized["publisher"]).strip()
        publisher_aliases = {
            "association for computing machinery": "ACM",
            "acm": "ACM",
            "ieee": "IEEE",
            "ieee computer society": "IEEE Computer Society",
            "springer": "Springer",
            "springer nature": "Springer Nature",
            "elsevier": "Elsevier",
        }
        normalized["publisher"] = publisher_aliases.get(publisher.lower(), publisher)

    return normalized


def rekey_bibtex_entry(text: str, citation_key: str) -> str:
    match = ENTRY_RE.search(text.strip())
    if not match:
        raise ValueError("Could not parse BibTeX entry")
    return f"@{match.group('type')}{{{citation_key},{match.group('body')}}}\n"


def split_bibtex_entries(text: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"@\s*\w+\s*\{", text)]
    if not starts:
        return []
    entries: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        entries.append(text[start:end].strip())
    return entries


def _parse_string_macro(entry_text: str) -> tuple[str, str] | None:
    match = re.search(r"@\s*string\s*\{(?P<body>.*)\}\s*$", entry_text.strip(), re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    fields = _parse_fields(match.group("body"))
    if not fields:
        return None
    key, value = next(iter(fields.items()))
    return key.lower(), value


def parse_bibtex_file(text: str) -> dict[str, dict[str, str]]:
    parsed: dict[str, dict[str, str]] = {}
    string_macros: dict[str, str] = {}
    for entry_text in split_bibtex_entries(text):
        kind = re.match(r"@\s*(\w+)", entry_text)
        entry_kind = kind.group(1).lower() if kind else ""
        if entry_kind == "string":
            macro = _parse_string_macro(entry_text)
            if macro:
                string_macros[macro[0]] = macro[1]
            continue
        if entry_kind in {"comment", "preamble"}:
            continue
        entry = parse_bibtex_entry(entry_text)
        entry.update(_parse_fields(ENTRY_RE.search(entry_text.strip()).group("body"), string_macros))  # type: ignore[union-attr]
        entry = normalize_bibtex_fields(entry)
        parsed[entry["citation_key"]] = entry
    return parsed
