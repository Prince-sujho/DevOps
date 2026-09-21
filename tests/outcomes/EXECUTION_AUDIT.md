# EXECUTION AUDIT — Are the passing test results real?

Scope: `tests/unit/user_service`, `tests/api/*` (runnable in this sandbox); `tests/integration` and
`tests/e2e` are collected but cannot execute here (`gcloud emulators firestore start` fails:
"Unable to execute the java that was found on your PATH" — no JRE in this environment). This was
verified by actually attempting to run them (see Check 7 and the Check 5 sabotage section), not
assumed.

Environment: `.venv/bin/pytest` 9.1.1, Python 3.13.15, pytest-cov 7.1.0 / coverage 7.16.0,
pytest-asyncio 1.4.0, pytest-socket 0.8.1 (installed live, network was available).

---

## CHECK 1 — Async tests that never executed

Raw commands and output:

```
$ grep -rn "async def test_" tests/ | wc -l
     240

$ grep -rn "asyncio_mode\|pytest.mark.asyncio\|anyio_mode" pyproject.toml setup.cfg pytest.ini tests/ 2>/dev/null
tests/unit/pytest.ini:2:asyncio_mode = auto
tests/integration/pytest.ini:2:asyncio_mode = auto
[... 90+ lines of tests/**/test_*.py hits for @pytest.mark.asyncio / pytestmark = pytest.mark.asyncio, spanning
tests/unit/user_service, tests/api/*, tests/integration, tests/e2e — full raw list captured during the run]
```

Root `pyproject.toml`'s `[tool.pytest.ini_options]` is **empty**:
```toml
[tool.pytest.ini_options]
# Root-level pytest config only affects invocation from repo root; the
# authoritative unit-suite config remains tests/unit/pytest.ini.
```
`tests/api/*` has **no pytest.ini of its own** at all. Pytest's ini-file discovery uses the common
ancestor of the paths given on the command line and searches upward for the first ini file; when
invoking `pytest tests/unit tests/api` (as Checks 2/4/6 require) or `pytest tests/` (Checks 1/7),
the common ancestor is `tests/`, which has no ini file, so the search continues up to the repo
root and picks up `pyproject.toml`'s **empty** `[tool.pytest.ini_options]`. This means
`tests/unit/pytest.ini`'s `asyncio_mode = auto` is **not actually in effect** for any of the
invocations this audit runs, or for CI runs that invoke `pytest tests/unit tests/api` together.

This is a real config gap, but it turned out **not to produce any dead async test**, because every
single async test in the runnable suites already carries an *explicit* `@pytest.mark.asyncio`
decorator or a module-level `pytestmark = pytest.mark.asyncio` — which works identically under
pytest-asyncio's default "strict" mode, independent of `asyncio_mode`. Verified by a script that
parsed every `async def test_` in `tests/` and walked backward for a decorator or checked for a
module-level `pytestmark`/`anyio_mode`:

```
total async def test_ found (python-parsed): 236
missing explicit/module asyncio marking, count: 0
```

Confirmed empirically, not just by code inspection — full-suite run and grep for the
unawaited-coroutine / "was not run" / unknown-mark signatures:

```
$ .venv/bin/pytest tests/ -q -rw 2>&1 | grep -i "coroutine\|never awaited\|was not run\|unknown mark"
(0 lines)
```

And the stronger check, promoting `RuntimeWarning` to a hard error (which is what an unawaited
coroutine would raise if pytest silently dropped it):

```
$ .venv/bin/pytest tests/ -W error::RuntimeWarning -q 2>&1 | tail -30
...
16 failed, 218 passed, 6 warnings in 3.67s
! _pytest.outcomes.Exit: Firestore emulator exited early:
ERROR: (gcloud.emulators.firestore.start) Unable to execute the java that was found on your PATH...
```
Identical pass/fail counts to the unconstrained run — no `RuntimeWarning` was hiding anywhere.

**Finding: 0 dead async tests.** The 16 failures present are pre-existing behavioral bugs (real
assertion failures against 500s/404s/missing-fields — a different, already-documented class of
issue, not execution vacuity), not async-related. The `tests/api` ini gap is worth fixing for
hygiene/CI-robustness reasons, but it is not currently causing any test to silently not run.

One incidental, harmless warning found:
```
tests/api/user_service/test_auth_boundary.py::test_public_route_exemption_set_matches_readme
  tests/api/user_service/test_auth_boundary.py:89: PytestWarning: The test <Function
  test_public_route_exemption_set_matches_readme> is marked with '@pytest.mark.asyncio' but it is
  not an async function.
```
This is a synchronous test picking up the file's module-level `pytestmark = pytest.mark.asyncio`
by accident. It still runs synchronously and its assertion still executes — cosmetic only.

---

## CHECK 2 — Per-test coverage contexts

```
$ .venv/bin/pytest tests/unit tests/api -q --cov=user_service/app/src --cov-branch --cov-context=test --cov-report=json
...
Coverage JSON written to file coverage.json
Required test coverage of 90.0% reached. Total coverage: 90.04%
21 failed, 328 passed, 6 warnings in 5.14s

$ .venv/bin/coverage json -o coverage.json --show-contexts
Wrote JSON report to coverage.json
```
(`--cov-context=test` worked directly with pytest-cov 7.1.0; no troubleshooting needed.)

