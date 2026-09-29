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
    """The text a user would actually see across a turn's messages.

    Args:
        contents: the turn's raw content messages.
    Returns:
        Every text field and button/row title/description, newline-joined.
    Raises:
        None.
    """
    parts: list[str] = []
    for message in contents:
        parts.extend(
            message[field] for field in TEXT_FIELDS if message.get(field)
        )
        for row in [*message.get("buttons", []), *message.get("rows", [])]:
            parts.extend(
                row[field]
                for field in ("title", "description")
                if row.get(field)
            )
    return "\n".join(parts)


def attachment_names(contents: list[dict]) -> list[str]:
    """Every attachment filename across a turn's messages.

    Args:
        contents: the turn's raw content messages.
    Returns:
        Filenames of every message whose type is a known attachment type.
    Raises:
        None.
    """
    return [
        message["filename"]
        for message in contents
        if message.get("type") in ATTACHMENT_TYPES and message.get("filename")
    ]


def tool_names(actions: list[dict]) -> list[str]:
    """Every tool name actually called across a turn's action rounds.

    Args:
        actions: the turn's tool-call rounds.
    Returns:
        The name of every function_call item, in call order.
    Raises:
        None.
    """
    names: list[str] = []
    for round in actions:
        for item in round.get("items", []):
            if item.get("type") == "function_call" and item.get("name"):
                names.append(item["name"])
    return names


def media_object(user_id: str, thread_key: str, filename: str) -> str:
    """The GCS object name an attachment is stored under.

    Args:
        user_id: the eval user the attachment belongs to.
        thread_key: the eval thread the attachment was sent on.
        filename: the attachment's filename.
    Returns:
        The full object path, matching the real storage layout.
    Raises:
        None.
    """
    return f"users/{user_id}/threads/{thread_key}/files/{filename}"


def file_text(filename: str, data: bytes) -> str:
    """The readable text inside an attachment's bytes.

    Args:
        filename: the attachment's filename, used to pick the extraction path.
        data: the attachment's raw bytes.
    Returns:
        Concatenated XML text for .docx/.pptx (tags stripped); decoded text
        otherwise.
    Raises:
        zipfile.BadZipFile: filename claims .docx/.pptx but data isn't a valid
            zip.
    """
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix in {".docx", ".pptx"}:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = b"\n".join(
                archive.read(name)
                for name in archive.namelist()
                if name.endswith(".xml")
            )
        return _XML_TAG.sub(" ", xml.decode("utf-8"))
    return data.decode("utf-8", "replace")


def _modality_failures(types: list[str], expect: Expect) -> list[str]:
    """Hard failures for required and forbidden message modalities.

    Args:
        types: this turn's message types.
        expect: the turn's expected shape.
    Returns:
        Failure lines for a missing required modality or a present forbidden
        one.
    Raises:
        None.
    """
    hard: list[str] = []
    if expect.modalities_any and not set(expect.modalities_any) & set(types):
        hard.append(
            f"expected one of {sorted(expect.modalities_any)}, got {
                types or ['nothing']
            }"
        )
    banned = sorted(set(expect.modalities_none) & set(types))
    if banned:
        hard.append(f"forbidden modality present: {banned}")
    return hard


def _word_count_failures(text: str, expect: Expect) -> list[str]:
    """Hard failures for a turn's visible-text word count.

    Args:
        text: this turn's visible text.
        expect: the turn's expected shape.
    Returns:
        Failure lines when the word count is outside the expected range.
    Raises:
        None.
    """
    words = len(text.split())
    hard: list[str] = []
    if expect.word_count_min is not None and words < expect.word_count_min:
        hard.append(f"expected >= {expect.word_count_min} words, got {words}")
    if expect.word_count_max is not None and words > expect.word_count_max:
        hard.append(f"expected <= {expect.word_count_max} words, got {words}")
    return hard


def _shape_failures(
    types: list[str],
    text: str,
    names: list[str],
    actions: list[dict],
    expect: Expect,
    earlier_names: set[str],
) -> list[str]:
    """Hard failures for modality, attachments, script, and word count.

    Args:
        types: this turn's message types.
        text: this turn's visible text.
        names: this turn's attachment filenames.
        actions: this turn's tool-call rounds.
        expect: the turn's expected shape.
        earlier_names: attachment names seen in earlier turns.
    Returns:
        Failure lines for modality, attachments, script, and length.
    Raises:
        None.
    """
    hard = _modality_failures(types, expect)
    if expect.attachments:
        hard.extend(
            _attachment_failures(expect.attachments, names, earlier_names)
        )
    if expect.script:
        hard.extend(_script_failures(text, expect.script))
    hard.extend(_word_count_failures(text, expect))
    return hard


