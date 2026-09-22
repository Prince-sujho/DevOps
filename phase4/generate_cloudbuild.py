#!/usr/bin/env python3
"""Render Phase 4 Cloud Build YAML from catalog.json.

Do not edit the generated ci/*-build-deploy.yaml / *-deploy-only.yaml by
hand — change this file or catalog.json and re-run. validate.py fails on
drift.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / "catalog.json").read_text())


def cloudrun_services(catalog: dict | None = None) -> list[dict]:
    catalog = catalog or CATALOG
    return [s for s in catalog["services"] if s.get("kind") == "cloudrun"]


def indent_block(text: str, spaces: int) -> str:
    prefix = " " * spaces
    lines = text.split("\n")
    return "\n".join(prefix + line if line else line for line in lines)


def require_sha_script() -> str:
    return r"""set -euo pipefail
if [ -z "${_COMMIT_SHA}" ] || [ -z "${_SHORT_SHA}" ]; then
  echo "Refuse: _COMMIT_SHA/_SHORT_SHA empty. Pass them from the GitHub form."
  echo "Cloud Build trigger builtins (COMMIT_SHA/SHORT_SHA/TRIGGER_NAME) are not used."
  exit 1
fi
"""


def health_verify() -> str:
    return r"""set -euo pipefail
EXPECTED_COMMIT=$$(cat /workspace/deploy.commit)
EXPECTED_DIGEST=$$(cat /workspace/deploy.digest)
REV=$$(cat /workspace/deploy.revision)
echo "Expected commit: $$EXPECTED_COMMIT"
echo "Expected digest: $$EXPECTED_DIGEST"
echo "Revision (no user traffic yet): $$REV"
REV_URL=$$(gcloud run revisions describe "$$REV" --project="${_TARGET_PROJECT}" --region="${_REGION}" --format='value(status.url)')
if [ -z "$$REV_URL" ]; then
  echo "Revision $$REV has no URL — cannot verify without sending users there."
  exit 1
fi
echo "Revision URL: $$REV_URL"
sleep 5
for i in $$(seq 1 15); do
  HTTP_STATUS=$$(curl -s -o /dev/null -w '%{http_code}' "$$REV_URL/health" || echo '000')
  VERSION_JSON=$$(curl -fsS "$$REV_URL/version" || true)
  RUNNING_COMMIT=$$(python3 -c 'import json,sys; t=(sys.stdin.read() or "").strip(); print(json.loads(t).get("release_commit_sha","") if t.startswith("{") else "")' <<< "$$VERSION_JSON")
  RUNNING_DIGEST=$$(python3 -c 'import json,sys; t=(sys.stdin.read() or "").strip(); print(json.loads(t).get("release_image_digest","") if t.startswith("{") else "")' <<< "$$VERSION_JSON")
  if [ "$$HTTP_STATUS" = "200" ] && [ "$$RUNNING_COMMIT" = "$$EXPECTED_COMMIT" ] && [ "$$RUNNING_DIGEST" = "$$EXPECTED_DIGEST" ]; then
    echo "Deployment verified on the revision URL. Users still on the previous revision."
    exit 0
  fi
  echo "Attempt $$i/15: health=$$HTTP_STATUS commit=$${RUNNING_COMMIT:-<none>} digest=$${RUNNING_DIGEST:-<none>}"
  sleep 3
done
echo "Verification failed. Traffic was not shifted."
exit 1
"""


def revision_verify() -> str:
    return r"""set -euo pipefail
EXPECTED_COMMIT=$$(cat /workspace/deploy.commit)
EXPECTED_DIGEST=$$(cat /workspace/deploy.digest)
REV=$$(cat /workspace/deploy.revision)
echo "Expected commit: $$EXPECTED_COMMIT"
echo "Expected digest: $$EXPECTED_DIGEST"
echo "Revision (no user traffic yet): $$REV"
for i in $$(seq 1 15); do
  if [ -n "$$REV" ] && gcloud run revisions describe "$$REV" --project="${_TARGET_PROJECT}" --region="${_REGION}" --format=json | python3 -c 'import json,sys; rev=json.load(sys.stdin); ready=next((c.get("status") for c in rev.get("status",{}).get("conditions",[]) if c.get("type")=="Ready"),""); env={e["name"]: e.get("value","") for e in rev.get("spec",{}).get("containers",[{}])[0].get("env",[])}; print("ready=%s commit=%s digest=%s" % (ready, env.get("RELEASE_COMMIT_SHA",""), env.get("RELEASE_IMAGE_DIGEST",""))); raise SystemExit(0 if ready=="True" and env.get("RELEASE_COMMIT_SHA")==sys.argv[1] and env.get("RELEASE_IMAGE_DIGEST")==sys.argv[2] else 1)' "$$EXPECTED_COMMIT" "$$EXPECTED_DIGEST"; then
    echo "Deployment verified: revision is Ready and matches expected release. Users still on the previous revision."
    exit 0
  fi
  echo "Attempt $$i/15 did not match expected release."
  sleep 3