Line numbers were read directly from the source files (not guessed) before querying contexts:

| Function | Line(s) checked | Description matched |
|---|---|---|
| `gifting.earned_inr` | 17 | `sum(... if points >= tier.points)` |
| `gifting.spent_inr` | 22 | `sum(... if card.status != "failed")` |
| `gifting.balance_inr` | 27 | `earned_inr(...) - spent_inr(...)` |
| `gifting.offered_amounts` | 36 (ladder/denominations `or`), 37 (`ceiling = min(...)`), 38 (return/filter) | matches description |
| `gifting._apply_order` | 52 | `voucher = order.vouchers[0]` |
| `influencers._campaign_for` | 25 | `c.startMs <= at_ms <= c.endMs` (start+end comparison is one line) |
| `influencers._campaign_spend` | 31 (floor-div `onboards // payout.blockSize`), 32 (cap `min(blocks*perBlockInr, incentiveCapInr)`) | matches |
| `ambassadors._tier_reached` | 44 | `points >= tier.points` inside the list comprehension |
| `attribution.first_registered_mention` | 14 | `next(m for m in mentions(text) if m in handles)` — loop and registered-check are the same physical line (single-expression generator) |
| `directory._matches` | 64 | `all(token in haystack for token in needle.split())` |

Per-line coverage-context query (`python3 -c "import json; d=json.load(open('coverage.json')); ..."`),
every target line **had covering tests** — none came back empty. Representative excerpt (full test
lists captured during the run for every line):

- `gifting.py:52` (`vouchers[0]`) → **only one** covering test:
  `tests/api/user_service/test_gifting.py::test_redeem_gift_card_success_shape`. The line is
  covered (not a Check-2 "no test" finding), but only the success path is ever exercised — the
  known `IndexError` bug on an empty `vouchers` list (documented in `tests/outcomes/FINDINGS.md`) has no
  test forcing that branch. This belongs in Section 4 as an under-tested edge, not "no covering
  test."
- `gifting.py:36/37/38` (ladder/clamp/denominations): 16 covering tests including
  `test_flexible_amounts_are_the_ladder_plus_exact_balance_inside_bounds`,
  `test_fixed_amounts_stay_within_bounds_sorted_unique`, etc. — both branches of the `or` on line
  36 are exercised; confirmed via `coverage report -m` branch data (`gifting.py` missing_branches
  = `[[48,49],[50,51],[65,66],[65,67]]`, none touching line 36-38).
- `influencers.py:25,31,32`: fully covered, `coverage report -m` shows `influencers.py` at 100%
  statements and 100% branches (`Stmts 36 Miss 0 Branch 6 BrPart 0`).
- `ambassadors.py:44`: 13 covering tests, 100% branch coverage for the file.
- `attribution.py:14`: 13 covering tests (missing lines in that file are 35-39, inside
  `derive_starts`, unrelated to the target line).
- `directory.py:64`: 16 covering tests (missing lines in that file are 75/78-79, unrelated to
  `_matches`).

**Name-vs-coverage-context cross-check**: every test whose name plausibly claims to test one of
these ten functions (`test_earned_inr_*`, `test_spent_inr_*`, `test_balance_inr_*`,
`test_offered_amounts_*`, `test_campaign_for_*`, `test_campaign_spend_*`, `test_tier_reached_*`,
`test_*registered_mention*`, `test_matches_*`) **does appear** in the coverage context for the
line(s) it should cover. **No name/context mismatches were found** for these ten targets. (Tests
like `test_offered_amounts_inactive_product_is_empty` legitimately do not appear in the
line-36/37/38 context because they test the function's earlier guard clause at line 32-33, a
different line in the same function — that is not a mismatch.)

**Finding: all 10 target lines/branches are genuinely covered by tests whose names match their
purpose.** No untested-line findings from Check 2 itself; see Section 4 for the one
under-tested-edge-case observation (the `vouchers[0]` crash path).

---

## CHECK 3 — Inversion drill

Sed inversion (`sed -i '' 's/assert \(.*\) == \(.*\)/assert \1 != \2/'`) was run against **all 37**
`test_*.py` files under `tests/unit/user_service` and `tests/api/**` — every file was covered, one
at a time, backed up, inverted, run, restored, and verified clean via `git status --porcelain`.
Full per-file pass/fail summary (raw `pytest -q` tail from each of the 37 runs):

