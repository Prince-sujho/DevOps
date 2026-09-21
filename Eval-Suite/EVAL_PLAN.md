# Eval-Suite

New suite. Lives only in this folder. Do not edit `evals/`,
`eval-suite-strengthening-plan.md`, product packages, or git remotes.

Measured against `text_agent/app/src/services/respond.py` as it stands today.

---

## The situation in three lines

1. `tests/` proves pipes with a fake model. It cannot see a live reply, a live
   file, or whether a tool actually ran.
2. `evals/` is the old suite. The grader and 90 cases are on disk; the runner,
   types, fixtures, and `run_evals.py` are gone. Leave that folder alone.
3. This folder is the new exam: same `RespondService`, fake users, disk files,
   real OpenAI. Grade the reply. A crash message is not a pass.

---

## What this suite is

Black-box exam of `RespondService.respond`. Fake student or teacher. Ledger of
`TranscriptMessage` rows. Look at `GenerateResponse.contents` and
`GenerateResponse.actions`. Not WhatsApp. Not user-service persistence.

| | `tests/` | `Eval-Suite/` |
|---|---|---|
| Model | Fake | Real OpenAI |
| Question | Does the code match the spec? | Did this chat do the job? |
| Cadence | Every commit | Manual / weekly, costs money |

Never re-test HMAC, session gap, auth, cascade, Hubble. Those belong in
`tests/`.

---

## Product as it is (do not wrap)

Constructor — `text_agent/app/src/services/respond.py`:

```python
RespondService(
    runtime,          # OpenAIRuntime
    users,            # needs the methods below
    media_bucket,     # GcsBucket-shaped: upload, exists, delete_prefix, public_url
    documents,        # DocumentWorkerClient-shaped: render(document, scope)
    skills,           # SkillLibrary.load()
    graph,            # GraphClient, read-only
    embeddings,       # GeminiEmbeddingClient
)
```

Call:

```python
response = await service.respond(user, thread_key, rows)
# rows: list[TranscriptMessage], oldest first
# response.contents  — what to say (AgentMessage, reaction, sources)
# response.actions   — tool rounds already done
# response.readIds
# response.thought
# response.usage
```

Before anything else, `respond()` calls `users.get_enrollment_ids` and
`users.batch_get_users`. Missing those methods crash. That is correct.

Attachments are `filename`, not `url`. Liveness is the bucket object:

```
users/{userId}/threads/{threadKey}/files/{filename}
```

Tool names come off `FunctionCallItem` in `response.actions[*].items`.
There is no `trace` field and no `cta_url` modality. A web link is `type="url"`.

Cleanup is media only: `delete_user_media(bucket, user_id)`. Do not invent a
Neo4j `DETACH DELETE`.

---

## Rules

- Files only under `Eval-Suite/`.
- Fake `eval-…` users. Never a real person.
- Generated files on local disk. Production GCS is never written.
- Graph is read-only.
- One way to do each thing. A missing client or a wrong shape crashes at
  import or at the call. No default, no retry, no shim for the old harness.
- A check is never loosened to turn a bug into a pass.
- OpenAI steps wait for an explicit go. They cost money.

---

## Hard vs soft

**Hard** — the case fails. A live run with any `fail` or `xpass` exits 1.

- Turn finished (no timeout, no exception)
- Attachment count, suffix, `bucket.exists(object_name)`, new file on revise
- Always: secrecy leak, "here's your PDF" with no `.pdf`, two forms in one turn
- `script` ratio (Unicode ranges, not phrases)
- `modalities_any` / `modalities_none`
- Word bounds
- `profile_unchanged`
- Required / forbidden tool names; a required tool's output must not start
  with `error`
- Crisis digits `14416` / `112` when the case marks them hard

**Soft** — recorded. Never fails the case. Never exits 1 on one rephrase.

- `text_matches` / `text_forbidden`
- `ends_with_prompt`
- Human `review` lines

`known_red` is only for a **hard** product bug. Promotion: fix product →
`--case id` → `xpass` → delete the flag → `pass`.

---

## Layout

```
Eval-Suite/
  EVAL_PLAN.md          this file
  run.py                entry: --list / --tag / --case
  eval_suite/           importable package (the folder name cannot be one)
    types.py
    constants.py
    users.py
    media.py
    documents.py
    ledger.py
    checks.py
    runner.py
    report.py
    cases/
      helpers.py
      student.py
      teacher.py
  tests/
    conftest.py
    test_checks.py
    test_cases.py
    test_users.py
  scratch/              generated files
  reports/              run output
```

