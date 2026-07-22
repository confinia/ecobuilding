# TEST_POLAR — pro account registration validation (Polar.sh)

Covers the **pro plan registration** flow: a signed-in user (Keycloak, see
TEST_SUBSCRIPTION.md) subscribes via **Polar.sh** (Merchant of Record) and
gains pro abilities — normalized PDF building fiches with a daily quota,
higher API limits. Feature status: **not implemented** — tracked in
[#35](https://github.com/confinia/ecobuilding/issues/35); real-money wiring is
gated by RULES.md #6 (≥10k€ before incorporation); **sandbox** tests come first.
**No fabricated results: the results below are from the real latest run.**

## Target flow under test (spec 2026-07-22)

1. Signed-in user clicks **« Passer Pro »** → `GET /v1/pro/checkout` →
   redirect to the Polar hosted checkout (sandbox organization during beta).
2. Payment done → Polar sends the `subscription.created` **webhook** (signed);
   the API verifies the signature, matches the user/org, upgrades the tier.
3. Pro tier grants: PDF fiche downloads **N/day** (quota), batch lookups,
   higher API quotas; usage visible per org in Grafana.
4. `subscription.canceled` webhook → automatic downgrade to free.
5. All money flows through Polar as seller of record (EU VAT handled).

## Automated validation (CI)

Suite: `api/tests/test_polar.py` — currently **SKIPPED** with the explicit
reason `Polar integration not implemented`. Planned cases:

| # | Case | Asserts |
|---|---|---|
| 1 | `test_checkout_redirects_to_polar_sandbox` | authenticated checkout → 307 to Polar sandbox URL with org metadata |
| 2 | `test_webhook_provisions_pro_key` | signed `subscription.created` → tier=pro, quota active |
| 3 | `test_webhook_signature_enforced` | tampered signature → 401, no provisioning |
| 4 | `test_cancellation_downgrades_key` | `subscription.canceled` → tier=free |

Prerequisite (user action): create the Polar account + sandbox organization;
`POLAR_WEBHOOK_SECRET` and product IDs go to `deploy/secrets.env`.

## Manual validation checklist (sandbox, before any real money)

- [ ] « Passer Pro » visible only when signed in
- [ ] Checkout shows the pro plan with correct price and org name
- [ ] Sandbox test card completes; redirect back to the app confirmed
- [ ] Tier switches to `pro` (visible in `/api/v1/me`) within seconds
- [ ] PDF fiche quota enforced: N/day then explicit 429 with reset time
- [ ] Cancellation in Polar dashboard downgrades the account
- [ ] Invoice/receipt e-mail received from Polar (MoR)

## How to run

Same hermetic command as TEST_SUBSCRIPTION.md (`pytest api/tests -v`).
GitHub Actions activation: see TEST_SUBSCRIPTION.md (token `workflow` scope).

## Last results (REAL run)

- **Date:** 2026-07-22 · **Environment:** `python:3.12-slim` container on the
  production VM (`cka-ovh-dedicated-01`) · **Branch:** `feat/ci-test-harness`
- **Outcome:** `6 passed, 8 skipped in 1.19s`

| Suite | Result |
|---|---|
| `test_api.py` (existing API surface) | ✅ 6 PASSED |
| `test_polar.py` (4 cases) | ⏭ SKIPPED — integration not implemented (#35) |
| `test_subscription.py` (4 cases) | ⏭ SKIPPED — see TEST_SUBSCRIPTION.md |