```
tests/api/document_worker/test_health_version.py        -> 2 failed, 5 warnings
tests/api/document_worker/test_render_auth.py            -> 3 failed, 5 warnings
tests/api/document_worker/test_render_failure.py         -> 2 failed, 5 warnings
tests/api/document_worker/test_render_success.py         -> 2 failed, 5 warnings
tests/api/document_worker/test_render_validation.py      -> 8 failed, 5 warnings
tests/api/redirect_service/test_click_best_effort.py     -> 2 failed, 1 passed
tests/api/redirect_service/test_health_version.py        -> 3 failed
tests/api/redirect_service/test_redirect.py               -> 5 failed
tests/api/text_agent/test_ops_routes.py                   -> 2 failed
tests/api/text_agent/test_respond_auth.py                 -> 2 failed
tests/api/text_agent/test_respond_failure.py               -> 2 failed
tests/api/text_agent/test_respond_success.py               -> 1 failed
tests/api/text_agent/test_respond_validation.py             -> 5 failed
tests/api/user_service/test_access.py                       -> 6 failed
tests/api/user_service/test_ambassadors.py                  -> 8 failed, 2 passed
tests/api/user_service/test_auth_boundary.py                -> 71 failed, 1 passed, 1 warning
tests/api/user_service/test_blocklist.py                     -> 4 failed
tests/api/user_service/test_directory.py                     -> 10 failed
tests/api/user_service/test_enrollments.py                   -> 5 failed
tests/api/user_service/test_gifting.py                        -> 7 failed
tests/api/user_service/test_health_version.py                 -> 2 failed
tests/api/user_service/test_influencers.py                     -> 12 failed, 6 passed
tests/api/user_service/test_referrers.py                       -> 4 failed
tests/api/user_service/test_threads.py                          -> 8 failed, 2 passed
tests/api/user_service/test_users.py                             -> 17 failed
tests/api/whatsapp_adapter/test_flows.py                          -> 14 failed
tests/api/whatsapp_adapter/test_ops_endpoints.py                   -> 2 failed
tests/api/whatsapp_adapter/test_webhook_signature.py                -> 4 failed
tests/api/whatsapp_adapter/test_webhook_success.py                   -> 3 failed
tests/api/whatsapp_adapter/test_webhook_validation.py                 -> 2 failed
tests/api/whatsapp_adapter/test_webhook_verification.py                -> 4 failed
tests/unit/user_service/test_ambassadors.py                             -> 11 failed, 4 passed
tests/unit/user_service/test_attribution.py                              -> 5 failed, 9 passed
tests/unit/user_service/test_directory.py                                 -> 11 failed, 11 passed
tests/unit/user_service/test_gifting.py                                    -> 34 failed
tests/unit/user_service/test_influencers.py                                 -> 14 failed, 8 passed
tests/unit/user_service/test_user_id.py                                      -> 2 failed, 6 passed
```

`git status --porcelain -- <file>` after every single revert showed only `?? <file>` (the expected
untracked state — `tests/` is entirely untracked in this repo to begin with; no leftover
modifications).

### Triage of every test that "still passed" after inversion

10 files had `passed > 0`. Each surviving test was individually re-run with `-v` and its source
inspected. Every survivor falls into one of three buckets — **none is a genuine vacuity finding**:

**(a) Already a pre-existing failure before inversion** (from Check 2's 21-item FAILED list — a
test that was red to begin with tells us nothing about inversion):
`test_enroll_ambassador_refuses_when_institution_id_is_null`,
`test_create_influencer_409_on_collision_with_existing_influencer_handle`,
`test_create_influencer_409_on_collision_with_existing_ambassador_handle`,
`test_campaign_overlap_identical_window_is_409`, `test_campaign_overlap_partial_at_start_is_409`,
`test_campaign_overlap_partial_at_end_is_409`, `test_campaign_overlap_fully_containing_is_409`,
`test_append_transcript_404_for_unknown_user`, `test_set_session_extraction_404_for_unknown_session`,
`test_campaign_spend_negative_onboards_does_not_pay_below_base`,
`test_plus_91_is_the_same_identity_as_digits`, `test_spaces_in_the_phone_are_the_same_identity`,
`test_leading_zero_is_the_same_identity`.

**(b) No `==` assertion at all** (sed correctly never touched them — confirmed by reading each
test): `test_click_logging_failure_does_not_break_redirect` (`pytest.raises`),
`test_enroll_ambassador_refusal_does_not_create_a_registry_row` (`is None`),
`test_route_enumeration_is_nonempty` (`len(...) > 10`),
`test_tier_reached_below_first_rung_is_none`, `test_next_tier_at_top_rung_is_none`,
`test_mint_handle_name_with_no_latin_letters_raises`, `test_mint_handle_punctuation_only_name_raises`
(`is None` / `pytest.raises`), all 11 `test_matches_*`/`test_blank_queries_match_any_name` in
`test_directory.py` (unit) (`is True`/`is False`), all 7 `test_campaign_for_*` /
`test_campaign_window_contains_exactly_its_closed_interval` (`is`/`is None`), and
`test_two_different_phones_never_share_an_id`, `test_different_hmac_secrets_do_not_alias_the_same_phone`,
`test_distinct_canonical_phones_do_not_collide` (all use `!=`, the opposite of what the drill
inverts).

