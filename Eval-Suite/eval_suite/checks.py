"""Hard and soft checks over one turn's contents and actions."""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from pathlib import PurePosixPath

from .constants import (
    ATTACHMENT_TYPES,
    FORBIDDEN_IN_TEXT,
    FORMAT_CLAIMS,
    PROMPT_TYPES,
    SCRIPT_MIN_RATIO,
    SCRIPT_RANGES,
    TEXT_FIELDS,
    TRAILING_ORNAMENT,
)
from .media import EvalMediaBucket
from .types import Attachments, CaseStatus, Expect, KnownRed, Script, Stack

_XML_TAG = re.compile(r"<[^>]+>")


def visible_text(contents: list[dict]) -> str:
    parts: list[str] = []
    for message in contents:
        parts.extend(message[field] for field in TEXT_FIELDS if message.get(field))
        for row in [*message.get("buttons", []), *message.get("rows", [])]:
            parts.extend(row[field] for field in ("title", "description") if row.get(field))
    return "\n".join(parts)


def attachment_names(contents: list[dict]) -> list[str]:
    return [
        message["filename"]
        for message in contents
        if message.get("type") in ATTACHMENT_TYPES and message.get("filename")
    ]


def tool_names(actions: list[dict]) -> list[str]:
    names: list[str] = []
    for round in actions:
        for item in round.get("items", []):
            if item.get("type") == "function_call" and item.get("name"):
                names.append(item["name"])
    return names


def media_object(user_id: str, thread_key: str, filename: str) -> str:
    return f"users/{user_id}/threads/{thread_key}/files/{filename}"


def file_text(filename: str, data: bytes) -> str:
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in {".docx", ".pptx"}:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = b"\n".join(
                archive.read(name) for name in archive.namelist() if name.endswith(".xml")
            )
        return _XML_TAG.sub(" ", xml.decode("utf-8"))
    return data.decode("utf-8", "replace")


def check_turn(
    contents: list[dict],
    actions: list[dict],
    expect: Expect,
    waive: set[str],
    earlier_names: set[str],
) -> tuple[list[str], list[str]]:
    types = [message.get("type", "") for message in contents]
    text = visible_text(contents)
    names = attachment_names(contents)
    hard = _universal(text, types, names, waive)

    if expect.modalities_any and not set(expect.modalities_any) & set(types):
        hard.append(f"expected one of {sorted(expect.modalities_any)}, got {types or ['nothing']}")
    banned = sorted(set(expect.modalities_none) & set(types))
    if banned:
        hard.append(f"forbidden modality present: {banned}")
    if expect.attachments:
        hard.extend(_attachment_failures(expect.attachments, names, earlier_names))
    if expect.script:
        hard.extend(_script_failures(text, expect.script))
    words = len(text.split())
    if expect.word_count_min is not None and words < expect.word_count_min:
        hard.append(f"expected >= {expect.word_count_min} words, got {words}")
    if expect.word_count_max is not None and words > expect.word_count_max:
        hard.append(f"expected <= {expect.word_count_max} words, got {words}")
    if expect.stack:
        hard.extend(_stack_failures(actions, expect.stack))
    for pattern in expect.hard_text_matches:
        if not pattern.search(text):
            hard.append(f"missing required pattern {pattern.pattern!r}")
    for pattern in expect.hard_text_forbidden:
        found = pattern.search(text)
        if found:
            hard.append(
                f"forbidden pattern {pattern.pattern!r} matched {found.group(0)[:80]!r}"
            )

    soft: list[str] = []
    for pattern in expect.text_matches:
        if not pattern.search(text):
            soft.append(f"missing required pattern {pattern.pattern!r}")
    for pattern in expect.text_forbidden:
        found = pattern.search(text)
        if found:
            soft.append(
                f"forbidden pattern {pattern.pattern!r} matched {found.group(0)[:80]!r}"
            )
    if expect.ends_with_prompt and not _ends_with_prompt(contents):
        soft.append("turn does not end with a tap control or a question")
    return hard, soft


def case_status(hard: list[str], known_red: KnownRed | None) -> CaseStatus:
    if not known_red:
        return "fail" if hard else "pass"
    matched = any(known_red.signature.search(line) for line in hard)
    return "xfail" if matched else "xpass"


async def check_attachments_live(
    bucket: EvalMediaBucket,
    user_id: str,
    thread_key: str,
    filenames: list[str],
) -> list[str]:
    failures: list[str] = []
    for filename in filenames:
        object_name = media_object(user_id, thread_key, filename)
        if not await bucket.exists(object_name):
            failures.append(f"attachment missing: {filename}")
    return failures