done
echo "Verification failed. Traffic was not shifted."
exit 1
"""


def admin_iam() -> str:
    return r"""
        PROJECT_NUMBER=$$(gcloud projects describe "${_TARGET_PROJECT}" --format='value(projectNumber)')
        gcloud run services add-iam-policy-binding "${_SERVICE_NAME}" \
          --project="${_TARGET_PROJECT}" \
          --region="${_REGION}" \
          --member="serviceAccount:service-$${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
          --role=roles/run.invoker \
          --quiet
"""


def gcloud_run_deploy(svc: dict) -> str:
    flags = "\n".join(f"          {flag} \\" for flag in svc.get("run_args", []))
    iam = admin_iam() if svc["id"] == "admin" else ""
    return f"""SA="${{_RUNTIME_SERVICE_ACCOUNT}}"
if [ -z "$$SA" ]; then
  SA="${{_SERVICE_NAME}}-run@${{_TARGET_PROJECT}}.iam.gserviceaccount.com"
fi
DEPLOY_DIGEST=$$(cat /workspace/deploy.digest)
DEPLOY_COMMIT=$$(cat /workspace/deploy.commit)
IMAGE_REF="${{_REGISTRY}}/${{_IMAGE}}@$${{DEPLOY_DIGEST}}"
echo "Deploying image: $$IMAGE_REF"
echo "Release commit: $$DEPLOY_COMMIT"
echo "Runtime SA: $$SA"
if [ "${{_TARGET_PROJECT}}" = "sujho-preprod" ] || [ "${{_TARGET_PROJECT}}" = "sujho-dev" ]; then
  MIN_INSTANCES=0
else
  MIN_INSTANCES={svc["min_instances"]}
fi
echo "min-instances=$$MIN_INSTANCES (Pre-Prod and Dev are 0)"
gcloud run deploy "${{_SERVICE_NAME}}" \\
          --project="${{_TARGET_PROJECT}}" \\
          --region="${{_REGION}}" \\
          --image="$$IMAGE_REF" \\
          --platform=managed \\
          --service-account="$$SA" \\
{flags}
          --update-env-vars="GOOGLE_CLOUD_PROJECT=${{_TARGET_PROJECT}},GOOGLE_CLOUD_LOCATION=${{_REGION}},RELEASE_COMMIT_SHA=$$DEPLOY_COMMIT,RELEASE_IMAGE_DIGEST=$$DEPLOY_DIGEST" \\
          --min-instances=$$MIN_INSTANCES \\
          --max-instances={svc["max_instances"]} \\
          --cpu={svc["cpu"]} \\
          --memory={svc["memory"]} \\
          --timeout={svc["timeout"]} \\
          --no-traffic \\
          --quiet
REV=$$(gcloud run services describe "${{_SERVICE_NAME}}" --project="${{_TARGET_PROJECT}}" --region="${{_REGION}}" --format='value(status.latestReadyRevisionName)')
if [ -z "$$REV" ]; then
  echo "No ready revision after deploy."
  exit 1
fi
printf '%s' "$$REV" > /workspace/deploy.revision
echo "Created revision $$REV with no user traffic"
{iam}"""


def shift_traffic() -> str:
    return r"""set -euo pipefail
REV=$$(cat /workspace/deploy.revision)
echo "Shifting 100% traffic to $$REV"
gcloud run services update-traffic "${_SERVICE_NAME}" \
  --project="${_TARGET_PROJECT}" \
  --region="${_REGION}" \
  --to-revisions="$$REV=100" \
  --quiet
"""


def verify_block(svc: dict) -> str:
    if svc.get("verify") == "revision":
        return revision_verify()
    return health_verify()


def git_source_sujho(catalog: dict) -> str:
    return f"""dependencies:
  - gitSource:
      repository:
        developerConnect: projects/${{PROJECT_ID}}/locations/{catalog["region"]}/connections/${{_DC_CONNECTION}}/gitRepositoryLinks/sujho-sujho
      revision: ${{_COMMIT_SHA}}
      depth: 1
      destPath: .
