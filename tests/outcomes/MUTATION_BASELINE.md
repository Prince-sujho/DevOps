# Mutation baseline (honest starting point)

Recorded **before** any test was added or tuned to kill survivors.
Tool: mutmut 3.7.0. Runner: `tests/unit` + `tests/api/user_service`, with the
18 already-red spec-mismatch tests deselected (they cannot be an oracle;
see `tests/outcomes/FINDINGS.md`). Integration and e2e excluded.

Command: `mutmut run` (2026-09-06), working tree at this file's first commit.

## Totals

| | count |
|---|---|
| mutants generated | 565 |
| killed | 448 |
| survived | 103 |
| no tests | 13 (`_settle` entirely untested at baseline) |
| timeout | 1 (`mint_handle` `if not exists` inverted — infinite retry) |
| skipped / suspicious / type-check | 0 |

**Score (killed / (killed + survived)) = 448 / 551 = 81.3%**

Score including untested and timeout as not-killed: 448 / 565 = 79.3%.

The CI ratchet in `.github/workflows/mutation.yml` uses **81.3%**. Untested
and timeout are listed in the triage table; they are gaps, not a reason to
inflate the percentage.

## Per module (baseline)

| file | total | killed | survived | no tests | timeout | score killed/(killed+survived) |
|---|---|---|---|---|---|---|
| `user_service/app/src/gifting.py` | 162 | 117 | 32 | 13 | 0 | 78.5% |
| `user_service/app/src/ambassadors.py` | 157 | 129 | 27 | 0 | 1 | 82.7% |
| `user_service/app/src/influencers.py` | 103 | 86 | 17 | 0 | 0 | 83.5% |
| `user_service/app/src/directory.py` | 113 | 98 | 15 | 0 | 0 | 86.7% |
| `user_service/app/src/attribution.py` | 30 | 18 | 12 | 0 | 0 | 60.0% |

## What this number means

Pure arithmetic (`earned_inr`, `spent_inr`, `_campaign_spend`, `_campaign_for`
inclusivity, `_tier_reached`) was already well pinned and mostly killed.
Survivors clustered in **I/O wrappers never called from unit tests**
(`_settle`, `derive_starts`, `derive_influencer_report`, `derive_status`)
and in **`+=` vs `=` / two-event counts** that a single-item fixture cannot see.

---

# Survivor triage

Verdict is exactly one of KILLABLE / EQUIVALENT / DEAD CODE.
Unsure → KILLABLE. Gifting survivors are KILLABLE unless the equivalence
proof is airtight. Mutant ids are mutmut 3 keys (`function__mutmut_N`).

## gifting.py — 32 survived + 13 no-tests

| mutant | original → mutated | why it survived | verdict |
|---|---|---|---|
| `_apply_order` 1 | `None or status in (...)` → `and` | No unit test called `_apply_order` with a 404/`None` order | KILLABLE |
| `_apply_order` 4–9 | `"FAILED"` / `"CANCELLED"` / `"REVERSED"` string mutated | Terminal Hubble statuses never asserted at unit layer | KILLABLE |
| `_apply_order` 10–13 | `gifting.fail(user_id, gift_card)` args → None / dropped | Fail identity not pinned | KILLABLE |
| `_apply_order` 22–23 | `cardPin` / `validTill` → None on succeed | SUCCESS voucher fields not pinned | KILLABLE |
| `_settle` 1–13 | entire function | **no tests** — `settled_gift_cards` never called from unit tests, so the trampoline never fired | KILLABLE |
| `settled_gift_cards` 2–10 | `gifting.list(None)` / `_settle` args dropped | Never called; list identity not pinned | KILLABLE |
| `derive_rewards` 11, 14, 15 | `zip(..., strict=True)` → None / omitted / False | `products` is `gather` of one `get_product` per `REWARD_PRODUCTS` key — lengths match by construction | EQUIVALENT — mismatch cannot occur without a broken `gather` |
| `redeem` 3, 5 | `settled_gift_cards` args → None | Redeem unit path missing | KILLABLE |
| `redeem` 20 | `ValueError(f"...")` → `ValueError(None)` | Spec names `ValueError`, not the message text | EQUIVALENT / spec gap (message unspecified) |
| `redeem` 23 | `"\\n".join` → `"XX\\nXX".join` | Instruction snapshot string never asserted | KILLABLE |
| `redeem` 37–39 | `place_order` product / reference / amount → None | Hubble mint args never asserted | KILLABLE |

