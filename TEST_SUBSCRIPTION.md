# TEST_SUBSCRIPTION — new user sign-up validation

Covers the **sign-up / sign-in flow** (target architecture: Keycloak IdP).
Status of the feature itself: **not implemented yet** — tracked in
[#27](https://github.com/confinia/ecobuilding/issues/27) (keys/quotas) and
[#36](https://github.com/confinia/ecobuilding/issues/36) (Keycloak IdP + organizations).
This document defines the validation process now so tests flip from SKIPPED to
enforced as the feature lands. **No fabricated results: the results below are
from the real latest run.**

## Target flow under test (spec 2026-07-22)

1. Frontend shows **Sign up / Sign in** links (map topbar + offer page).
2. Auth is delegated to **Keycloak** (dedicated realm `confinia`, OIDC
   Authorization Code + PKCE, themed to feel integrated with the app).
3. Registration form requires the **organization** attribute (company/tenant);
   it is stored as a user attribute and mapped into the JWT (`org` claim).
4. After first login, the API auto-provisions a **free-tier key** bound to the
   user/org; `/v1/me` returns identity + org + tier.
5. Anonymous users keep a small daily cap (~10 req/day/IP) with a sign-up hint
   in the 429 response.

## Automated validation (CI)

Suite: `api/tests/test_subscription.py` — currently **SKIPPED** with the
explicit reason `Sign-up not implemented yet`. Planned cases (already written,
activated with the feature):

| # | Case | Asserts |
|---|---|---|
| 1 | `test_signup_returns_api_key` | signup via Keycloak → JWT accepted → free key provisioned, org claim present |
| 2 | `test_duplicate_email_rejected` | second registration with same email → error surfaced |
| 3 | `test_key_bypasses_anonymous_cap` | keyed requests exceed the anonymous daily cap |
| 4 | `test_anonymous_cap_hints_signup` | 11th anonymous request/day → 429 + sign-up hint |

Keycloak-specific additions planned with #36: token issuer/audience validation,
expired/forged token rejection, org claim required.

## Manual validation checklist (run before promoting the feature)

- [ ] « Créer un compte » visible on map + /offres.html
- [ ] Registration form requires organization; blank org rejected
- [ ] E-mail verification round-trip works
- [ ] Login → redirected back to the app, session persists on reload
- [ ] `/api/v1/me` shows email + organization + tier `free`
- [ ] Logout clears the session

## How to run

```sh
# VM / anywhere with podman (hermetic, no network calls in tests):
cd api && podman run --rm -v .:/w -w /w -e OTEL_METRIC_EXPORT_INTERVAL=600000 \
  docker.io/library/python:3.12-slim bash -c \
  "apt-get update -qq && apt-get install -y -qq libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core && pip install -q -r requirements.txt pytest && pytest tests -v"
```

GitHub Actions: workflow ready in `ci/github-workflow-ci.yml` — **not yet
active**: the current `GH_TOKEN` lacks the `workflow` scope. To activate:
`gh auth refresh -h github.com -s workflow`, then move the file to
`.github/workflows/ci.yml` and push.

## Last results (REAL run)

- **Date:** 2026-07-22 · **Environment:** `python:3.12-slim` container on the
  production VM (`cka-ovh-dedicated-01`) · **Branch:** `feat/keycloak-idp`
- **Outcome:** `11 passed, 6 skipped in 1.19s`

| Suite | Result |
|---|---|
| `test_api.py` (healthz, lookup validation, suggest, events, leads, PDF fiche) | ✅ 6 PASSED |
| `test_subscription.py` — JWT identity (/v1/me: no token, garbage, valid+org, wrong issuer, expired) | ✅ 5 PASSED |
| `test_subscription.py` — anonymous cap / key provisioning | ⏭ 2 SKIPPED (#27) |
| `test_polar.py` (4 cases) | ⏭ SKIPPED — see TEST_POLAR.md |
