"""Sign-up flow validation — SKIPPED until accounts exist (issue #27).

Planned automated coverage (activated when /v1/signup ships):
 1. POST /v1/signup {email} -> 201, api_key returned, key persisted
 2. duplicate email -> 409
 3. key grants >10 req/day (anonymous cap bypassed)
 4. anonymous 11th request within a day -> 429 with signup hint
 5. signup event counted in metrics (ecobuilding_signups_total)
"""

import pytest

pytestmark = pytest.mark.skip(
    reason="Sign-up not implemented yet (free account-less beta) — issue #27"
)


def test_signup_returns_api_key():
    raise NotImplementedError


def test_duplicate_email_rejected():
    raise NotImplementedError


def test_key_bypasses_anonymous_cap():
    raise NotImplementedError


def test_anonymous_cap_hints_signup():
    raise NotImplementedError
