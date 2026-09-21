# Sujho tests

Private test suite for the [Sujho](https://github.com/Sujho/sujho) umbrella:
`user_service`, `infra`, `whatsapp_adapter`, `text_agent`, `document_worker`,
`redirect_service`.

This tree is the whole suite — tests, pipeline, CI copies, audits, pytest
catalog, coverage snapshot, and mutmut snapshot. Product code is not here.

**This clone cannot run by itself.** The suites import live product packages.
Place this tree at `tests/` inside a cloned Sujho workspace with submodules
initialized. Set `SUJHO_ROOT` if the umbrella is somewhere else.

```text
sujho/                  # github.com/Sujho/sujho + submodules
  user_service/ infra/ whatsapp_adapter/ text_agent/ ...
  tests/                # this repository
```

## What is in this folder

Everything that belongs to the test suite lives here:

| Path | Role |
|---|---|
| `unit/` | Pure derived-logic tests |
| `api/` | Per-service FastAPI route tests |
| `integration/` | Persistence / cross-service, Firestore emulator |
| `e2e/` | WhatsApp-pipeline journeys |
| `mutation/` | mutmut HTML renderer + 98.0% score ratchet |
| `tooling/` | Marker coverage, weak-assertion gates, pytest catalog renderer |
| `outcomes/` | Audits, findings, pytest catalog, coverage + mutmut snapshots |
| `ci/pipeline.py` | One entry point for every stage |
| `ci/github/` | Copies of the umbrella GitHub Actions workflows |
| `ci/pyproject.toml` | Copy of umbrella mutmut / coverage / ruff / mypy config |
| `ci/pre-commit-config.yaml` | Copy of umbrella pre-commit hooks |
| `ci/.secrets.baseline` | Copy of the umbrella detect-secrets baseline |

Nothing from the suite was left in `scripts/` or a parallel `Test-Suite/`
tree. Those are gone.

GitHub Actions, mutmut, ruff, mypy, and pre-commit still **read** the live
copies at the Sujho repo root (`.github/workflows/`, `pyproject.toml`,
`.pre-commit-config.yaml`, `.secrets.baseline`). The files under `ci/` are
kept in sync so this repo still has a copy of that config. Regenerating
mutmut still writes `mutants/` at the Sujho workspace root, not here.

## Recorded 2026-09-07

470 collected tests, 0 not-run. Full table:
[`outcomes/PYTEST_RESULTS.md`](outcomes/PYTEST_RESULTS.md).

| suite | passed | failed | skipped |
|---|---:|---:|---:|
| unit | 157 | 5 | 0 |
| api | 208 | 30 | 2 xfail (no local `soffice`) |
| integration | 37 | 10 | 0 |
| e2e | 17 | 4 | 0 |
| **all** | **419** | **49** | **2** |

Known-red tests were left failing on purpose (spec vs product). Write-up:
[`outcomes/FINDINGS.md`](outcomes/FINDINGS.md).

Combined `tests/unit` + `tests/api` coverage of `user_service/app/src` is
**93%** (`fail_under` on the umbrella is 90%). Mutation scope is five
`user_service` modules; last snapshot is **98.0%** killed
(553 killed, 11 survived, 1 timeout).

## How to run

From the **Sujho workspace root**, not from this folder:

```bash
python tests/ci/pipeline.py --list
python tests/ci/pipeline.py                  # static, secrets, unit, api, gates, coverage
python tests/ci/pipeline.py --all            # plus integration and e2e
python tests/ci/pipeline.py unit api
python tests/ci/pipeline.py mutation
python tests/ci/pipeline.py --with-install   # pip install, then the default stages
```

Pytest paths are unchanged: `pytest tests/unit`, `pytest tests/api`,
`pytest tests/integration`, `pytest tests/e2e`.

Integration and e2e need `gcloud` (Firestore emulator) and a JRE. On GitHub
those two stages are best-effort (`continue-on-error`). Locally `--all`
treats a failure as a real failure.

## Outcomes

| Path | What it is |
|---|---|
| [`outcomes/PYTEST_RESULTS.md`](outcomes/PYTEST_RESULTS.md) | Every collected test, last recorded pass/fail |
| [`outcomes/pytest/`](outcomes/pytest/) | Raw JUnit XML + `collected.json` + `results.json` |
| [`outcomes/coverage.xml`](outcomes/coverage.xml) | Combined unit+api coverage of `user_service/app/src` |
| [`outcomes/coverage.json`](outcomes/coverage.json) | Same coverage, JSON form |
| [`outcomes/FINDINGS.md`](outcomes/FINDINGS.md) | Known-red tests and product/spec mismatches |
| [`outcomes/MUTATION_BASELINE.md`](outcomes/MUTATION_BASELINE.md) | mutmut scope, oracle, 98.0% ratchet |
| [`outcomes/mutmut-report.html`](outcomes/mutmut-report.html) | Every mutant from the recorded run |
| [`outcomes/mutmut-cicd-stats.json`](outcomes/mutmut-cicd-stats.json) | killed / survived / timeout counts |
| [`outcomes/ASSERTION_AUDIT.md`](outcomes/ASSERTION_AUDIT.md) | Weak-assertion audit |
| [`outcomes/EXECUTION_AUDIT.md`](outcomes/EXECUTION_AUDIT.md) | Did passing tests actually run? |
| [`outcomes/UNCERTAINTY.md`](outcomes/UNCERTAINTY.md) | Open questions and tradeoffs |
| [`outcomes/MIRRORED_AND_WRONG.md`](outcomes/MIRRORED_AND_WRONG.md) | Tests that mirrored broken product behavior |

Regenerate snapshots after a suite run (from the Sujho root; integration/e2e
need `JAVA_HOME` pointing at a real JRE):

```bash
pytest tests/unit --junitxml=tests/outcomes/pytest/unit.xml
pytest tests/api --junitxml=tests/outcomes/pytest/api.xml
pytest tests/integration --junitxml=tests/outcomes/pytest/integration.xml
pytest tests/e2e --junitxml=tests/outcomes/pytest/e2e.xml
python tests/tooling/render_pytest_results.py --collect
pytest tests/unit tests/api -c tests/unit/pytest.ini \
  --cov=user_service/app/src --cov-branch \
  --cov-report=xml:tests/outcomes/coverage.xml \
  --cov-report=json:tests/outcomes/coverage.json
```