def _pattern_failures(
    text: str,
    required: list[re.Pattern[str]],
    forbidden: list[re.Pattern[str]],
) -> list[str]:
    """Failure lines for missing required patterns and present forbidden ones.

    Args:
        text: the text to search.
        required: patterns that must match.
        forbidden: patterns that must not match.
    Returns:
        One line per missing required pattern or matched forbidden pattern.
    Raises:
        None.
    """
    failures: list[str] = []
    for pattern in required:
        if not pattern.search(text):
            failures.append(f"missing required pattern {pattern.pattern!r}")
    for pattern in forbidden:
        found = pattern.search(text)
        if found:
            failures.append(
                f"forbidden pattern {pattern.pattern!r} matched {
                    found.group(0)[:80]!r
                }"
            )
    return failures


def _expect_hard_failures(
    types: list[str],
    text: str,
    names: list[str],
    actions: list[dict],
    expect: Expect,
    earlier_names: set[str],
) -> list[str]:
    """Hard failures against expect beyond the universal ones.

    Args:
        types: this turn's message types.
        text: this turn's visible text.
        names: this turn's attachment filenames.
        actions: this turn's tool-call rounds.
        expect: the turn's expected shape.
        earlier_names: attachment names seen in earlier turns (for freshness
            checks).
    Returns:
        Every hard failure line expect's rules produce.
    Raises:
        None.
    """
    hard = _shape_failures(types, text, names, actions, expect, earlier_names)
    if expect.stack:
        hard.extend(_stack_failures(actions, expect.stack))
    hard.extend(
        _pattern_failures(
            text, expect.hard_text_matches, expect.hard_text_forbidden
        )
    )
    return hard


def _expect_soft_failures(
    contents: list[dict], text: str, expect: Expect
) -> list[str]:
    """Soft (non-blocking) failures against expect.

    Args:
        contents: this turn's raw content messages.
        text: this turn's visible text.
        expect: the turn's expected shape.
    Returns:
        Every soft failure line expect's rules produce.
    Raises:
        None.
    """
    soft = _pattern_failures(text, expect.text_matches, expect.text_forbidden)
    if expect.ends_with_prompt and not _ends_with_prompt(contents):
        soft.append("turn does not end with a tap control or a question")
    return soft


def check_turn(
    contents: list[dict],
    actions: list[dict],
    expect: Expect,
    waive: set[str],
    earlier_names: set[str],
) -> tuple[list[str], list[str]]:
    """Judge one turn's contents and actions against its expected shape.

    Args:
        contents: this turn's raw content messages.
        actions: this turn's tool-call rounds.
        expect: the turn's expected shape.
        waive: universal-check names this case has opted out of.
        earlier_names: attachment names seen in earlier turns (for freshness
            checks).
    Returns:
        (hard, soft) failure lines. Any hard failure fails the case; soft is
        informational.
    Raises:
        None.
    """
    types = [message.get("type", "") for message in contents]
    text = visible_text(contents)
    names = attachment_names(contents)
    hard = _universal(text, types, names, waive)
    hard.extend(
        _expect_hard_failures(
            types, text, names, actions, expect, earlier_names
        )
    )
    soft = _expect_soft_failures(contents, text, expect)
    return hard, soft


def case_status(hard: list[str], known_red: KnownRed | None) -> CaseStatus:
    """Judge a case's final status from its accumulated hard failures.

    Args:
        hard: every hard failure line across all of the case's turns.
        known_red: the case's known-red signature, if it's marked as expected to
            fail.
    Returns:
        "pass"/"fail" for an ordinary case; "xfail"/"xpass" for a known-red one,
        depending on whether the known signature actually matched.
    Raises:
        None.
    """
    if not known_red:
        return "fail" if hard else "pass"
    matched = any(known_red.signature.search(line) for line in hard)
    return "xfail" if matched else "xpass"


