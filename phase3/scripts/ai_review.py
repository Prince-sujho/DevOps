#!/usr/bin/env python3
"""Two-pass AI review. Billing, auth, or parse errors fail open — never block merge.

The workflow posts review-result.json. Important findings fail the `ai-review`
gate job. Nits never fail it. fail_open=true also never fails it.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MODEL = "claude-sonnet-4-6"
NIT_CAP = 5
RESULT_PATH = Path("review-result.json")

PASS1_SYSTEM = """You are reviewing a pull request diff for Sujho, an education \
platform delivered over WhatsApp to users. Call them "users" only — never \
"students and teachers" in findings. You have two jobs:

1. Review the diff against the rubric below. Trace the actual execution path — \
simulate what happens when this code runs, don't just pattern-match phrases. A \
change that looks correct but isn't, on tracing it through, is the most valuable \
thing to catch.

2. Triage the static-analysis findings you're given (from Semgrep and Bandit). \
For each one, decide TRUE POSITIVE or FALSE POSITIVE, with a one-line reason.

--- REVIEW RUBRIC (REVIEW.md) ---
{review_md}
--- END RUBRIC ---

Output strict JSON only, no markdown, no commentary outside the JSON:
{{
  "review_findings": [
    {{"severity": "important"|"nit", "file": "...", "line": <int>, "issue": "...", "reasoning": "..."}}
  ],
  "static_triage": [
    {{"tool": "semgrep"|"bandit", "rule_id": "...", "verdict": "true_positive"|"false_positive", "reasoning": "..."}}
  ]
}}"""

PASS2_SYSTEM = """You are the second reviewer in a two-pass review of the same \
pull request diff for Sujho. The first pass already found some issues — listed \
below. Do NOT repeat them. Your only job is to find what the first pass missed.

Read the diff fresh and ask: what correctness, security, or behavioral issue \
would a careful engineer catch that isn't already listed? Pay particular \
attention to categories that are easy to miss on a first read for this codebase: \
duplicate-delivery safety (Meta webhooks are at-least-once), event-ordering \
assumptions, single-instance state coupling (whatsapp is pinned to \
max-instances=1), Cloud Run timeout budgets, and concurrent-write races on \
Firestore/Neo4j.

--- PASS 1 FINDINGS (do not repeat) ---
{pass1_findings}
--- END PASS 1 FINDINGS ---

Output strict JSON only:
{{
  "missed_findings": [
    {{"severity": "important"|"nit", "file": "...", "line": <int>, "issue": "...", "reasoning": "..."}}
  ]
}}
If there is genuinely nothing new, return an empty array — do not pad with \
rephrased duplicates of Pass 1's findings."""


def write_result(findings: list, fail_open: bool, reason: str = "") -> None:
    payload = {"findings": findings, "fail_open": fail_open, "reason": reason}
    RESULT_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def spend_cap_hit() -> str | None:
    cap = os.environ.get("SPEND_CAP_INR", "").strip()
    so_far = os.environ.get("SPEND_SO_FAR_INR", "").strip()
    if not cap or not so_far:
        return None
    try:
        if float(so_far) >= float(cap):
            return f"spend cap hit ({so_far} >= {cap} INR) — failing open"
    except ValueError:
        return None
    return None


def parse_model_json(text: str) -> dict:
    raw = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1)
    return json.loads(raw)


def load_static_findings() -> list[dict]:
    findings: list[dict] = []
    try:
        semgrep = json.loads(Path("semgrep-results.json").read_text())
        for item in semgrep.get("results", []):
            findings.append(
                {
                    "tool": "semgrep",
                    "rule_id": item.get("check_id", ""),
                    "file": item.get("path", ""),
                    "line": item.get("start", {}).get("line", 0),
                    "message": item.get("extra", {}).get("message", ""),
                }
            )
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    try:
        bandit = json.loads(Path("bandit-results.json").read_text())
        for item in bandit.get("results", []):
            findings.append(
                {
                    "tool": "bandit",
                    "rule_id": item.get("test_id", ""),
                    "file": item.get("filename", ""),
                    "line": item.get("line_number", 0),
                    "message": item.get("issue_text", ""),
                }
            )
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return findings


def cap_nits(findings: list[dict]) -> list[dict]:
    important = [f for f in findings if f.get("severity") == "important"]
    nits = [f for f in findings if f.get("severity") == "nit"][:NIT_CAP]
    other = [f for f in findings if f.get("severity") not in {"important", "nit"}]
    return important + nits + other


def merge_passes(pass1: dict, pass2: dict) -> list[dict]:
    out: list[dict] = []
    out.extend(pass1.get("review_findings") or [])
    for item in pass1.get("static_triage") or []:
        if item.get("verdict") == "true_positive":
            out.append(
                {
                    "severity": "important",
                    "file": item.get("file") or item.get("rule_id") or "",
                    "line": item.get("line") or 0,
                    "issue": f"[{item.get('tool', 'static')}] {item.get('reasoning', '')}",
                }
            )
    seen = {(f.get("file"), f.get("issue")) for f in out}
    for item in pass2.get("missed_findings") or []:
        key = (item.get("file"), item.get("issue"))
        if key in seen:
            continue
        out.append(item)
        seen.add(key)
    return cap_nits(out)


def call_claude(system: str, user: str) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return parse_model_json(resp.content[0].text)


def main() -> int:
    reason = spend_cap_hit()
    if reason:
        print(reason, file=sys.stderr)
        write_result([], fail_open=True, reason=reason)
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        reason = "ANTHROPIC_API_KEY missing — failing open"
        print(reason, file=sys.stderr)
        write_result([], fail_open=True, reason=reason)
        return 0

    try:
        diff = Path("pr.diff").read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        reason = "pr.diff missing — failing open"
        print(reason, file=sys.stderr)
        write_result([], fail_open=True, reason=reason)
        return 0

    try:
        review_md = Path("REVIEW.md").read_text(encoding="utf-8")
    except FileNotFoundError:
        review_md = "(no REVIEW.md in this repo yet — reviewing on general correctness/security judgment only)"

    static_findings = load_static_findings()
    try:
        pass1 = call_claude(
            PASS1_SYSTEM.format(review_md=review_md),
            f"DIFF:\n{diff}\n\nSTATIC ANALYSIS FINDINGS:\n{json.dumps(static_findings, indent=2)}",
        )
        pass2 = call_claude(
            PASS2_SYSTEM.format(pass1_findings=json.dumps(pass1.get("review_findings") or [], indent=2)),
            f"DIFF:\n{diff}",
        )
        findings = merge_passes(pass1, pass2)
    except Exception as exc:
        reason = f"AI review call failed, failing open: {exc}"
        print(reason, file=sys.stderr)
        write_result([], fail_open=True, reason=reason)
        return 0

    write_result(findings, fail_open=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
