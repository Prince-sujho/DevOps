"""Unit tests for checks.py. Synthetic contents and actions. No network."""

from __future__ import annotations

import pytest

from eval_suite.checks import check_attachments_live, check_turn
from eval_suite.media import EvalMediaBucket
from eval_suite.types import Attachments, Expect, Stack


def _grade(
    contents: list[dict],
    expect: Expect,
    waive: set[str] | None = None,
    earlier: set[str] | None = None,
    actions: list[dict] | None = None,
) -> tuple[list[str], list[str]]:
    """check_turn with convenient defaults for the tests in this file.

    Args:
        contents: the turn's raw content messages.
        expect: the turn's expected shape.
        waive: universal-check names to skip; defaults to none.
        earlier: attachment names seen in earlier turns; defaults to none.
        actions: the turn's tool-call rounds; defaults to none.
    Returns:
        (hard, soft) failure lines, exactly as check_turn returns them.
    Raises:
        None.
    """
    return check_turn(
        contents, actions or [], expect, waive or set(), earlier or set()
    )


def _hard(
    contents: list[dict],
    expect: Expect,
    waive: set[str] | None = None,
    earlier: set[str] | None = None,
    actions: list[dict] | None = None,
) -> list[str]:
    """_grade's hard failures only.

    Args:
        contents: the turn's raw content messages.
        expect: the turn's expected shape.
        waive: universal-check names to skip; defaults to none.
        earlier: attachment names seen in earlier turns; defaults to none.
        actions: the turn's tool-call rounds; defaults to none.
    Returns:
        The hard failure lines.
    Raises:
        None.
    """
    hard, _soft = _grade(contents, expect, waive, earlier, actions)
    return hard


def test_missing_document_fails() -> None:
    """No document attachment at all fails the min stem-count check.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "Sure, here you go."}],
        Expect(attachments=Attachments()),
    )
    assert any("stem" in failure for failure in failures)


def test_wrong_suffix_fails() -> None:
    """A .docx attachment fails a suffix=.pptx expectation.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "document", "filename": "paper.docx", "caption": "Paper"}
    ]
    failures = _hard(contents, Expect(attachments=Attachments(suffix=".pptx")))
    assert any("expected a .pptx" in failure for failure in failures)


def test_pdf_among_office_files_passes_suffix() -> None:
    """A .pdf among the attachments satisfies a suffix=.pdf expectation.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "document", "filename": "paper.docx", "caption": "Paper"},
        {"type": "document", "filename": "paper.pdf", "caption": "PDF"},
    ]
    assert _hard(contents, Expect(attachments=Attachments(suffix=".pdf"))) == []


def test_devanagari_reply_passes_hindi_check() -> None:
    """Hindi (Devanagari) text passes a script=devanagari expectation.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    assert (
        _hard(
            [{"type": "text", "text": "यह उत्तर है।"}],
            Expect(script="devanagari"),
        )
        == []
    )


def test_english_reply_fails_hindi_check() -> None:
    """English text fails a script=devanagari expectation.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "Here is the answer."}],
        Expect(script="devanagari"),
    )
    assert any("devanagari ratio" in failure for failure in failures)


def test_ends_with_prompt_accepts_a_question() -> None:
    """A turn ending in a question satisfies ends_with_prompt, no soft note.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    hard, soft = _grade(
        [{"type": "text", "text": "Which chapter do you mean?"}],
        Expect(ends_with_prompt=True),
    )
    assert hard == []
    assert soft == []


def test_ends_with_prompt_rejects_a_statement() -> None:
    """A turn ending in a statement is a soft (not hard) ends_with_prompt miss.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    hard, soft = _grade(
        [{"type": "text", "text": "Here is the summary."}],
        Expect(ends_with_prompt=True),
    )
    assert hard == []
    assert any("does not end with" in note for note in soft)


def test_pdf_claim_without_a_pdf_fails() -> None:
    """Claiming PDF delivery in text without a .pdf attachment is a hard
    failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "text", "text": "Here's your PDF!"},
        {"type": "document", "filename": "paper.docx", "caption": "Paper"},
    ]
    failures = _hard(contents, Expect())
    assert any("claims .pdf delivery" in failure for failure in failures)


def test_two_forms_in_one_turn_fails() -> None:
    """Two form messages in one turn is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "form", "body": "b", "requestText": "r"},
        {"type": "form", "body": "b", "requestText": "r"},
    ]
    failures = _hard(contents, Expect())
    assert any("2 forms" in failure for failure in failures)


def test_fixture_institution_leak_fails() -> None:
    """Naming the fixture institution in reply text is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "I'm built for Eval School students."}],
        Expect(),
    )
    assert any("fixture institution leak" in failure for failure in failures)


