# Tests Upgrade Plan

Measured 2026-09-09 against `sujho@286397c`. Five steps, in order. Do not
reorder them — each one makes the next one measurable.

---

## The situation in three lines

1. `tests/` is **not in git**. 52 test files, 445 tests, 8 audit documents —
   none of it is committed anywhere. `git ls-files tests` returns 0.
2. So **CI has never run**. `.github/workflows/checks.yml` is untracked too.
   Nothing enforces anything.
3. So the tests drifted. The product moved on GitHub; the tests sat on one
   laptop with no feedback. Today 71 tests are switched off by 5 stale lines
   and nobody was told.

Everything below follows from those three lines.

---

## Already done — do not redo

Verified present on disk today.

| Thing | Evidence |
|---|---|
| Unit suite | `tests/unit/` — 143 tests |
| API suite | `tests/api/` — 242 tests |
| Integration suite | `tests/integration/` — 39 tests |
| E2E suite | `tests/e2e/` — 21 tests |
| Mutation testing | 98.05% killed, ratchet at 98.0% (`mutmut-cicd-stats.json`) |
| Quality gates | `tests/tooling/check_assertions.py`, `check_test_methods.py` |
| CI script | `tests/ci/pipeline.py` — 12 stages, written and working |
| Audit docs | 8 files in `tests/outcomes/` |
| MIRRORED/WRONG cleanup | done, changelog in `MIRRORED_AND_WRONG.md` |

The suite is well built. It is simply unplugged.

---

## Step 1 — Put it in git

Nothing else matters until this is done. Right now one disk failure loses
every test in the table above.

```bash
cd /Users/prince/Desktop/Sujho/sujho
git add tests/ pyproject.toml .github/ .secrets.baseline .pre-commit-config.yaml
git commit -m "tests: add suite, gate config, and CI workflows"
git push
```

Nothing is blocking this: `git check-ignore` confirms these paths are not
ignored, they were simply never added. A plain `git add` is all it takes.

**Done when:** `git ls-files tests | wc -l` is 52+, and GitHub Actions shows a
run.

---

## Step 2 — Fix 5 lines, get 71 tests back

Five stale references switch off 71 tests. Repair only the names. Change no
assertions.

| File | Wrong | Right |
|---|---|---|
| `tests/api/whatsapp_adapter/conftest.py:131` | `AppState(coordinator=…)` | `turns=` (a `TurnLoop`) |
| `tests/api/text_agent/conftest.py:33` | `RespondService(llm_client=…, image_client=…)` | `runtime=` (an `OpenAIRuntime`), drop `image_client` |
| `tests/integration/test_cross_service_contract.py:33` | `assistant_row` | `assistant_rows(contents, turn_id, response_id)` |
| `tests/unit/user_service/test_attribution.py:14` | `resolve_referrer` | `await resolve_attribution(texts, ad, referrers)` |
| `evals/checks.py:9` | `filename_from_url` | gone — use `ConversationMediaStore` |

**Done when:**

```bash
pytest tests/unit tests/api --collect-only -q   # 0 errors
```

Collection goes 445 → 472. Some recovered tests will fail; that is a result,
not a regression. Record them, do not silence them.

---

## Step 3 — Install Java, run the other 60 tests

39 integration + 21 e2e tests need the Firestore emulator, which needs a JRE.
`/usr/bin/java` here is the macOS stub, so these 60 tests have never run.

```bash
brew install --cask temurin
pytest tests/integration tests/e2e -q
```

Expect failures. They have had no feedback since they were written.

**Done when:** all 472 tests produce a pass or fail. None are unknown.

---

## Step 4 — Make the gates watch everything

Today every gate points at `user_service/app/src` — 701 of 7136 statements,
**9.8% of the product**. A pull request rewriting `whatsapp_adapter` or
`knowledge_store` passes all of them.

Two edits:

**`pyproject.toml`** — measure the whole product, not one folder:

```toml
[tool.coverage.run]
source = [
    "user_service/app/src",
    "whatsapp_adapter/app/src",
    "text_agent/app/src",
    "document_worker/src",
    "redirect_service/app/src",
    "knowledge_store",
    "infra",
]
```

**`tests/ci/pipeline.py`** — add the matching `--cov=` flags to `stage_unit`
and `stage_coverage`.

Set each component's `fail_under` to the number it actually measures after
Steps 2 and 3, then raise them over time. Do not set aspirational numbers.

Add one small gate — the cheapest thing in this plan, and the one that would
have caught today's mess on day one:

```python
# tests/tooling/check_test_count.py
"""Fail if the suite collects fewer tests than last recorded."""
import json, subprocess, sys
from pathlib import Path

BASELINE = Path(__file__).parent.parent / "outcomes" / "pytest" / "collected.json"

out = subprocess.run(
    [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
    capture_output=True, text=True,
)
now = out.stdout.count("::")
was = sum(len(v) for v in json.loads(BASELINE.read_text()).values())

print(f"collected={now} baseline={was}")
if now < was:
    sys.exit(f"FAIL: lost {was - now} tests")
```

Wire it into `stage_gates`.

**Done when:** `diff-cover` rejects an under-tested line in `whatsapp_adapter`.
Watch it fail once — a gate you have never seen fail is not known to work.

---

## Step 5 — Write the missing tests

Only now. Tests written before Step 4 rot exactly like the current ones did.