"""


def render_build_deploy(svc: dict, catalog: dict) -> str:
    gcloud = catalog["gcloud"]
    kaniko = catalog["kaniko"]
    digest = f"/workspace/{svc['id']}.digest"
    extra_steps = ""
    kaniko_wait = "checkout-pins"
    if svc.get("pre_kaniko") == "assets":
        extra_steps = f"""
  - name: node:22-slim
    id: build-assets
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        cd {svc["gitlink"]}/app
        npm ci
        npm run build
    waitFor: [checkout-pins]
"""
        kaniko_wait = "build-assets"
    verify = indent_block(verify_block(svc).rstrip(), 8)
    require = indent_block(require_sha_script().rstrip(), 8)
    return f"""# {svc["id"]}-build-deploy.yaml — manual Cloud Build only (no push trigger).
# Build once, tag sha-<7 of _SHORT_SHA>, deploy that digest to _TARGET_PROJECT
# (default: sujho-preprod). Building does not mean approved: never writes the
# promotion tag. gitSource is sujho at _COMMIT_SHA only; service + infra come
# from gitlink SHAs. Run this job for THIS service only.
# Submit from GitHub with --project=sujho-dev so Kaniko can push.

{git_source_sujho(catalog)}options:
  logging: CLOUD_LOGGING_ONLY

substitutions:
  _SERVICE_NAME: {svc["cloud_run"]}
  _IMAGE: {svc["image"]}
  _REGION: {catalog["region"]}
  _REGISTRY: {catalog["registry"]}
  _TARGET_PROJECT: {catalog["preprod_project"]}
  _COMMIT_SHA: ""
  _SHORT_SHA: ""
  _DC_CONNECTION: {catalog["dc_connection"]}
  _RUNTIME_SERVICE_ACCOUNT: ""

steps:
  - name: {gcloud}
    id: require-sha
    entrypoint: bash
    args:
      - -c
      - |
{require}

  - name: {gcloud}
    id: checkout-pins
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        python3 ci/checkout-gitlinks.py --paths {svc["gitlink"]} infra
    waitFor: [require-sha]
{extra_steps}
  - name: {kaniko}
    id: build-and-push
    args:
      - --dockerfile={svc["dockerfile"]}
      - --context=dir://.
      - --destination=${{_REGISTRY}}/${{_IMAGE}}:sha-${{_SHORT_SHA}}
      - --digest-file={digest}
      - --cache=true
      - --cache-ttl=168h
    waitFor: [{kaniko_wait}]

  - name: {gcloud}
    id: deploy
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        DEPLOY_DIGEST=$$(cat {digest})
        DEPLOY_COMMIT="${{_COMMIT_SHA}}"
        if [ -z "$$DEPLOY_COMMIT" ] || [ -z "$$DEPLOY_DIGEST" ]; then
          echo "Refuse: missing _COMMIT_SHA or image digest."
          exit 1
        fi
        printf '%s' "$$DEPLOY_COMMIT" > /workspace/deploy.commit
        printf '%s' "$$DEPLOY_DIGEST" > /workspace/deploy.digest
{indent_block(gcloud_run_deploy(svc).rstrip(), 8)}
    waitFor: [build-and-push]

  - name: {gcloud}
    id: verify
    entrypoint: bash
    args:
      - -c
      - |
{verify}
    waitFor: [deploy]

  - name: {gcloud}
    id: shift-traffic
    entrypoint: bash
    args:
      - -c
      - |
{indent_block(shift_traffic().rstrip(), 8)}
    waitFor: [verify]

timeout: {svc["build_timeout"]}
"""


def render_deploy_only(svc: dict, catalog: dict) -> str:
    gcloud = catalog["gcloud"]
    require = indent_block(require_sha_script().rstrip(), 8)
    verify = indent_block(verify_block(svc).rstrip(), 8)
    return f"""# {svc["id"]}-deploy-only.yaml — manual Cloud Build only (no push trigger).
# No image build. Deploy the digest of sha-<7 of _SHORT_SHA>. Confirm
# preprod-approved still points at that same digest (no floating-tag TOCTOU).
# _IMAGE_DIGEST if set must match. prod-live is applied when _TARGET_PROJECT
# is sujho-478914 (derived from the project, not a separate _ENV knob).

{git_source_sujho(catalog)}options:
  logging: CLOUD_LOGGING_ONLY

