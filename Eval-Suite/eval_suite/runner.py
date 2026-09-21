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
    return int(time.time() * 1000)


def require_env(name: str) -> str:
    value = os.environ[name]
    if not value.strip():
        raise RuntimeError(f"{name} is empty")
    return value


async def run(ids: list[str], tags: set[str]) -> EvalRunResult:
    cases = select_cases(ids, tags)
    users = EvalUsers()
    bucket = EvalMediaBucket(SCRATCH_ROOT)
    documents = EvalDocuments(bucket)
    openai = OpenAIRuntime(require_env("OPENAI_API_KEY"))
    gemini = GeminiRuntime(require_env("GEMINI_API_KEY"))
    graph = GraphClient(
        require_env("NEO4J_URI"),
        require_env("NEO4J_USER"),
        require_env("NEO4J_PASSWORD"),
    )
    service = RespondService(
        openai,
        users,
        bucket,
        documents,
        SkillLibrary.load(),
        graph,
        GeminiEmbeddingClient(gemini),
    )
    started = time.perf_counter()
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    results: list[EvalCaseResult] = []
    try:
        for case in cases:
            results.append(await _run_case(service, users, bucket, case))
    finally:
        await openai.close()
        await gemini.close()
        await graph.close()
    counts = dict.fromkeys(("pass", "fail", "xfail", "xpass"), 0)
    for result in results:
        counts[result.status] += 1
    run_result = EvalRunResult(
        run_id=run_id,
        duration_ms=int((time.perf_counter() - started) * 1000),
        counts=counts,
        results=results,
    )
    write_reports(REPORTS_ROOT, run_result)
    if counts["fail"] or counts["xpass"]:
        raise SystemExit(1)
    return run_result


async def _run_case(
    service: RespondService,
    users: EvalUsers,
    bucket: EvalMediaBucket,
    case: EvalCase,
) -> EvalCaseResult:
    user = users.clone(case.id, case.user_id)
    await delete_user_media(bucket, user.userId)
    before = user.model_dump(mode="json", include={"name", "scope"})
    thread_key = f"eval-{case.id}"
    rows = []
    seen: set[str] = set()
    turns: list[EvalTurnResult] = []
    after = before
    try:
        for index, turn in enumerate(case.turns, start=1):
            turn_id = f"{case.id}-{index}"
            created_at_ms = now_ms()
            rows.append(user_row(turn.prompt, turn_id, created_at_ms))
            started = time.perf_counter()
            try:
                async with asyncio.timeout(EVAL_TIMEOUT_SECONDS):
                    response = await service.respond(user, thread_key, rows)
            except TimeoutError:
                turns.append(
                    EvalTurnResult(
                        prompt=turn.prompt,
                        finished=False,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        modalities=[],
                        contents=[],
                        actions=[],
                        hard=["turn timed out"],
                        review=turn.review,
                        error="timeout",
                    )
                )
                break
            except Exception as exc:
                turns.append(
                    EvalTurnResult(
                        prompt=turn.prompt,
                        finished=False,
                        latency_ms=int((time.perf_counter() - started) * 1000),
                        modalities=[],
                        contents=[],
                        actions=[],
                        hard=[f"respond() raised {type(exc).__name__}: {exc}"],
                        review=turn.review,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                break
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
            hard, soft = check_turn(contents, actions, turn.expect, case.waive, seen)
            names = attachment_names(contents)
            if turn.expect.attachments and turn.expect.attachments.live:
                missing = await check_attachments_live(
                    bucket, user.userId, thread_key, names
                )
                hard.extend(missing)
                if not missing and turn.expect.attachments.contains:
                    hard.extend(
                        await check_attachment_contains(
                            bucket,
                            user.userId,
                            thread_key,
                            names,
                            turn.expect.attachments.contains,
                        )
                    )
            seen.update(names)
            turns.append(
                EvalTurnResult(
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
            )
        after = (await users.get_user(user.userId)).model_dump(
            mode="json", include={"name", "scope"}
        )
    finally:
        users.drop(user.userId)
        await delete_user_media(bucket, user.userId)

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