**(c) A genuine `==` comparison the sed regex missed due to multi-line formatting** (the
`assert (` and `== value` are on different source lines, so the single-line sed pattern never
matched): 3 tests in `tests/unit/user_service/test_attribution.py` —
`test_first_registered_mention_wins_even_when_an_unregistered_mention_appears_earlier`,
`test_first_of_two_registered_mentions_wins`,
`test_resolve_referrer_first_text_with_a_registered_mention_wins`. These were manually inverted
(`== "alice"` → `!= "alice"`) and **all three failed correctly**:
```
FAILED tests/unit/user_service/test_attribution.py::test_first_registered_mention_wins_even_when_an_unregistered_mention_appears_earlier
FAILED tests/unit/user_service/test_attribution.py::test_first_of_two_registered_mentions_wins
FAILED tests/unit/user_service/test_attribution.py::test_resolve_referrer_first_text_with_a_registered_mention_wins
3 failed, 11 deselected in 0.88s
```
This is a **methodology gap in the sed-based drill, not a defect in the test suite** — worth
noting since a purely mechanical CI check based on this exact sed pattern would blind-spot
multi-line asserts.

**Result: zero tests in the entire sed-inverted `==` pass are vacuous.** Every survivor is either
pre-existing-broken, uses a non-`==` assertion, or was a sed-methodology miss that failed once
manually corrected.

### Manual inversion of `in` / `is None` / `pytest.raises` (no `assert_called_with` exists in the
runnable suites — see Check 4)

Representative sampling, not exhaustive (33 `is None`, 5 `pytest.raises`, 20 raw `in`-pattern
grep hits — most of the `in` hits are false positives from list-comprehension `for x in y`
syntax, not membership assertions; the true membership assertions are far fewer):