`combo.py` / `endurance.py` / gift-card minting wait until the 60-session exam is live.
Do not add a second fixtures module: `EVAL_USERS` lives in `users.py`.

---

## `types.py`

```python
"""Contracts for one eval case."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

Modality = Literal[
    "text", "image", "document", "buttons", "list",
    "url", "location_request", "contact", "gift_card", "form",
]
Script = Literal["latin", "devanagari", "kannada", "malayalam"]
CaseStatus = Literal["pass", "fail", "xfail", "xpass"]

EvalUserId = Literal[
    "eval-student-grade-6-math",
    "eval-student-grade-7-science",
    "eval-student-grade-8-social-science",
    "eval-student-grade-9-math",
    "eval-student-grade-9-social-science",
    "eval-student-grade-10-math",
    "eval-student-grade-10-science",
    "eval-student-grade-11-math",
    "eval-student-grade-12-math",
    "eval-student-grade-12-commerce",
    "eval-student-grade-12-accountancy",
    "eval-student-grade-12-humanities",
    "eval-student-grade-12-physics",
    "eval-teacher-grade-9-science",
    "eval-teacher-grade-9-social-science",
    "eval-teacher-grade-6-8-science",
    "eval-teacher-grade-9-10-math",
    "eval-teacher-grade-11-12-math",
    "eval-teacher-grade-11-12-physics",
    "eval-teacher-grade-11-12-commerce",
    "eval-teacher-grade-11-12-humanities",
]


class Attachments(BaseModel):
    min_count: int = 1
    suffix: Optional[str] = None
    live: bool = False
    fresh: bool = False


class Stack(BaseModel):
    tools_any: list[str] = Field(default_factory=list)
    tools_none: list[str] = Field(default_factory=list)
    tools_all: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherent(self) -> "Stack":
        overlap = (set(self.tools_any) | set(self.tools_all)) & set(self.tools_none)
        if overlap:
            raise ValueError(f"tool both required and forbidden: {sorted(overlap)}")
        return self


class Expect(BaseModel):
    modalities_any: list[Modality] = Field(default_factory=list)
    modalities_none: list[Modality] = Field(default_factory=list)
    attachments: Optional[Attachments] = None
    script: Optional[Script] = None
    word_count_min: Optional[int] = None
    word_count_max: Optional[int] = None
    stack: Optional[Stack] = None
    hard_text_matches: list[re.Pattern] = Field(default_factory=list)
    text_matches: list[re.Pattern] = Field(default_factory=list)
    text_forbidden: list[re.Pattern] = Field(default_factory=list)
    ends_with_prompt: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> "Expect":
        overlap = set(self.modalities_any) & set(self.modalities_none)
        if overlap:
            raise ValueError(f"modality both required and forbidden: {sorted(overlap)}")
        if self.attachments and {"document", "image"} & set(self.modalities_none):
            raise ValueError("attachments required while document/image forbidden")
        if (
            self.word_count_min is not None
            and self.word_count_max is not None
            and self.word_count_min > self.word_count_max
        ):
            raise ValueError("word_count_min > word_count_max")
        return self


class EvalTurn(BaseModel):
    prompt: str
    expect: Expect = Field(default_factory=Expect)
    review: list[str] = Field(default_factory=list)


class KnownRed(BaseModel):
    defect: str
    owner: Literal["prompt", "engineering", "accuracy"]
    signature: re.Pattern
    opened_on: date


class EvalCase(BaseModel):
    id: str
    user_id: EvalUserId
    tags: set[str]
    turns: list[EvalTurn] = Field(min_length=1)
    profile_unchanged: bool = False
    waive: set[str] = Field(default_factory=set)
    known_red: Optional[KnownRed] = None
```

`EvalUserId` and the fixture dict must match at import:

```python
assert set(EVAL_USERS) == set(get_args(EvalUserId))
```

---

## `users.py` — clone per case

`respond()` always calls `get_enrollment_ids` and `batch_get_users`. Profile
tools call `get_user` and `update_profile`. Ambassador tools call
`enroll_ambassador`, `get_ambassador_status`, `list_rewards`, `redeem_reward`.
Implement those methods. Do not add a silent extra method "in case".