No DEAD CODE in gifting. Empty-voucher SUCCESS (`vouchers[0]`) is a known FINDINGS crash, not a surviving mutant of a tested line.

## ambassadors.py — 27 survived + 1 timeout

| mutant | original → mutated | why it survived | verdict |
|---|---|---|---|
| `mint_handle` 3 | `"-".join` → `"XX-XX".join` | Stem is `split()[0]` then normalize; join of a one-token list ignores the separator. Spec example is first-name `arjun-x4k9` | EQUIVALENT / spec gap (multi-token stem undefined) |
| `mint_handle` 7 | `ValueError(f"...")` → `ValueError(None)` | Tests only `pytest.raises(ValueError)` | EQUIVALENT / spec gap (message unspecified) |
| `mint_handle` 17 timeout | `if not await exists` → `if await exists` | Empty-registry tests infinite-loop (SIGXCPU) before the retry test can kill it | TIMEOUT (would be KILLABLE: retry test asserts the returned handle is not a taken one) |
| `_enrolled` 7, 10, 11 | `zip(..., strict=True)` → None / omitted / False | Docstring: missing profile is a bug; no mismatch test | KILLABLE |
| `_row` 9 | `tier=_tier_reached(points)` → None | Roster/status never unit-tested | KILLABLE |
| `derive_roster` 16 | `count + len(starts)` → `-` | started formula never asserted with both onboards and abandoned starts | KILLABLE |
| `derive_roster` 19, 22, 23 | `zip(members, counts, strict=True)` | `counts` is gather of one call per member; same length by construction | EQUIVALENT |
| `derive_status` 4, 18–20, 7, 9, 34 | next_tier / tier / pointsToNext / settled_gift_cards / referral_link args → None | Status I/O wrapper untested | KILLABLE |
| `derive_status` 38–41, 43–46 | student/teacher count `1`→`2`, `==`→`!=`, string case | Single-persona or zero-referral fixtures | KILLABLE |
| `derive_status` 48 | `next_tier.points - points` → `+` | pointsToNextTier never asserted as 15 at 5 points | KILLABLE |
| `derive_detail` 19 | `len(referred)+len(pending_starts)` → `-` | started formula never asserted | KILLABLE |

## influencers.py — 17 survived

| mutant | original → mutated | why it survived | verdict |
|---|---|---|---|
| `derive_influencer_report` 1, 3, 5, 7–12 | handle / list / count_all / count_between args dropped or None | I/O wrapper never called from unit tests | KILLABLE |
| `_assemble_report` 11 | `_campaign_for(...)` → None on pending starts | Existing tests only put pending starts in a gap | KILLABLE |
| `_assemble_report` 17, 37, 40 | `stats.started/onboards/retained += 1` → `= 1` | Single-event fixtures | KILLABLE |
| `_assemble_report` 28–31 | `model_copy(update={"campaignId": ...})` mutated | `referral.campaignId` never asserted | KILLABLE |

## attribution.py — 12 survived (all in `derive_starts`)

| mutant | original → mutated | why it survived | verdict |
|---|---|---|---|
| 7–11 | `first_registered_mention(...)` → None / dropped args | `derive_starts` never called | KILLABLE |
| 12 | `if handle is not None` → `is None` | same | KILLABLE |
| 13–17 | `starts.setdefault(handle, []).append(...)` mutated | same | KILLABLE |
| 18 | `break` → `return` | would drop later buffered users; no two-in-flight fixture | KILLABLE |

## directory.py — 15 survived

| mutant | original → mutated | why it survived | verdict |
|---|---|---|---|
| `directory_entry` 2, 12 | `for_channel(None)`, `_activity_state(..., None)` | Production `directory_entry` never called (tests used the factory helper) | KILLABLE |
| `_matches` 5 | `" ".join` → `"XX XX".join` | Tokens are matched with `in haystack`; the separator is not a documented search surface | EQUIVALENT |
| `_sort_key` newest / session_count cases removed or `+` instead of `-` | Those sort keys never asserted (name and last_active were) | KILLABLE |
| `_sort_key` `or 0` → `or 1` on None lastMessageAtMs | None already sorts last via the first tuple element; the `or` value is only used inside the None bucket | EQUIVALENT |
| `derive_directory_page` 5, 10 | `now_ms()` / `at_ms` → None | Page assembler untested | KILLABLE |
| `derive_directory_page` 14 | `userId in blocked_ids` → `not in` | Blocked filter never driven through the page assembler | KILLABLE |

