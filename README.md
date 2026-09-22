# Sujho DevOps Plan

This folder is the plan for how Sujho code gets onto GitHub and then onto Google Cloud. None of it is turned on — putting this folder on GitHub changes nothing for real users.

Today the live product still updates the old way: a push to `main` starts a build and often ships a tag called `latest`.

The full plan is in [`docs/sujho-github-workflow-plan-full.md`](docs/sujho-github-workflow-plan-full.md).

## How shipping works

GitHub has one branch, `main`. Dev, Pre-Prod, and Prod are separate Google Cloud projects, not branches.

A merged pull request does not update a running app. A person opens one file, picks one service or job, and clicks Run.

Dev is a practice project. Pre-Prod is for phone testing. Prod is the real users. An image is built once, checked on Pre-Prod, and only then sent to Prod. Prod does not build it again.

Passwords stay in Google Cloud. GitHub only stores the login names, not the passwords.

## What is in this folder

```
phase1/        Who can approve a pull request
phase2/        Tests that run on a pull request
phase3/        An AI comment on a pull request
phase4/        Dev, Pre-Prod, Prod, approval, and rollback
  jobs/        Jobs that run and then stop
phase5/        An old check we removed
phase6/        A weekly report
docs/          The written plan
tests/         A copy of the product tests
Eval-Suite/    A copy of the evals
```

Phase 4 files are generated from `phase4/catalog.json`. Change the catalog, then regenerate. Do not edit the generated files by hand.

## Check on your laptop

```bash
for d in phase1 phase2 phase3 phase4 phase5 phase6 phase4/jobs; do
  (cd "$d" && python3 validate.py)
done
```

## Not done yet

- The Dev and Pre-Prod Google Cloud projects do not exist. Creating them costs money.
- The Prod connection name in these files is `sujho-github-dc`. The live name is `sujho-github-dc-org`.
- These files store images under `sujho-dev/services/<image>`. Live Prod stores them under `$PROJECT/<service>/api`.
- Nothing here creates Dev databases or passwords. Prod user data is not copied into Dev.