```python
def clone(self, case_id: str, user_id: EvalUserId) -> UserProfile:
    isolated_id = f"{user_id}--{case_id}"
    clone = EVAL_USERS[user_id].model_copy(deep=True, update={"userId": isolated_id})
    self._users[isolated_id] = clone
    return clone

def drop(self, user_id: str) -> None:
    del self._users[user_id]

async def get_enrollment_ids(self, user_id: str) -> EnrollmentIdsResponse:
    return EnrollmentIdsResponse(teacherUserIds=[], studentUserIds=[])

async def batch_get_users(self, user_ids: list[str]) -> list[UserProfile]:
    return [self._users[user_id] for user_id in user_ids]
```

Id is `{user_id}--{case_id}` so a crashed run's leftovers are found by the
next run of the same case. Deep copy so nested `scope` is not shared.

`get_enrollment_ids` returns empty lists: eval users are not campus-linked
unless a case seeds them. Empty is a real answer, not a fallback.

---

## `media.py` — disk bucket

Same methods `ConversationMediaStore` calls. Files under
`Eval-Suite/scratch/{object_name}`.

```python
class EvalMediaBucket:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    async def upload(self, object_name: str, data: bytes, content_type: str) -> None:
        path = self._root / object_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def exists(self, object_name: str) -> bool:
        return (self._root / object_name).is_file()

    async def delete_prefix(self, prefix: str) -> int:
        base = self._root / prefix
        if not base.exists():
            return 0
        paths = [p for p in base.rglob("*") if p.is_file()]
        for path in paths:
            path.unlink()
        return len(paths)

    def public_url(self, object_name: str) -> str:
        return (self._root / object_name).resolve().as_uri()
```

Liveness never HTTP-gets. It calls `exists` on
`users/{userId}/threads/{threadKey}/files/{filename}`.

---

## `documents.py` — local render

The real document worker writes production GCS. This suite must not. One
local renderer, same `render(document, scope)` shape the tool calls.

Write `{filename}.{format}` plus a `.pdf` of the same stem into the eval
bucket under that scope. Return those filenames. Bytes must be real files of
that suffix (a valid zip-based `.docx` / `.pptx`, a real `%PDF` header). A
zero-byte placeholder is a fail waiting to happen.

---

## `ledger.py`

The runner holds the ledger. Before `respond()`, append the user row. After,
append tool rounds then speech — same order WhatsApp uses.

```python
def user_row(prompt: str, turn_id: str, created_at_ms: int) -> UserTranscriptMessage:
    return UserTranscriptMessage(
        createdAtMs=created_at_ms,
        turnId=turn_id,
        content=TextContent(text=prompt),
    )

def trace_rows(round: Round, turn_id: str, created_at_ms: int) -> list[TraceTranscriptMessage]:
    return [
        TraceTranscriptMessage(
            createdAtMs=created_at_ms,
            turnId=turn_id,
            responseId=round.responseId,
            content=item,
        )
        for item in round.items
    ]

def assistant_rows(
    contents: list[AssistantContent], turn_id: str, response_id: str | None, created_at_ms: int,
) -> list[AssistantTranscriptMessage]:
    return [
        AssistantTranscriptMessage(
            createdAtMs=created_at_ms,
            turnId=turn_id,
            responseId=response_id,
            content=content,
        )
        for content in contents
    ]
```

Photos and voice in a case are words in `prompt` (`[I sent a worksheet photo]`),
not uploads. Taps are `[tapped] id — Title`.

---

## `checks.py`

Visible text: every user-visible string on `contents` (dump with
`model_dump`). Attachment names: `filename` on `image` and `document`.

```python
def tool_names(actions: list[Round]) -> list[str]:
    names: list[str] = []
    for round in actions:
        for item in round.items:
            if isinstance(item, FunctionCallItem):
                names.append(item.name)
    return names

def check_turn(contents, actions, expect, waive, earlier_names) -> tuple[list[str], list[str]]:
    ...
```

Hard stack failures: `tools_any` / `tools_none` / `tools_all`, and for a
required tool a matching `FunctionCallOutputItem` whose `output` does not
start with `error`.

Live files: for each required filename, `await bucket.exists(object_name)`.
A missing object is a hard fail.