substitutions:
  _SERVICE_NAME: {svc["cloud_run"]}
  _IMAGE: {svc["image"]}
  _REGION: {catalog["region"]}
  _REGISTRY: {catalog["registry"]}
  _TARGET_PROJECT: {catalog["preprod_project"]}
  _COMMIT_SHA: ""
  _SHORT_SHA: ""
  _DC_CONNECTION: {catalog["dc_connection"]}
  _RUNTIME_SERVICE_ACCOUNT: ""
  _IMAGE_DIGEST: ""

steps:
  - name: {gcloud}
    id: require-sha
    entrypoint: bash
    args:
      - -c
      - |
{require}

  - name: {gcloud}
    id: resolve-digest
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        SHORT="${{_SHORT_SHA}}"
        if [ -z "$$SHORT" ]; then
          echo "Refuse: _SHORT_SHA empty."
          exit 1
        fi
        SHA_DIGEST=$$(gcloud artifacts docker images describe \\
          "${{_REGISTRY}}/${{_IMAGE}}:sha-$$SHORT" \\
          --format="value(image_summary.digest)")
        if [ -z "$$SHA_DIGEST" ]; then
          echo "Refuse: no image ${{_IMAGE}}:sha-$$SHORT — this commit was never built."
          exit 1
        fi
        TAG_DIGEST=$$(gcloud artifacts docker images describe \\
          "${{_REGISTRY}}/${{_IMAGE}}:preprod-approved" \\
          --format="value(image_summary.digest)")
        if [ -z "$$TAG_DIGEST" ]; then
          echo "No image tagged preprod-approved — nothing eligible to deploy."
          exit 1
        fi
        if [ "$$SHA_DIGEST" != "$$TAG_DIGEST" ]; then
          echo "Refuse: sha-$$SHORT ($$SHA_DIGEST) is not preprod-approved ($$TAG_DIGEST). Tag moved or this commit was not approved."
          exit 1
        fi
        if [ -n "${{_IMAGE_DIGEST}}" ] && [ "${{_IMAGE_DIGEST}}" != "$$SHA_DIGEST" ]; then
          echo "Refuse: passed _IMAGE_DIGEST does not match sha-$$SHORT."
          exit 1
        fi
        echo "Deploying pinned digest: $$SHA_DIGEST (sha-$$SHORT, confirmed preprod-approved)"
        printf '%s' "$$SHA_DIGEST" > /workspace/deploy.digest
        COMMIT="${{_COMMIT_SHA}}"
        if [ -z "$$COMMIT" ]; then
          echo "Refuse: _COMMIT_SHA empty."
          exit 1
        fi
        echo "Promoted commit: $$COMMIT"
        printf '%s' "$$COMMIT" > /workspace/deploy.commit
    waitFor: [require-sha]

  - name: {gcloud}
    id: deploy
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
{indent_block(gcloud_run_deploy(svc).rstrip(), 8)}
    waitFor: [resolve-digest]

  - name: {gcloud}
    id: verify
    entrypoint: bash
    args:
      - -c
      - |
{verify}
    waitFor: [deploy]

  - name: {gcloud}
    id: shift-traffic
    entrypoint: bash
    args:
      - -c
      - |
{indent_block(shift_traffic().rstrip(), 8)}
    waitFor: [verify]

  - name: {gcloud}
    id: tag-prod-live
    entrypoint: bash
    args:
      - -c
      - |
        set -euo pipefail
        if [ "${{_TARGET_PROJECT}}" = "sujho-478914" ]; then
          DIGEST=$$(cat /workspace/deploy.digest)
          gcloud artifacts docker tags add \\
            "${{_REGISTRY}}/${{_IMAGE}}@$$DIGEST" \\
            "${{_REGISTRY}}/${{_IMAGE}}:prod-live"
          echo "Tagged $$DIGEST as prod-live"
        else
          echo "Not prod (_TARGET_PROJECT=${{_TARGET_PROJECT}}) — skipping prod-live tag"
        fi
    waitFor: [shift-traffic]

timeout: {svc["build_timeout"]}
"""


def render_all(catalog: dict | None = None) -> dict[str, str]:
    catalog = catalog or CATALOG
    files: dict[str, str] = {}
    for svc in cloudrun_services(catalog):
        files[f"ci/{svc['id']}-build-deploy.yaml"] = render_build_deploy(svc, catalog)
        files[f"ci/{svc['id']}-deploy-only.yaml"] = render_deploy_only(svc, catalog)
    return files


def write_all(dest: Path | None = None) -> list[Path]:
    dest = dest or HERE
    written = []
    for rel, body in render_all().items():
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body if body.endswith("\n") else body + "\n")
        written.append(path)
    return written


def main() -> int:
    paths = write_all()
    for p in paths:
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