async def check_attachments_live(
    bucket: EvalMediaBucket, user_id: str, thread_key: str, filenames: list[str]
) -> list[str]:
    """Confirm every claimed attachment actually exists in storage.

    Args:
        bucket: the eval media bucket to check against.
        user_id: the eval user the attachments belong to.
        thread_key: the eval thread the attachments were sent on.
        filenames: attachment filenames the turn's response claimed to send.
    Returns:
        One failure line per filename that isn't actually in the bucket.
    Raises:
        None.
    """
    failures: list[str] = []
    for filename in filenames:
        object_name = media_object(user_id, thread_key, filename)
        if not await bucket.exists(object_name):
            failures.append(f"attachment missing: {filename}")
    return failures


async def _joined_attachment_text(
    bucket: EvalMediaBucket,
    user_id: str,
    thread_key: str,
    filenames: list[str],
) -> str:
    """Download every attachment and join its readable text.

    Args:
        bucket: the eval media bucket to download attachments from.
        user_id: the eval user the attachments belong to.
        thread_key: the eval thread the attachments were sent on.
        filenames: attachment filenames to download.
    Returns:
        The attachments' text, newline-joined.
    Raises:
        None.
    """
    blobs = [
        file_text(
            name, await bucket.download(media_object(user_id, thread_key, name))
        )
        for name in filenames
    ]
    return "\n".join(blobs)


async def check_attachment_contains(
    bucket: EvalMediaBucket,
    user_id: str,
    thread_key: str,
    filenames: list[str],
    patterns: list[re.Pattern[str]],
) -> list[str]:
    """Confirm every required pattern appears somewhere across the attachments'
    text.

    Args:
        bucket: the eval media bucket to download attachments from.
        user_id: the eval user the attachments belong to.
        thread_key: the eval thread the attachments were sent on.
        filenames: attachment filenames to download and search.
        patterns: patterns that must each match somewhere in the combined text.
    Returns:
        One failure line per pattern that matched nowhere in the attachments.
    Raises:
        None.
    """
    text = await _joined_attachment_text(
        bucket, user_id, thread_key, filenames
    )
    failures: list[str] = []
    for pattern in patterns:
        if not pattern.search(text):
            failures.append(
                f"attachment missing required pattern {pattern.pattern!r}"
            )
    return failures


def _suffix(filename: str) -> str:
    """filename's lowercased extension, including the leading dot.

    Args:
        filename: the file name to inspect.
    Returns:
        The suffix (e.g. ".docx"), or "" if there is none.
    Raises:
        None.
    """
    return PurePosixPath(filename).suffix.lower()


def _stem(filename: str) -> str:
    """filename without its directory or extension.

    Args:
        filename: the file name to inspect.
    Returns:
        The bare stem.
    Raises:
        None.
    """
    return PurePosixPath(filename).stem


def _universal(
    text: str, types: list[str], names: list[str], waive: set[str]
) -> list[str]:
    """Hard failures every turn is checked against, regardless of what it
    expects.

    Args:
        text: this turn's visible text.
        types: this turn's message types.
        names: this turn's attachment filenames.
        waive: universal-check names this case has opted out of.
    Returns:
        Failure lines for forbidden text, mismatched format claims, and
        multiple forms in one turn — skipping any check named in waive.
    Raises:
        None.
    """
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


def _suffix_mismatch(expect: Attachments, names: list[str]) -> str | None:
    """The failure line when no attachment has the expected suffix.

    Args:
        expect: the expected attachment shape.
        names: this turn's attachment filenames.
    Returns:
        The failure line, or None when the suffix is unset or matched.
    Raises:
        None.
    """
    if not expect.suffix:
        return None
    if any(_suffix(name) == expect.suffix for name in names):
        return None
    got = [_suffix(name) or "?" for name in names]
    return f"expected a {expect.suffix} file, got {got}"


def _resend_failure(names: list[str], earlier_names: set[str]) -> str | None:
    """The failure line when a file name repeats an earlier turn.

    Args:
        names: this turn's attachment filenames.
        earlier_names: attachment names seen in earlier turns.
    Returns:
        The failure line, or None when nothing was re-sent.
    Raises:
        None.
    """
    repeats = sorted(set(names) & earlier_names)
    if not repeats:
        return None
    return (
        "re-sent an earlier file instead of producing a new one: "
        f"{repeats}"
    )