`case_status(hard, known_red)`: no flag → `fail` or `pass`; flag whose
signature matches a hard line → `xfail`; flag that did not match → `xpass`.

---

## `runner.py`

```python
async def _run_case(service, users, bucket, case: EvalCase) -> EvalCaseResult:
    user = users.clone(case.id, case.user_id)
    await delete_user_media(bucket, user.userId)
    before = user.model_dump(mode="json", include={"name", "scope"})
    thread_key = f"eval-{case.id}"
    rows: list[TranscriptMessage] = []
    seen: set[str] = set()
    turns: list[EvalTurnResult] = []
    try:
        for index, turn in enumerate(case.turns, start=1):
            turn_id = f"{case.id}-{index}"
            now = now_ms()
            rows.append(user_row(turn.prompt, turn_id, now))
            response = await service.respond(user, thread_key, rows)
            rows.extend(row for action in response.actions for row in trace_rows(action, turn_id, now))
            rows.extend(assistant_rows(response.contents, turn_id, response.thought.responseId, now))
            hard, soft = check_turn(response, turn.expect, case.waive, seen)
            names = attachment_names(response.contents)
            if turn.expect.attachments and turn.expect.attachments.live:
                hard += await check_attachments_live(bucket, user.userId, thread_key, names)
            seen.update(names)
            turns.append(...)
        after = (await users.get_user(user.userId)).model_dump(mode="json", include={"name", "scope"})
    finally:
        users.drop(user.userId)
        await delete_user_media(bucket, user.userId)

    hard = flatten(turns)
    if case.profile_unchanged and before != after:
        hard.append(f"profile changed: {before} -> {after}")
    ...
```

Wire `RespondService` with `EvalUsers`, `EvalMediaBucket`, `EvalDocuments`,
`SkillLibrary.load()`, the real `OpenAIRuntime`, real `GraphClient`, real
`GeminiEmbeddingClient`. No second constructor.

`run.py --list` builds every case and prints ids. No model call.
`--tag` / `--case` select. After reports: `fail` or `xpass` → `SystemExit(1)`.

Timeout per turn: 300s. Timed out → `finished=False` → hard fail.

---

## Corpus

Source chats (do not copy them into product):

| File | What |
|---|---|
| `Data/student-userbase-30.json` | 30 real student sessions |
| `Data/teacher-userbase-30.json` | 30 real teacher sessions |
| `Data/sujho-freeze-locked.json` | stricter ledger for late mines |

Write cases in `Eval-Suite/cases/`. Prompts from those transcripts. One
`Expect` that would have caught the real defect.

Minimum jobs the first corpus must hit:

- Student: onboarding, drill/test, homework, notes, plan, boundary, crash-retry,
  wrong final value, photo described in text, Hindi
- Teacher: worksheet, paper, notes, visual, deck/pptx, delivery "where is the
  file", PDF claimed / docx sent, unsupported xlsx/zip, nursery-scope, Kannada
- Combo: language × revise-same-file, voice-described × wrong answer
- Endurance: 14+ turn thread
- `gift_card` modality

A reply that only "did not crash" is not a pass on a delivery case.
`Expect(attachments=Attachments(live=True), stack=Stack(tools_any=["create_document"]))`
on the turn that must ship.

---

## Order of work

1. `types.py`, `constants.py`, `users.py`, `media.py`, `documents.py`,
   `ledger.py`. Import-time assert on fixture ids.
2. `checks.py` + `tests/test_checks.py`. No network. Fake `contents` / `actions`.
3. `cases/helpers.py` + one smoke case that builds.
4. `runner.py`, `report.py`, `run.py`. `--list` is the first honest green.
5. Write the live cases from `Data/`.
6. `pytest Eval-Suite/tests` — still no model.
7. **Stop.** Smoke 3–5 cases with OpenAI only after an explicit go.
8. Full run. Stamp `known_red` on confirmed **hard** product bugs. Do not
   invent flags. Do not loosen `Expect`.

---

## Done when

- `python Eval-Suite/run.py --list` prints every case.
- `pytest Eval-Suite/tests` is green with no network.
- A delivery case fails unless a real file exists on disk under that clone.
- A "here's your PDF" turn with a `.docx` is a hard fail with no case asking.
- Old `evals/` is unchanged.