Two components hold **2,224 of the 3,090 untested statements — 72% of all dark
code**:

**`knowledge_store`** — 1105 statements, zero tests. It is a batch job, so test
its five `run.py` verbs: `ingest`, `remove`, `sessions`, `import-ncert`,
`import-educart`. Start with the pure functions that need nothing external:
`graph/ids.py`, `types/`, `extraction/units.py`, `progress.py`.

**`infra`** — 3556 statements, no suite aimed at it. Create `tests/infra/`.
Order by blast radius: `api/routes.py` (shared by all 5 services),
`firestore/repos/`, `clients/`.

Then the WhatsApp path itself: the turn ledger, inbound media, Flow
completions, the Conversions API reporter.

**Done when:** `knowledge_store` and `infra` are non-zero and gated.

---

## Open questions — answered from the code

### 1. `gifting.py` crash — the TEST is wrong. Fix in Step 2.

`redeem()` takes `profile: UserProfile` (`gifting.py:97`) and the route passes
one: `redeem(profile, points, body, ctx.gifting, ctx.hubble)`
(`api/routes/gifting.py:34`). The test passes a bare string `USER_ID`
(`test_gifting.py:663`). Product and caller agree; 5 tests are stale.

Fix: build a `UserProfile` in the test instead of passing a string. No product
change.

### 2. `_derive_user_id` — not a live bug. Tests follow the verbatim HMAC.

WhatsApp sends one canonical digit string and we HMAC that string verbatim.
The old Block button could never miss because of `+91` vs digits.

The loose API (blocklist accepted a phone) and the docs lie
("Indian-normalized") were the real problems. Product rekeyed
`PUT`/`DELETE /internal/blocklist/{userId}` and documented that access
resolution and user creation are the only doors where a phone becomes an
identity. Different spellings are different ids; that is the contract.

The 3 `test_user_id` cases now assert those spellings **differ**. Do not
add a normalizer.

### 3. `/health` and `/version` are the public surface.

README now: "Besides `/health` and `/version` there is no public surface."
`PUBLIC_EXEMPT` is those two routes. Public `POST /access/phone` is gone.

### 4. Remaining reds are not the four reported issues.

Phone HMAC, webhook envelopes, blocklist `userId`, and empty Hubble vouchers
are settled as in questions 2 and the owner's notes: envelopes 422/403/421,
blocklist by `userId`, loud 500 on SUCCESS with no voucher.

Four reds were the tests being wrong rather than the code, and have been
corrected: `gradedWith` (removed from the contract upstream), transcript
`sequence` origin (0-based by design), the unknown-user append (the API-layer
fake returns `200` because it models no users at all; real Firestore fails the
transaction, so this moved to integration), and the forwarded-contact greeting
(the intro is not repeated once the action is pending).

Every remaining red is in `HANDOVER.md`, split into defects, decisions, and
parked. That file is the live list; this one is the plan it came from.

---

## What ran, what did not, and why

The suite contains **472 tests**. **342 produced a result. 130 did not.**

### Ran — 342 of 472 (72%)

| Result | Count |
|---|---:|
| Passed | 306 |
| Failed | 34 |
| xfailed (expected fail) | 2 |

Of the 34 failures, 18 are deliberate known-reds recorded 2026-09-04 and 16 are
new regressions.

### Did not run — 130 of 472 (28%)

| Count | What | Why |
|---:|---|---|
| 30 | `tests/api/whatsapp_adapter` | `AppState(coordinator=…)` — field is now `turns`. Fixture crashes, so every test in the suite errors before reaching the product. |
| 13 | `tests/api/text_agent` | `RespondService(llm_client=…)` — param is now `runtime`. Same: fixture crashes, whole suite errors. |
| 19 | `tests/unit/user_service/test_attribution.py` | Imports `resolve_referrer`, which no longer exists. File fails to import, so its tests are never collected. |
| 8 | `tests/integration/test_cross_service_contract.py` | Imports `assistant_row`, now `assistant_rows`. File fails to import, never collected. |
| 39 | `tests/integration` (the rest) | Needs the Firestore emulator, which needs Java. `/usr/bin/java` is the macOS stub, not a JRE. |
| 21 | `tests/e2e` | Same missing JRE. |

Separately, all **3 files in `evals/tests`** collect 0 tests: `evals/checks.py`
imports `filename_from_url` from `infra.conversation_media.store`, which no
longer exists. This is a default CI stage.

### Why the totals look inconsistent elsewhere

`pytest` reports **445 collected** and **44 errors**. Both are accurate but
easy to misread:

- 445 = 472 minus the 27 tests in the two files that fail to import.
- 44 = 43 test-level fixture errors, plus 1 file-level import error
  (`test_attribution.py`) that is a file, not a test.
- So 385 collected tests in `tests/unit` + `tests/api`
  = 306 + 34 + 2 + 43 errors.

### Coverage measured from the 342 that ran

`user_service` 91.0%, `redirect_service` 88.4%, `document_worker` 85.9%,
`infra` 68.5%, `text_agent` 68.1%, `whatsapp_adapter` 46.9%,
`knowledge_store` 0.0%. Total 52.6%.

`text_agent` and `whatsapp_adapter` are floors, not real values — their suites
errored before reaching the code.

Reproduce:

```bash
pytest tests/unit tests/api --continue-on-collection-errors -q
```