- **`pytest.raises` — all 5 occurrences done exhaustively** (small population): inverted the
  expected exception class to a wrong type (`ValueError`→`TypeError`, `RuntimeError`→`TypeError`)
  in `test_mint_handle_name_with_no_latin_letters_raises`, `test_mint_handle_punctuation_only_name_raises`,
  `test_mint_handle_empty_name_raises` (unit/test_ambassadors.py), and
  `test_click_logging_failure_does_not_break_redirect`,
  `test_click_logging_failure_302_already_sent_at_asgi_level` (api/test_click_best_effort.py). **All
  5 failed correctly** (the real exception, propagating unmatched, produced a test failure — e.g.
  `ValueError: ambassador name yields no referral stem: '张伟'` propagating out because
  `pytest.raises(TypeError)` didn't match).

- **`is None` — sampled 8 of 33**, spanning both unit and api: `influencers.py:66`
  (`test_campaign_for_one_ms_before_start_is_none`), `ambassadors.py:46` (unit,
  `test_tier_reached_below_first_rung_is_none`), `attribution.py:47`
  (`test_no_mentions_returns_none`), `test_users.py:21`
  (`test_create_user_returns_201_or_200_with_profile_shape`), `test_ambassadors.py:26` (api,
  `test_enroll_ambassador_first_call_mints_handle_and_returns_status`), `test_ambassadors.py:97`
  (`test_get_ambassador_status_null_when_not_enrolled`), `test_access.py:17`
  (`test_public_access_phone_needs_onboarding_for_unknown_phone`), `test_ambassadors.py:131`
  (`test_list_ambassadors_row_shape`). Inverted each `is None` → `is not None` (and the compound
  `"user" not in body or body["user"] is None` → `"user" in body and body["user"] is not None`).
  **All 8 failed correctly**, e.g. `AssertionError: assert None is not None`.

- **`in` / `not in` membership — sampled 4** of the small number of genuine (non-false-positive)
  membership assertions: `gifting.py:88` (`test_earned_inr_equals_sum_of_every_crossed_rung`, a
  Hypothesis property test), `ambassadors.py:104`
  (`test_tier_reached_and_next_tier_are_always_consistent`, also property-based),
  `test_respond_validation.py:23` (`test_missing_user_field_is_422`), `test_render_failure.py:74`
  (`test_render_nonsensical_but_schema_valid_format_still_reaches_storage_prefix`). **All 4 failed
  correctly** after inverting `in`↔`not in` (Hypothesis even printed the exact minimal failing
  case for the property tests, e.g. `points=0` and `points=5`).

**Conclusion for Check 3: zero surviving vacuous tests found across every category attempted** —
`==`, `is None`, `in`/`not in`, and `pytest.raises` assertions in the runnable suites all
genuinely execute and can fail. `git status --porcelain` after every single one of these drills
(sed-based and manual) showed only the expected `??` untracked markers, never a leftover
modification.

---

## CHECK 4 — Mocks that are not load-bearing

```
$ grep -rno "patch([\"'][^\"']*[\"']" tests/ | sort -u
(0 lines — no output)
```

Broader search for any mocking usage at all:
```
$ grep -rln "unittest.mock\|from unittest import mock\|mock.patch\|monkeypatch\|MagicMock\|AsyncMock\|import mock" tests/
tests/outcomes/FINDINGS.md
tests/outcomes/UNCERTAINTY.md
tests/api/document_worker/test_render_failure.py
tests/api/redirect_service/test_health_version.py
tests/integration/test_transactions.py
```

**`unittest.mock.patch(...)` is used exactly zero times anywhere in the entire test tree.** The
suite is built around hand-written fake/stub objects (`FakeUsersClient`, `FakeReferrers`,
`ScriptedHandleRegistry`, etc. injected via FastAPI dependency overrides / constructor args), not
`mock.patch`. The only real patching mechanism found is `pytest`'s built-in `monkeypatch` fixture,
used in exactly 3 places:
- `tests/api/document_worker/test_render_failure.py:44,64` —
  `monkeypatch.setattr(service_module, "render_previews", _fake_previews_ok)`, where
  `service_module = document_worker.src.service`. `document_worker/src/service.py` does
  `from infra.documents.previews import render_previews` and calls it as a bare name. Since
  Python resolves a bareword function call against the *calling* module's own `__globals__` dict
  (which is exactly what `service_module` refers to), `monkeypatch.setattr(service_module, ...)`
  **is** patching the exact namespace the call resolves through — this is the correct
  "patch-where-used" pattern, not a mismatch, despite `service.py` using a direct-import binding.
  Not a Check-4 finding.
- `tests/api/redirect_service/test_health_version.py:38-39,54-55` — `monkeypatch.setenv`/`delenv`
  for environment variables, unrelated to symbol patching.
- `tests/integration/test_transactions.py:90` — `monkeypatch.setattr(ThreadsRepository, ...)`,
  inside `tests/integration`, which cannot run in this sandbox (JRE-dependent).

**Finding: the "patched at definition site while consumer does a direct import" failure mode does
not exist in this codebase** — there is no `mock.patch(...)` call to have gotten wrong in the
first place.

### Socket-disabled run

```
$ .venv/bin/pip install pytest-socket
Successfully installed pytest-socket-0.8.1

$ .venv/bin/pytest tests/unit tests/api --disable-socket -q
...
4 failed, 99 passed, 36 warnings, 246 errors in 4.61s
```
Every one of the 246 errors was `pytest_socket.SocketBlockedError: A test tried to use
socket.socket` raised from `socket.socketpair()` at fixture/event-loop setup, e.g.:
```
_____ ERROR at setup of test_mint_handle_name_with_no_latin_letters_raises _____
    self._ssock, self._csock = socket.socketpair()
>       raise SocketBlockedError()
```
This is asyncio/anyio's internal self-pipe `socketpair()` for the event loop, unrelated to any
outbound network call — `pytest-socket --disable-socket` blocks all socket creation, including
local `AF_UNIX` socketpairs, by default. Re-ran with `--allow-unix-socket` (pytest-socket's
documented flag for exactly this class of false positive) to isolate genuine outbound-network
dependence:
```
$ .venv/bin/pytest tests/unit tests/api --disable-socket --allow-unix-socket -q
...
21 failed, 328 passed, 6 warnings in 3.21s
```
This is **byte-for-byte the same pass/fail count as the unconstrained baseline run** (Check 2's
`21 failed, 328 passed`). **Finding: zero tests depend on real network reachability.** The raw
`--disable-socket` run without `--allow-unix-socket` is not usable evidence on its own in this
codebase (it produces 246 false-positive errors from the event loop, not from application code
making real connections) — reporting those 246 as "network calls" would have been a fabricated
finding; the controlled re-run confirms none of them were.

---

## CHECK 5 — Vacuous negative assertions

```
$ grep -rn "== 0\|== \[\]\|assert_not_called\|not .*\.called\|len(.*) == 0" tests/
(106 lines total; see raw list captured during the run — spans tests/unit, tests/api,
tests/integration, tests/e2e)
```

Every hit in the **runnable** suites (`tests/unit`, `tests/api`) was opened and checked for a
positive control immediately preceding the negative assertion. All of them have one:
- `test_ambassadors.py` (api) `points==0`/`studentsReferred==0`/etc. are part of a full
  profile-shape assertion block that also asserts `body["handle"].startswith("arjun-")` and
  `response.status_code == 200` — proving the enroll actually happened.
- `test_directory.py` (api) `entries == []` / `totalCount == 0` cases: every one is preceded by
  `await _seed_students(...)` and paired with either a nonzero `totalCount` (e.g. `== 4`, proving
  the seed worked and only the specific query zeroed out) or a `status_code == 200` check.
- `test_gifting.py:145` (`len(place_order_calls) == 0`) is preceded by
  `assert response.status_code == 422`, a positive control on the rejection path.
- `test_referrers.py:33` (`clicks.rows_for(...) == []`) is preceded by
  `assert response.status_code == 204`.
- `tests/api/whatsapp_adapter/test_webhook_signature.py` /`test_webhook_validation.py`
  /`test_webhook_success.py` — every `claim_calls == []` / `coordinator.calls == []` assertion is
  preceded by a `status_code` check (500/403/200) that pins down which code path actually ran, and
  `test_sent_status_confirms_delivery` additionally has `confirmations.confirmed == [wamid]` as a
  positive control.

**No vacuous negative assertion (missing positive control) was found in the runnable suites.**

### Sabotage drill on the named e2e-style tests

The task named `blocked-phone-writes-no-transcript`, `duplicate-webhook-makes-no-second-agent-call`,
`un-onboarded-user-writes-no-transcript`-shaped tests, expected in `tests/e2e/`. These files exist
(`tests/e2e/test_blocking_and_failures.py`, `tests/e2e/test_idempotency.py`,
`tests/e2e/test_onboarding.py`) and do contain exactly this shape of negative assertion (e.g.
`tests/e2e/test_blocking_and_failures.py:54` `assert await all_transcript_row_count(db) == 0`).
Attempted to run them directly rather than assuming:
```
$ .venv/bin/pytest tests/e2e/test_blocking_and_failures.py -q
no tests ran in 0.94s
! _pytest.outcomes.Exit: Firestore emulator exited early:
ERROR: (gcloud.emulators.firestore.start) Unable to execute the java that was found on your PATH...

$ .venv/bin/pytest tests/integration/test_cascade.py -q
no tests ran in 0.64s
! _pytest.outcomes.Exit: Firestore emulator exited early: ... (same JRE error)
```
**Confirmed NOT POSSIBLE IN THIS ENVIRONMENT** — both `tests/integration` and `tests/e2e` abort at
the emulator-startup fixture before a single test body runs; this is not something that can be
routed around here.

As required, ran the equivalent drill on runnable stand-ins from `tests/api` instead:

1. **`test_sent_status_confirms_delivery`** (`tests/api/whatsapp_adapter/test_webhook_success.py`)
   — sabotaged by replacing the status-only trigger payload with a real inbound-message payload
   (`sent_status_webhook(...)` → `text_message_webhook()`):
   ```
   assert harness.confirmations.confirmed == [wamid]
   E       AssertionError: assert [] == ['wamid.STATUS1']
   1 failed, 2 deselected in 0.09s
   ```
   Reverted; `git status --porcelain -- tests/api/whatsapp_adapter/test_webhook_success.py` → `??` only.

2. **`test_malformed_supported_payload_fails_loudly`** (`tests/api/whatsapp_adapter/test_webhook_validation.py`)
   — sabotaged by replacing the malformed-trigger payload with a well-formed one
   (`text_message_missing_text_object()` → `reaction_message_webhook()`):
   ```
   assert response.status_code == 500
   E       assert 200 == 500
   1 failed, 1 deselected in 0.09s
   ```
   Reverted; git status clean after.

3. **`test_click_on_unknown_handle_is_a_no_op_but_still_succeeds`** (`tests/api/user_service/test_referrers.py`)
   — sabotaged by seeding the "never-registered" handle as a real ambassador before the click,
   directly attacking the negative assertion itself (not just an earlier positive control):
   ```
   assert fakes.clicks.rows_for("never-registered") == [], (
       "an unknown handle must not create a click document"
   )
   E       AssertionError: an unknown handle must not create a click document
   E       assert [1788538035952] == []
   1 failed, 3 deselected in 0.13s
   ```
   This is the strongest of the three: the positive control (`status_code == 204`) still passed,
   but the negative assertion itself correctly detected the sabotage. Reverted; git status clean.

**Finding: all three sabotage drills correctly turned a passing test red.** No vacuous
negative-assertion test found among the ones actually exercisable in this sandbox.

---

## CHECK 6 — Import sabotage

For each of the five critical modules, appended `raise RuntimeError('sabotage')` at module end,
ran `tests/unit`, then reverted.

**Important correction made mid-run**: `user_service` is a **git submodule**, not a plain tracked
directory of the outer repo. The first attempt used `git checkout -- user_service/app/src/<file>.py`
from the outer repo, which failed silently with `error: pathspec ... did not match any file(s)
known to git` (because the outer repo has no such path — it's inside the submodule). This left
all 5 files sabotaged simultaneously for one iteration, compounding the observed failures. This
was caught by checking `git status --porcelain` after every step (as required), diagnosed via
`git -C user_service status --porcelain` showing `M app/src/*.py` for all five files, and fixed
immediately with `git -C user_service checkout -- app/src/<file>.py`. Final state was verified
clean (`git -C user_service status --porcelain` → empty) before re-running the drill correctly,
and again before moving on to Check 7. `.venv/bin/pytest tests/unit -q` was re-run afterward and
reproduced the exact known baseline (5 pre-existing failures, 110 passed), confirming full
recovery.

Corrected per-module runs (revert via `git -C user_service checkout -- app/src/<mod>.py` each
time, `git status --porcelain` / `git -C user_service status --porcelain` both empty after every
one):

```
=== gifting.py sabotaged ===
ERROR tests/unit/user_service/test_ambassadors.py - RuntimeError: sabotage   (ambassadors.py does `from .gifting import ...`)
ERROR tests/unit/user_service/test_gifting.py - RuntimeError: sabotage
Interrupted: 2 errors during collection (0 tests ran at all — default pytest aborts the whole session on any collection error)

=== influencers.py sabotaged ===
ERROR tests/unit/user_service/test_influencers.py - RuntimeError: sabotage
Interrupted: 1 error during collection (0 tests ran)

=== ambassadors.py sabotaged ===
ERROR tests/unit/user_service/test_ambassadors.py - RuntimeError: sabotage
Interrupted: 1 error during collection (0 tests ran)

=== attribution.py sabotaged ===
ERROR tests/unit/user_service/test_attribution.py - RuntimeError: sabotage
Interrupted: 1 error during collection (0 tests ran)

=== directory.py sabotaged ===
ERROR tests/unit/user_service/test_directory.py - RuntimeError: sabotage
Interrupted: 1 error during collection (0 tests ran)
```

By default, pytest aborts the **entire** `tests/unit` session on any collection error, so the
observed blast radius per run is "the whole suite reports 0 executed" — a stronger, not weaker,
signal (nothing anywhere silently reports green while a target module is broken). To see the
precise per-file blast radius, re-ran the `gifting.py` sabotage with
`--continue-on-collection-errors`:
```
$ .venv/bin/pytest tests/unit --continue-on-collection-errors -q
...
FAILED tests/unit/user_service/test_influencers.py::test_campaign_spend_negative_onboards_does_not_pay_below_base
FAILED tests/unit/user_service/test_user_id.py::test_plus_91_is_the_same_identity_as_digits
FAILED tests/unit/user_service/test_user_id.py::test_spaces_in_the_phone_are_the_same_identity
FAILED tests/unit/user_service/test_user_id.py::test_leading_zero_is_the_same_identity
ERROR tests/unit/user_service/test_ambassadors.py - RuntimeError: sabotage
ERROR tests/unit/user_service/test_gifting.py - RuntimeError: sabotage
4 failed, 62 passed, 2 errors in 0.93s
```
This confirms the blast radius is exactly the expected transitive-import set (`test_gifting.py`
directly, `test_ambassadors.py` because `ambassadors.py` imports from `.gifting`) — `test_influencers.py`,
`test_directory.py`, `test_attribution.py`, `test_user_id.py` ran normally and unaffected (the 4
failures shown are the same pre-existing baseline failures, unrelated to the sabotage).

**Finding: no test claiming to cover a sabotaged module still passed.** No unrelated test files
were affected beyond the expected import chain.

---

## CHECK 7 — Collection sanity

```
$ .venv/bin/pytest tests/ --collect-only -q | tail -5
...
416 tests collected in 1.73s

$ find tests -name "*.py" | xargs grep -l "def test_" | wc -l
      58

$ .venv/bin/pytest tests/ -q -rA 2>&1 | tail -60
...
16 failed, 218 passed, 6 warnings in 3.18s
! _pytest.outcomes.Exit: Firestore emulator exited early:
ERROR: (gcloud.emulators.firestore.start) Unable to execute the java that was found on your PATH...
```

Collected-test breakdown by directory (from `--collect-only`):
```
234 tests/api
115 tests/unit
 47 tests/integration
 20 tests/e2e   (approx.; individual e2e node ids listed in the raw run)
```
234+115+47+20 ≈ 416, matching the reported total (collection fully parses every file, including
`integration`/`e2e`, with zero collection errors — the JRE/emulator failure happens later, at
fixture *setup*, not at collection).

**58 files contain `def test_`** by the raw grep, but one is a false positive:
`tests/e2e/servers.py:63: def test_gcp_identity() -> GcpIdentity:` is a helper/factory function
whose name happens to start with `test_`; it is not a pytest test (no assertions, returns a
value, not collected as a test — confirmed 0 pytest node ids reference it). The remaining 57 files
are all accounted for in the 416 collected node ids: 35 in `tests/api`, 6 in `tests/unit`, 9 in
`tests/integration`, 7 in `tests/e2e` (`test_ambassador_and_gifting.py`,
`test_blocking_and_failures.py`, `test_conversation.py`, `test_idempotency.py`,
`test_onboarding.py`, `test_session_gap.py`, `test_webhook_signature.py`).

`0 skipped` — confirmed by `grep -i "skip" /tmp/check7_full.txt` returning nothing.

Only warning in the full-suite summary (besides the harmless C-extension `SwigPy*`
`DeprecationWarning`s, unrelated to this codebase):
```
tests/api/user_service/test_auth_boundary.py::test_public_route_exemption_set_matches_readme
  tests/api/user_service/test_auth_boundary.py:89: PytestWarning: The test <Function
  test_public_route_exemption_set_matches_readme> is marked with '@pytest.mark.asyncio' but it is
  not an async function.
```

**Finding: no test file on disk with real test functions is missing from collection.**
`tests/integration` (47 collected) and `tests/e2e` (~20 collected) are fully parsed but 0 of them
execute a single test body in this sandbox — the run aborts via `_pytest.outcomes.Exit` the moment
the session-scoped Firestore-emulator fixture tries to start, before the first `integration`/`e2e`
test function runs. That is why `tests/unit`+`tests/api` (349 tests) show real pass/fail results
(218 passed / 16 failed / 115 more in tests/unit not shown in this particular tail) while
`tests/integration`+`tests/e2e` show none — a documented environment limitation, not a suite defect.

---

## SECTION 1: DEAD TESTS

**None found.** Every check designed to surface a test that reports green without its assertion
ever executing (Check 1's async-marking audit, Check 3's inversion drill across `==`, `is None`,
`in`/`not in`, and `pytest.raises`) came back empty in the runnable suites (`tests/unit`,
`tests/api`). The one near-miss — 3 tests in `test_attribution.py` that the sed-based drill's
single-line regex failed to touch because their `==` spans two source lines — were manually
inverted and confirmed to fail correctly (Check 3, bucket (c)); they are not dead, the drill's
first pass was just blind to their formatting.

`tests/integration` and `tests/e2e` cannot be evaluated for this at all in this environment (Check
5, Check 7) — their assertions may or may not execute for real; that is unverified here, not
verified-clean.

## SECTION 2: VACUOUS TESTS

**None found among the negative-assertion population that is actually runnable here.** Every
`== 0` / `== []` / membership-style negative assertion in `tests/unit` and `tests/api` was checked
for a positive control and had one (Check 5). The 3 hand-sabotage drills on runnable stand-ins for
the task's named "writes-no-X" test shapes all correctly turned red when their triggering
condition was removed or subverted (Check 5).

The genuinely equivalent named tests (`tests/e2e/test_blocking_and_failures.py`,
`tests/e2e/test_idempotency.py`, `tests/e2e/test_onboarding.py`) could not be sabotage-tested —
confirmed NOT POSSIBLE IN THIS ENVIRONMENT (no JRE for the Firestore emulator; verified by
attempting to run them directly, not assumed).

## SECTION 3: MISLEADING MOCKS

**No `unittest.mock.patch(...)` calls exist anywhere in the test tree** (Check 4) — the entire
"patched at definition site vs. consuming module's direct-import binding" failure class simply
does not apply to this codebase. The only patching mechanism in use, `monkeypatch.setattr`, is
used correctly (patches the consuming module's own namespace, which is where the bareword call
resolves) in the one place it targets application-level behavior
(`tests/api/document_worker/test_render_failure.py`).

**No test makes a real network call.** The naive `--disable-socket` run produced 246 errors, but
all 246 are `pytest_socket.SocketBlockedError` from `socket.socketpair()` — asyncio/anyio's
internal event-loop self-pipe, not application network I/O. Re-running with
`--allow-unix-socket` reproduced the exact unconstrained-baseline pass/fail counts
(`21 failed, 328 passed`), proving zero tests depend on real network reachability.

## SECTION 4: UNTESTED LINES

All 10 specifically-targeted critical lines/branches (Check 2) have covering tests. The one
concrete under-tested-edge-case finding:

- **`gifting._apply_order` line 52 (`voucher = order.vouchers[0]`)** is covered by exactly one
  test — `tests/api/user_service/test_gifting.py::test_redeem_gift_card_success_shape` — which
  only exercises the success path (a non-empty `vouchers` list). The known bug documented in
  `tests/outcomes/FINDINGS.md` (an `IndexError` when Hubble returns `SUCCESS` with an empty `vouchers`
  list) has **no test forcing that specific crash branch**, even though the line itself is
  "covered" in the statement-coverage sense.

No other target line came back with an empty coverage context.

## SECTION 5: COUNTS

- Total tests collected (`pytest tests/ --collect-only -q`): **416** (234 `tests/api`, 115
  `tests/unit`, 47 `tests/integration`, ~20 `tests/e2e`).
- Total tests that survived the sed-based `==` inversion drill as genuine vacuity findings: **0**
  (37/37 files drilled; every apparent survivor was triaged as pre-existing-failure, non-`==`
  assertion, or a sed-methodology miss that failed correctly once manually corrected).
- Total async tests found: **240** (raw grep) / **236** (AST-adjacent parse); async tests proven
  never to run: **0**.
- Total vacuous negative assertions found (missing positive control) in the runnable suites: **0**
  (out of 106 raw `== 0`/`== []`/`.called`-pattern grep hits, all checked in `tests/unit`+`tests/api`).
- Suite-wide result for the runnable portion (`tests/unit`+`tests/api`, 349 tests): **16 failed,
  218 passed** in the plain `tests/` run reported by Check 1/7 (21 failed, 328 passed when the
  full 349-test set including all of `tests/unit` is targeted directly, per Check 2/4) — these are
  pre-existing behavioral bugs, unrelated to execution-reality; not fixed as part of this audit
  per the no-fix instruction.
- `tests/integration` (47 collected) and `tests/e2e` (~20 collected): **0 executed** in this
  sandbox — blocked by missing JRE for the Firestore emulator, confirmed by direct attempt, not
  assumed.

## SECTION 6: REPO STATE

Final `git status --porcelain` (outer repo):
```
?? .coverage
?? .github/
?? .pre-commit-config.yaml
?? .secrets.baseline
?? Data/
?? coverage.json
?? pyproject.toml
?? scripts/
?? tests/
```

Final `git -C user_service status --porcelain` (submodule — all Check 6 import-sabotage edits
happened here):
```
(empty)
```

`.coverage` and `coverage.json` are new untracked artifacts produced by this audit's own coverage
runs (Check 2); `.github/`, `.pre-commit-config.yaml`, `.secrets.baseline`, `Data/`, `pyproject.toml`,
`scripts/`, `tests/` were already untracked at the start of this session (see the initial
`gitStatus` in the task header) and are unchanged by this audit. No tracked file was left modified
anywhere, in the outer repo or the `user_service` submodule. This file, `EXECUTION_AUDIT.md`, is
intentionally left as an additional untracked file and was not committed.
