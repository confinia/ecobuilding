"""Pro account registration via Polar.sh — SKIPPED until integrated (issue #35).

Planned automated coverage (Polar sandbox organization, activated with #35):
 1. GET /v1/pro/checkout -> redirect to Polar hosted checkout (sandbox)
 2. Polar webhook subscription.created (signed) -> pro key provisioned
 3. webhook with invalid signature -> 401, nothing provisioned
 4. subscription.canceled -> key downgraded to free tier
 5. pro key quota > free key quota
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Polar integration not implemented — issue #35 (wired when RULES.md #6 is met; sandbox tests first)"
)


def test_checkout_redirects_to_polar_sandbox():
    raise NotImplementedError


def test_webhook_provisions_pro_key():
    raise NotImplementedError


def test_webhook_signature_enforced():
    raise NotImplementedError


def test_cancellation_downgrades_key():
    raise NotImplementedError