async def check_attachment_contains(
    bucket: EvalMediaBucket,
    user_id: str,
    thread_key: str,
    filenames: list[str],
    patterns: list[re.Pattern[str]],
) -> list[str]:
    blobs = [
        file_text(name, await bucket.download(media_object(user_id, thread_key, name)))
        for name in filenames
    ]
    text = "\n".join(blobs)
    failures: list[str] = []
    for pattern in patterns:
        if not pattern.search(text):
            failures.append(f"attachment missing required pattern {pattern.pattern!r}")
    return failures


def _suffix(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def _stem(filename: str) -> str:
    return PurePosixPath(filename).stem


def _universal(text: str, types: list[str], names: list[str], waive: set[str]) -> list[str]:
    failures: list[str] = []
    for name, pattern in FORBIDDEN_IN_TEXT.items():
        found = pattern.search(text)
        if found and name not in waive:
            failures.append(f"[{name}] matched {found.group(0)[:80]!r}")
    suffixes = {_suffix(name) for name in names}
    for suffix, pattern in FORMAT_CLAIMS.items():
        found = pattern.search(text)
        if found and suffix not in suffixes and "format lie" not in waive:
            failures.append(
                f"claims {suffix} delivery, attachments are "
                f"{sorted(suffixes) or 'none'}: {found.group(0)!r}"
            )
    forms = types.count("form")
    if forms > 1 and "double form" not in waive:
        failures.append(f"{forms} forms in one turn")
    return failures


def _attachment_failures(
    expect: Attachments, names: list[str], earlier_names: set[str]
) -> list[str]:
    stems = {_stem(name) for name in names}
    if len(stems) < expect.min_count:
        return [
            f"expected >= {expect.min_count} distinct file stem(s), "
            f"got {len(stems)}: {sorted(stems) or 'none'}"
        ]
    failures: list[str] = []
    if expect.suffix and not any(_suffix(name) == expect.suffix for name in names):
        got = [_suffix(name) or "?" for name in names]
        failures.append(f"expected a {expect.suffix} file, got {got}")
    if expect.fresh:
        repeats = sorted(set(names) & earlier_names)
        if repeats:
            failures.append(f"re-sent an earlier file instead of producing a new one: {repeats}")
    return failures


def _stack_failures(actions: list[dict], stack: Stack) -> list[str]:
    names = tool_names(actions)
    hard: list[str] = []
    if stack.tools_any and not set(stack.tools_any) & set(names):
        hard.append(f"expected one of tools {sorted(stack.tools_any)}, got {names or ['none']}")
    banned = sorted(set(stack.tools_none) & set(names))
    if banned:
        hard.append(f"forbidden tool called: {banned}")
    missing = sorted(set(stack.tools_all) - set(names))
    if missing:
        hard.append(f"required tools missing: {missing}")
    if stack.required_tool_must_succeed:
        calls = {
            item["call_id"]: item["name"]
            for round in actions
            for item in round.get("items", [])
            if item.get("type") == "function_call"
        }
        outputs = {
            item["call_id"]: item.get("output", "")
            for round in actions
            for item in round.get("items", [])
            if item.get("type") == "function_call_output"
        }
        wanted = set(stack.tools_any) | set(stack.tools_all)
        for call_id, name in calls.items():
            if name not in wanted:
                continue
            out = outputs.get(call_id, "")
            if not out or str(out).lower().startswith("error"):
                hard.append(f"tool {name} did not succeed: {str(out)[:80]!r}")
    return hard


def _ends_with_prompt(contents: list[dict]) -> bool:
    if not contents:
        return False
    last = contents[-1]
    if last.get("type") in PROMPT_TYPES:
        return True
    text = last.get("text") or ""
    return last.get("type") == "text" and TRAILING_ORNAMENT.sub("", text).endswith("?")


def _script_failures(text: str, script: Script) -> list[str]:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return [f"expected {script} text, found no letters at all"]
    ranges = SCRIPT_RANGES[script]
    hits = sum(1 for char in letters if any(low <= ord(char) <= high for low, high in ranges))
    ratio = hits / len(letters)
    if ratio < SCRIPT_MIN_RATIO:
        return [f"{script} ratio {ratio:.2f} < {SCRIPT_MIN_RATIO} ({hits}/{len(letters)} letters)"]
    return []
