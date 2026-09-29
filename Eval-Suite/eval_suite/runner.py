"""Run selected cases against RespondService."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from infra.conversation_media import delete_user_media
from infra.llm.gemini.embeddings import GeminiEmbeddingClient
from infra.llm.gemini.runtime import GeminiRuntime
from infra.llm.oai.runtime import OpenAIRuntime
from infra.platform.graph import GraphClient
from infra.skills import SkillLibrary
from text_agent.app.src.services import RespondService

from .cases import select_cases
from .checks import (
    attachment_names,
    case_status,
    check_attachment_contains,
    check_attachments_live,
    check_turn,
)
from .constants import EVAL_TIMEOUT_SECONDS
from .documents import EvalDocuments
from .ledger import assistant_rows, trace_rows, user_row
from .media import EvalMediaBucket
from .report import write_reports
from .types import EvalCase, EvalCaseResult, EvalRunResult, EvalTurnResult
from .users import EvalUsers

SUITE_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = SUITE_ROOT / "scratch"
REPORTS_ROOT = SUITE_ROOT / "reports"


def now_ms() -> int:
    """The current time in epoch milliseconds.

    Args:
        None.
    Returns:
        The current Unix time in milliseconds.
    Raises:
        None.
    """
    return int(time.time() * 1000)


def require_env(name: str) -> str:
    """The named env var's value.

    Args:
        name: the environment variable to read.
    Returns:
        Its stripped value.
    Raises:
        KeyError: name isn't set at all.
        RuntimeError: name is set but blank.
    """
    value = os.environ[name]
    if not value.strip():
        raise RuntimeError(f"{name} is empty")
    return value


def _open_runtimes():
    """Open the OpenAI, Gemini, and Neo4j clients a run closes later.

    Args:
        None.
    Returns:
        The OpenAI runtime, Gemini runtime, and graph client.
    Raises:
        None.
    """
    openai = OpenAIRuntime(require_env("OPENAI_API_KEY"))
    gemini = GeminiRuntime(require_env("GEMINI_API_KEY"))
    graph = GraphClient(
        require_env("NEO4J_URI"),
        require_env("NEO4J_USER"),
        require_env("NEO4J_PASSWORD"),
    )
    return openai, gemini, graph


async def _build_service():
    """Construct RespondService and the real collaborators a run needs to close
    after.

    Args:
        None.
    Returns:
        The RespondService, EvalUsers, media bucket, OpenAI runtime, Gemini
        runtime, and graph client.
    Raises:
        None.
    """
    users = EvalUsers()
    bucket = EvalMediaBucket(SCRATCH_ROOT)
    documents = EvalDocuments(bucket)
    openai, gemini, graph = _open_runtimes()
    service = RespondService(
        openai,
        users,
        bucket,
        documents,
        SkillLibrary.load(),
        graph,
        GeminiEmbeddingClient(gemini),
    )
    return service, users, bucket, openai, gemini, graph


def _tally(results: list[EvalCaseResult]) -> dict[str, int]:
    """How many cases landed in each status.

    Args:
        results: every case's result from this run.
    Returns:
        Counts keyed by "pass", "fail", "xfail", "xpass".
    Raises:
        None.
    """
    counts = dict.fromkeys(("pass", "fail", "xfail", "xpass"), 0)
    for result in results:
        counts[result.status] += 1
    return counts


async def _close_runtimes(openai, gemini, graph) -> None:
    """Close the clients opened for one eval run.

    Args:
        openai: the OpenAI runtime to close.
        gemini: the Gemini runtime to close.
        graph: the graph client to close.
    Returns:
        None.
    Raises:
        None.
    """
    await openai.close()
    await gemini.close()
    await graph.close()


def _run_result(
    run_id: str, started: float, results: list[EvalCaseResult]
) -> EvalRunResult:
    """Assemble the run result from its id, start time, and case results.

    Args:
        run_id: the timestamp id of this run.
        started: perf_counter() reading taken before the cases ran.
        results: every case's result from this run.
    Returns:
        The EvalRunResult, including status counts and duration.
    Raises:
        None.
    """
    return EvalRunResult(
        run_id=run_id,
        duration_ms=int((time.perf_counter() - started) * 1000),
        counts=_tally(results),
        results=results,
    )


async def run(ids: list[str], tags: set[str]) -> EvalRunResult:
    """Run the selected cases against a real RespondService and write reports.

    Args:
        ids: exact case ids to run (empty means no id filter).
        tags: cases must carry every one of these tags.
    Returns:
        The full run result (counts, per-case results, timing).
    Raises:
        SystemExit: at least one case failed or unexpectedly passed (xpass).
    """
    cases = select_cases(ids, tags)
    service, users, bucket, openai, gemini, graph = await _build_service()
    started = time.perf_counter()
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    results: list[EvalCaseResult] = []
    try:
        for case in cases:
            results.append(await _run_case(service, users, bucket, case))
    finally:
        await _close_runtimes(openai, gemini, graph)
    run_result = _run_result(run_id, started, results)
    write_reports(REPORTS_ROOT, run_result)
    if run_result.counts["fail"] or run_result.counts["xpass"]:
        raise SystemExit(1)
    return run_result


def _failed_turn_result(
    turn, started: float, error: str, hard_message: str
) -> EvalTurnResult:
    """A turn result for a respond() call that timed out or raised.

    Args:
        turn: the turn that failed.
        started: perf_counter() reading taken before the call.
        error: short machine-readable failure tag stored on the result.
        hard_message: the human-readable hard failure line.
    Returns:
        An unfinished EvalTurnResult with no contents or actions.
    Raises:
        None.
    """
    return EvalTurnResult(
        prompt=turn.prompt,
        finished=False,
        latency_ms=int((time.perf_counter() - started) * 1000),
        modalities=[],
        contents=[],
        actions=[],
        hard=[hard_message],
        review=turn.review,
        error=error,
    )


async def _live_attachment_failures(
    bucket, user, thread_key, names, expect
) -> list[str]:
    """Hard failures from live-attachment checks, or [] if the turn didn't ask
    for them.

    Args:
        bucket: the media bucket the attachments were written to.
        user: the profile the turn ran as.
        thread_key: the eval thread the attachments were written under.
        names: attachment names the turn's response actually produced.
        expect: the turn's Expect, whose .attachments may require
            liveness/contains checks.
    Returns:
        Every hard failure line from the live/contains checks.
    Raises:
        None.
    """
    if not (expect.attachments and expect.attachments.live):
        return []
    hard = list(
        await check_attachments_live(bucket, user.userId, thread_key, names)
    )
    if not hard and expect.attachments.contains:
        hard.extend(
            await check_attachment_contains(
                bucket,
                user.userId,
                thread_key,
                names,
                expect.attachments.contains,
            )
        )
    return hard


def _append_turn_rows(
    rows, response, turn_id: str, created_at_ms: int
) -> tuple[list, list]:
    """Append trace and assistant rows, and dump contents and actions.

    Args:
        rows: the transcript rows built up so far; appended to in place.
        response: the RespondService.respond() return value.
        turn_id: this turn's transcript-row id.
        created_at_ms: this turn's creation timestamp.
    Returns:
        (contents, actions) dumped as JSON-mode dicts.
    Raises:
        None.
    """
    rows.extend(
        row
        for action in response.actions
        for row in trace_rows(action, turn_id, created_at_ms)
    )
    rows.extend(
        assistant_rows(
            response.contents,
            turn_id,
            response.thought.responseId,
            created_at_ms,
        )
    )
    contents = [item.model_dump(mode="json") for item in response.contents]
    actions = [item.model_dump(mode="json") for item in response.actions]
    return contents, actions


def _assembled_turn(
    turn, started, contents, actions, hard, soft
) -> EvalTurnResult:
    """Assemble a finished turn result from resolved contents, actions, and
    checks.

    Args:
        turn: the turn that produced the response.
        started: perf_counter() reading taken before the respond() call.
        contents: dumped response contents.
        actions: dumped response actions.
        hard: hard check failures.
        soft: soft check failures.
    Returns:
        The finished EvalTurnResult.
    Raises:
        None.
    """
    return EvalTurnResult(
        prompt=turn.prompt,
        finished=True,
        latency_ms=int((time.perf_counter() - started) * 1000),
        modalities=[message.get("type", "") for message in contents],
        contents=contents,
        actions=actions,
        hard=hard,
        soft=soft,
        review=turn.review,
    )


async def _finish_turn(
    response,
    turn,
    case: EvalCase,
    bucket: EvalMediaBucket,
    user,
    thread_key: str,
    rows: list,
    seen: set[str],
    turn_id: str,
    created_at_ms: int,
    started: float,
) -> EvalTurnResult:
    """Build a finished turn's result from a successful respond() call.

    Args:
        response: the RespondService.respond() return value.
        turn: the turn that produced response.
        case: the case this turn belongs to.
        bucket: the media bucket backing this case's attachments.
        user: the case's cloned user profile.
        thread_key: this case's eval thread key.
        rows: the transcript rows built up so far; appended to in place.
        seen: attachment names seen so far; updated in place.
        turn_id: this turn's transcript-row id.
        created_at_ms: this turn's creation timestamp.
        started: perf_counter() reading taken before the respond() call.
    Returns:
        The finished EvalTurnResult, contents/actions/checks all resolved.
    Raises:
        None.
    """
    contents, actions = _append_turn_rows(
        rows, response, turn_id, created_at_ms
    )
    hard, soft = check_turn(contents, actions, turn.expect, case.waive, seen)
    names = attachment_names(contents)
    hard.extend(
        await _live_attachment_failures(
            bucket, user, thread_key, names, turn.expect
        )
    )
    seen.update(names)
    return _assembled_turn(turn, started, contents, actions, hard, soft)


async def _respond_or_fail(service, user, thread_key, rows, turn, started):
    """Call respond() and turn a timeout or exception into a failed turn result.

    Args:
        service: the real RespondService under test.
        user: the case's cloned user profile.
        thread_key: this case's eval thread key.
        rows: the transcript rows built up so far.
        turn: the turn to run.
        started: perf_counter() reading taken before the respond() call.
    Returns:
        (response, failed). failed is an EvalTurnResult when respond() timed out
        or raised; otherwise None, and response is the successful reply.
    Raises:
        None.
    """
    try:
        async with asyncio.timeout(EVAL_TIMEOUT_SECONDS):
            response = await service.respond(user, thread_key, rows)
    except TimeoutError:
        return None, _failed_turn_result(
            turn, started, "timeout", "turn timed out"
        )
    except Exception as exc:
        message = f"respond() raised {type(exc).__name__}: {exc}"
        failed = _failed_turn_result(
            turn, started, f"{type(exc).__name__}: {exc}", message
        )
        return None, failed
    return response, None


async def _run_turn(
    service: RespondService,
    bucket: EvalMediaBucket,
    user,
    case: EvalCase,
    thread_key: str,
    rows: list,
    seen: set[str],
    index: int,
    turn,
) -> tuple[EvalTurnResult, bool]:
    """Run one turn against the real service.

    Args:
        service: the real RespondService under test.
        bucket: the media bucket backing this case's attachments.
        user: the case's cloned user profile.
        case: the case this turn belongs to.
        thread_key: this case's eval thread key.
        rows: the transcript rows built up so far; appended to in place.
        seen: attachment names seen so far; updated in place.
        index: this turn's 1-based position in the case.
        turn: the turn to run.
    Returns:
        (result, stop) — stop is True only when respond() itself timed out or
        raised, the same condition that ends the case's turn loop early.
    Raises:
        None.
    """
    turn_id = f"{case.id}-{index}"
    created_at_ms = now_ms()
    rows.append(user_row(turn.prompt, turn_id, created_at_ms))
    started = time.perf_counter()
    response, failed = await _respond_or_fail(
        service, user, thread_key, rows, turn, started
    )
    if failed is not None:
        return failed, True

    result = await _finish_turn(
        response,
        turn,
        case,
        bucket,
        user,
        thread_key,
        rows,
        seen,
        turn_id,
        created_at_ms,
        started,
    )
    return result, False


async def _run_all_turns(
    service, bucket, user, case: EvalCase, thread_key: str
) -> list[EvalTurnResult]:
    """Run every turn in case in order, stopping early if one times out or
    raises.

    Args:
        service: the real RespondService under test.
        bucket: the media bucket backing this case's attachments.
        user: the case's cloned user profile.
        case: the case whose turns to run.
        thread_key: this case's eval thread key.
    Returns:
        One EvalTurnResult per turn actually run.
    Raises:
        None.
    """
    rows: list = []
    seen: set[str] = set()
    turns: list[EvalTurnResult] = []
    for index, turn in enumerate(case.turns, start=1):
        result, stop = await _run_turn(
            service, bucket, user, case, thread_key, rows, seen, index, turn
        )
        turns.append(result)
        if stop:
            break
    return turns


def _judged_case(
    case: EvalCase, turns: list[EvalTurnResult], before, after
) -> EvalCaseResult:
    """Judge a finished case from its turns and profile snapshots.

    Args:
        case: the case that was run.
        turns: the turns actually run.
        before: the profile snapshot taken before the turns.
        after: the profile snapshot taken after the turns.
    Returns:
        The case's judged result (status, failures, per-turn detail).
    Raises:
        None.
    """
    failures = [line for item in turns for line in item.hard]
    if case.profile_unchanged and before != after:
        failures.append(f"profile changed: {before} -> {after}")
    status = case_status(failures, case.known_red)
    return EvalCaseResult(
        case_id=case.id,
        tags=case.tags,
        status=status,
        known_red=case.known_red,
        latency_ms=sum(item.latency_ms for item in turns),
        failures=failures,
        soft=[line for item in turns for line in item.soft],
        turns=turns,
    )


async def _run_case(
    service: RespondService,
    users: EvalUsers,
    bucket: EvalMediaBucket,
    case: EvalCase,
) -> EvalCaseResult:
    """Run one case end to end: clone its user, run every turn, judge the
    outcome.

    Args:
        service: the real RespondService under test.
        users: the eval user directory (clone/get/drop).
        bucket: the media bucket backing this run's attachments.
        case: the case to run.
    Returns:
        The case's judged result (status, failures, per-turn detail).
    Raises:
        None.
    """
    user = users.clone(case.id, case.user_id)
    await delete_user_media(bucket, user.userId)
    before = user.model_dump(mode="json", include={"name", "scope"})
    thread_key = f"eval-{case.id}"
    after = before
    try:
        turns = await _run_all_turns(service, bucket, user, case, thread_key)
        after = (await users.get_user(user.userId)).model_dump(
            mode="json", include={"name", "scope"}
        )
    finally:
        users.drop(user.userId)
        await delete_user_media(bucket, user.userId)

    return _judged_case(case, turns, before, after)