def _attachment_failures(
    expect: Attachments, names: list[str], earlier_names: set[str]
) -> list[str]:
    """Hard failures against a turn's attachment expectations.

    Args:
        expect: the expected attachment shape (min count, suffix, freshness).
        names: this turn's attachment filenames.
        earlier_names: attachment names seen in earlier turns.
    Returns:
        Failure lines for too few distinct files, a wrong suffix, or a
        re-sent (non-fresh) file when freshness was required.
    Raises:
        None.
    """
    stems = {_stem(name) for name in names}
    if len(stems) < expect.min_count:
        return [
            f"expected >= {expect.min_count} distinct file stem(s), "
            f"got {len(stems)}: {sorted(stems) or 'none'}"
        ]
    failures: list[str] = []
    mismatch = _suffix_mismatch(expect, names)
    if mismatch:
        failures.append(mismatch)
    if expect.fresh:
        resent = _resend_failure(names, earlier_names)
        if resent:
            failures.append(resent)
    return failures


def _tool_call_maps(actions: list[dict]) -> tuple[dict, dict]:
    """Map each function call's id to its tool name and recorded output.

    Args:
        actions: the turn's tool-call rounds.
    Returns:
        (calls, outputs) keyed by call_id.
    Raises:
        None.
    """
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
    return calls, outputs


def _required_tool_errors(actions: list[dict], stack: Stack) -> list[str]:
    """Hard failures for a required tool call whose output looks like an error.

    Args:
        actions: the turn's tool-call rounds.
        stack: the expected tool-call shape.
    Returns:
        One line per required tool call that did not succeed. Empty when the
        stack does not require success.
    Raises:
        None.
    """
    if not stack.required_tool_must_succeed:
        return []
    calls, outputs = _tool_call_maps(actions)
    wanted = set(stack.tools_any) | set(stack.tools_all)
    hard: list[str] = []
    for call_id, name in calls.items():
        if name not in wanted:
            continue
        out = outputs.get(call_id, "")
        if not out or str(out).lower().startswith("error"):
            hard.append(f"tool {name} did not succeed: {str(out)[:80]!r}")
    return hard


def _stack_failures(actions: list[dict], stack: Stack) -> list[str]:
    """Hard failures against a turn's expected tool-call shape.

    Args:
        actions: the turn's tool-call rounds.
        stack: the expected tool-call shape (required/forbidden/any-of tools,
            and whether a required tool's call must have succeeded).
    Returns:
        Failure lines for a missing required tool, a forbidden tool call, or
        a required tool call whose recorded output looks like an error.
    Raises:
        None.
    """
    names = tool_names(actions)
    hard: list[str] = []
    if stack.tools_any and not set(stack.tools_any) & set(names):
        hard.append(
            f"expected one of tools {sorted(stack.tools_any)}, got {
                names or ['none']
            }"
        )
    banned = sorted(set(stack.tools_none) & set(names))
    if banned:
        hard.append(f"forbidden tool called: {banned}")
    missing = sorted(set(stack.tools_all) - set(names))
    if missing:
        hard.append(f"required tools missing: {missing}")
    hard.extend(_required_tool_errors(actions, stack))
    return hard


def _ends_with_prompt(contents: list[dict]) -> bool:
    """Whether the turn ends on a tap control or a question, inviting a reply.

    Args:
        contents: the turn's raw content messages.
    Returns:
        True if the last message is a prompt-type control, or text ending in
        "?".
    Raises:
        None.
    """
    if not contents:
        return False
    last = contents[-1]
    if last.get("type") in PROMPT_TYPES:
        return True
    text = last.get("text") or ""
    return last.get("type") == "text" and TRAILING_ORNAMENT.sub(
        "", text
    ).endswith("?")


def _script_failures(text: str, script: Script) -> list[str]:
    """Hard failure if text isn't mostly written in the expected script.

    Args:
        text: this turn's visible text.
        script: the expected script (e.g. "devanagari").
    Returns:
        A single failure line if the ratio of matching-script letters falls
        below SCRIPT_MIN_RATIO (or there are no letters at all); [] otherwise.
    Raises:
        None.
    """
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return [f"expected {script} text, found no letters at all"]
    ranges = SCRIPT_RANGES[script]
    hits = sum(
        1
        for char in letters
        if any(low <= ord(char) <= high for low, high in ranges)
    )
    ratio = hits / len(letters)
    if ratio < SCRIPT_MIN_RATIO:
        return [
            f"{script} ratio {ratio:.2f} < {SCRIPT_MIN_RATIO} ({hits}/{
                len(letters)
            } letters)"
        ]
    return []