No DEAD CODE found. Every untested line was reachable from a public derive-on-read function.

---

# Adversarial pass

Mutmut only mutates in the ways it knows. For the three highest-risk functions:

### 1. `_apply_order` (money)

If I wanted a bug the suite would not catch: treat a lowercase Hubble status
(`"failed"`) as a failure, or treat SUCCESS with `vouchers: []` as succeeded.
The README's fail set is the uppercase trio; unknown stays pending — so
lowercase `"failed"` staying pending is **specified**, not a hole I should
invent a fail-rule for. SUCCESS with empty vouchers **is** specified ("settles
with or without its voucher") and already crashes (`vouchers[0]`) — recorded
in FINDINGS.md, left red. Accepted residual risk: Hubble sending a synonym
(`"FAILURE"`, `"CANCELED"` American spelling) would stay pending forever.

### 2. `_campaign_spend` (money)

If I wanted a bug the suite would not catch: apply the incentive cap **before**
multiplying blocks (so one block of ₹50 against a ₹200 cap still pays ₹50, but
the arithmetic identity `min(blocks * per, cap)` vs `blocks * min(per, cap)`
diverges when `perBlockInr > cap`). I wrote no extra test for that identity
because the existing property already asserts `spend == base + min(blocks * per, cap)`.
Accepted residual risk: swapping `onboards` and `blockSize` in the `//`
expression when both happen to be 5 (the default fixture). A dedicated
`onboards=10, blockSize=5` case already exists (`exactly one block` is 5/5;
capped 40/5 is 8 blocks). Low residual risk.

### 3. `offered_amounts` (money)

If I wanted a bug the suite would not catch: offer a flexible amount using
`max(maxVoucher, balance)` as the ceiling so a ₹90 balance against a ₹5000
Hubble max still lists ₹250. Existing tests pin `all(amount <= cap)` with
`cap = min(max_v, balance)` and a negative-balance empty list. Residual risk:
Hubble returning `status="active"` (lowercase) — the documented offerable
status is `"ACTIVE"`; lowercase would correctly yield `[]`. Not a hole.

---

# After killer tests

Re-run 2026-09-06 after the KILLABLE tests above (same runner, same deselects).

| | baseline | after killers |
|---|---|---|
| killed | 448 | **553** |
| survived | 103 | **11** (all EQUIVALENT; listed in triage) |
| no tests | 13 | **0** |
| timeout | 1 | **1** (`mint_handle` invert-`exists`) |
| score killed/(killed+survived) | 81.3% | **98.0%** (553/564) |

Per module after killers:

| file | total | killed | survived | timeout | score |
|---|---|---|---|---|---|
| gifting.py | 162 | 158 | 4 | 0 | 97.5% |
| ambassadors.py | 157 | 151 | 5 | 1 | 96.8% |
| influencers.py | 103 | 103 | 0 | 0 | 100% |
| directory.py | 113 | 111 | 2 | 0 | 98.2% |
| attribution.py | 30 | 30 | 0 | 0 | 100% |

The 11 survivors are exactly the EQUIVALENT rows in the triage table
(`zip(strict)` on equal-length gather, one-token join separator, unspecified
`ValueError` message, `_sort_key` `or 0` inside the None-timestamp bucket).
None were marked EQUIVALENT to save effort.

CI ratchet is now **98.0%** (`tests/mutation/check_threshold.py`,
`.github/workflows/mutation.yml`). Never lower it.

## Raw run snapshot (2026-09-06, after killers)

Checked in next to this file so a tests-only clone has the machine output, not
just this write-up. Regenerating mutmut still writes under `mutants/` at the
Sujho workspace root; copy those files here if the snapshot should move.

| file | what it is |
|---|---|
| [`mutmut-cicd-stats.json`](mutmut-cicd-stats.json) | killed / survived / timeout / total |
| [`mutmut-report.html`](mutmut-report.html) | every mutant: killed, survived, or timeout |
| [`mutmut-stats.json`](mutmut-stats.json) | which tests ran against which mutated function |