def test_fixture_userid_leak_fails() -> None:
    """Naming a fixture eval user id in reply text is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [
            {
                "type": "text",
                "text": "Your id is eval-student-grade-6-math, right?",
            }
        ],
        Expect(),
    )
    assert any("fixture userId leak" in failure for failure in failures)


def test_ordinary_name_is_not_flagged_as_a_leak() -> None:
    """An ordinary name isn't mistaken for a fixture-id leak.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    assert (
        _hard([{"type": "text", "text": "Great work, Vihaan!"}], Expect()) == []
    )


def test_tool_name_leak_fails() -> None:
    """Naming a real tool in reply text is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "Let me call create_document for you."}],
        Expect(),
    )
    assert any("tool name leak" in failure for failure in failures)


def test_create_image_leak_fails() -> None:
    """Naming create_image in reply text is a hard tool-name-leak failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "I will use create_image now."}], Expect()
    )
    assert any("tool name leak" in failure for failure in failures)


def test_waived_rule_does_not_fail() -> None:
    """A universal check named in waive doesn't fail the turn.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    assert (
        _hard(
            [
                {
                    "type": "text",
                    "text": "See https://example.com for the source.",
                }
            ],
            Expect(),
            waive={"raw url in chat text"},
        )
        == []
    )


def test_text_matches_miss_is_soft_not_hard() -> None:
    """A missed text_matches pattern is a soft failure, not hard.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    hard, soft = _grade(
        [{"type": "text", "text": "The volume is a^3/3."}],
        Expect(text_matches=[r"a³/9|a\^3/9"]),
    )
    assert hard == []
    assert any("missing required pattern" in note for note in soft)


def test_text_forbidden_hit_is_soft_not_hard() -> None:
    """A matched text_forbidden pattern is a soft failure, not hard.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    hard, soft = _grade(
        [{"type": "text", "text": "Correct, 50 is right."}],
        Expect(text_forbidden=[r"(?i)(correct|right|well done)[^.]{0,20}50"]),
    )
    assert hard == []
    assert any("forbidden pattern" in note for note in soft)


def test_forbidden_tool_in_actions_is_hard() -> None:
    """Calling a tools_none-forbidden tool is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    actions = [
        {
            "responseId": "r1",
            "items": [
                {
                    "type": "function_call",
                    "name": "create_document",
                    "call_id": "1",
                }
            ],
        }
    ]
    failures = _hard(
        [
            {
                "type": "text",
                "text": "I cannot open Excel files. What are the busy periods?",
            }
        ],
        Expect(stack=Stack(tools_none=["create_document"])),
        actions=actions,
    )
    assert any("forbidden tool" in failure for failure in failures)


def test_required_tool_error_output_is_hard() -> None:
    """A required tool call whose output looks like an error is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    actions = [
        {
            "responseId": "r1",
            "items": [
                {
                    "type": "function_call",
                    "name": "create_document",
                    "call_id": "c1",
                },
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": "error: renderer failed",
                },
            ],
        }
    ]
    failures = _hard(
        [{"type": "document", "filename": "a.docx", "caption": "Paper"}],
        Expect(
            attachments=Attachments(),
            stack=Stack(
                tools_any=["create_document"], required_tool_must_succeed=True
            ),
        ),
        actions=actions,
    )
    assert any("did not succeed" in failure for failure in failures)


def test_required_tool_success_is_clean() -> None:
    """A required tool call with a clean output produces no failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    actions = [
        {
            "responseId": "r1",
            "items": [
                {
                    "type": "function_call",
                    "name": "create_document",
                    "call_id": "c1",
                },
                {
                    "type": "function_call_output",
                    "call_id": "c1",
                    "output": '{"files": ["a.docx"]}',
                },
            ],
        }
    ]
    failures = _hard(
        [{"type": "document", "filename": "a.docx", "caption": "Paper"}],
        Expect(
            stack=Stack(
                tools_any=["create_document"], required_tool_must_succeed=True
            )
        ),
        actions=actions,
    )
    assert not any("did not succeed" in failure for failure in failures)


def test_crisis_digits_missing_is_hard() -> None:
    """Missing the required crisis-helpline pattern is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "text", "text": "Please talk to someone you trust."}],
        Expect(hard_text_matches=[r"14416|(?i:tele-?manas)|\b112\b"]),
    )
    assert any("missing required pattern" in failure for failure in failures)


def test_crisis_digits_present_are_hard_pass() -> None:
    """Including the crisis-helpline pattern passes the hard check.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    assert (
        _hard(
            [
                {
                    "type": "text",
                    "text": "Please call Tele-MANAS at 14416 or 112.",
                }
            ],
            Expect(hard_text_matches=[r"14416|(?i:tele-?manas)|\b112\b"]),
        )
        == []
    )


def test_word_count_bounds_are_hard() -> None:
    """Both word_count_min and word_count_max violations are hard failures.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [{"type": "text", "text": "one two three four five"}]
    too_short = _hard(contents, Expect(word_count_min=10))
    too_long = _hard(contents, Expect(word_count_max=3))
    assert any("expected >= 10" in failure for failure in too_short)
    assert any("expected <= 3" in failure for failure in too_long)


def test_forbidden_modality_is_hard() -> None:
    """A modalities_none-forbidden modality present is a hard failure.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    failures = _hard(
        [{"type": "document", "filename": "a.docx", "caption": "Paper"}],
        Expect(modalities_none=["document"]),
    )
    assert any("forbidden modality" in failure for failure in failures)


def test_fresh_attachment_rejects_repeat_name() -> None:
    """Re-sending an earlier attachment name fails a fresh=True expectation.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "document", "filename": "paper.docx", "caption": "Paper"}
    ]
    failures = _hard(
        contents,
        Expect(attachments=Attachments(fresh=True)),
        earlier={"paper.docx"},
    )
    assert any("re-sent an earlier file" in failure for failure in failures)


@pytest.mark.asyncio
async def test_live_file_accepts_existing(tmp_path) -> None:
    """check_attachments_live passes when tmp_path's bucket already has the
    file.

    Args:
        tmp_path: pytest temporary directory used as the bucket root.
    Returns:
        None.
    Raises:
        None.
    """
    bucket = EvalMediaBucket(tmp_path)
    object_name = "users/u/threads/t/files/paper.docx"
    await bucket.upload(
        object_name, b"PK\x03\x04not-empty", "application/octet-stream"
    )
    assert await check_attachments_live(bucket, "u", "t", ["paper.docx"]) == []


@pytest.mark.asyncio
async def test_live_file_rejects_missing(tmp_path) -> None:
    """check_attachments_live fails when tmp_path's bucket lacks the file.

    Args:
        tmp_path: pytest temporary directory used as the bucket root.
    Returns:
        None.
    Raises:
        None.
    """
    bucket = EvalMediaBucket(tmp_path)
    failures = await check_attachments_live(bucket, "u", "t", ["missing.docx"])
    assert any("attachment missing" in failure for failure in failures)


@pytest.mark.asyncio
async def test_empty_upload_is_refused(tmp_path) -> None:
    """Uploading empty bytes into tmp_path's bucket raises.

    Args:
        tmp_path: pytest temporary directory used as the bucket root.
    Returns:
        None.
    Raises:
        None.
    """
    bucket = EvalMediaBucket(tmp_path)
    with pytest.raises(ValueError, match="empty upload"):
        await bucket.upload(
            "users/u/threads/t/files/empty.docx",
            b"",
            "application/octet-stream",
        )


def test_soft_wording_does_not_hard_arm() -> None:
    """Only-soft Expect fields (text_matches/forbidden, ends_with_prompt) don't
    hard-arm.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    expect = Expect(
        text_matches=[r"hello"], text_forbidden=[r"bye"], ends_with_prompt=True
    )
    assert not expect.hard_armed()


def test_docx_and_pdf_of_the_same_stem_are_one_file() -> None:
    """A .docx and .pdf sharing a stem count as one distinct file, not two.

    Args:
        None.
    Returns:
        None.
    Raises:
        None.
    """
    contents = [
        {"type": "document", "filename": "paper.docx", "caption": "Office"},
        {"type": "document", "filename": "paper.pdf", "caption": "PDF"},
    ]
    failures = _hard(contents, Expect(attachments=Attachments(min_count=2)))
    assert any("distinct file stem" in failure for failure in failures)


@pytest.mark.asyncio
async def _rendered_notes(tmp_path):
    """Render the class-notes docx into an eval bucket rooted at tmp_path.

    Args:
        tmp_path: pytest temporary directory used as the bucket root.
    Returns:
        (bucket, rendered file names).
    Raises:
        None.
    """
    from infra.clients.document_worker import DocumentSource
    from infra.conversation_media import ConversationMediaScope

    from eval_suite.documents import EvalDocuments

    bucket = EvalMediaBucket(tmp_path)
    documents = EvalDocuments(bucket)
    scope = ConversationMediaScope(user_id="u", thread_key="t")
    rendered = await documents.render(
        DocumentSource(
            title="Notes",
            filename="class-notes",
            markdown="Redox and gaseous state",
            format="docx",
        ),
        scope,
    )
    return bucket, rendered.files


async def test_live_file_must_contain_required_text(tmp_path) -> None:
    """check_attachment_contains matches rendered text in tmp_path's bucket, and
    reports a miss.

    Args:
        tmp_path: pytest temporary directory used as the bucket root.
    Returns:
        None.
    Raises:
        None.
    """
    from eval_suite.checks import check_attachment_contains

    bucket, files = await _rendered_notes(tmp_path)
    missing = await check_attachment_contains(
        bucket,
        "u",
        "t",
        files,
        Attachments(live=True, contains=[r"(?i)biomolecule"]).contains,
    )
    assert any("biomolecule" in failure for failure in missing)
    ok = await check_attachment_contains(
        bucket,
        "u",
        "t",
        files,
        Attachments(live=True, contains=[r"(?i)redox"]).contains,
    )
    assert ok == []
