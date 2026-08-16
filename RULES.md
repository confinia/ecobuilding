# Working rules

1. **Every change is tracked in GitHub** (rule set 2026-07-21):
   - open an **issue** describing the change (bug, feature, infra, docs);
   - work happens on a **branch**, submitted as a **PR** referencing the issue
     (`Closes #N`);
   - merge → deploy to the candidate stack (`./deploy/deploy.sh`) → validate on
     https://staging.ecobuilding.confinia.io → `./deploy/promote.sh`.
   Direct commits to `main` are reserved for emergency production fixes
   (document them in an issue afterwards).
2. Dev code lives in this repo (`confinia/ecobuilding`, private); Dockerfile +
   docker-compose.yml are the deployment contract (podman-compose on the VM).
3. Blue/green gate: production only changes through `promote.sh` after manual
   validation on staging. No automatic failover to unvalidated versions.
4. No AI co-author attribution in commits or PRs.
5. Communication: under-promise — announce only what already works.
6. **English everywhere in the repo** (rule set 2026-07-22): all code comments
   AND all markdown documentation are written in English. Exception:
   user-facing product content (UI strings, PDF fiche wording, forum/social
   post drafts in LAUNCH.md) may be French — that is content, not documentation.
   Existing French comments/docs are migrated opportunistically when files are
   touched.
7. **No company creation below a 10k€ invoice** (rule set 2026-07-21): no legal
   structure, no Stripe, no paid offers until at least one ≥10k€ deal is
   secured. Until then the product stays free (beta) and monetization effort
   targets 10k€-scale opportunities, not small transactions.
8. **French writing style** (rule set 2026-07-22, applies to French replies,
   posts, and UI text): never use the em dash "—"; use parentheses or commas
   instead. No space before a comma. No space before a colon ":" (operator's
   preference, overrides the standard French thin space).
9. **Every issue ships a test** (rule set 2026-07-22): each issue/feature must
   add a unit test OR an end-to-end test that exercises it (in `api/tests/` or
   an e2e check). The test suite is run after every deployment via
   `./deploy/test.sh` (staging), and the change is not promoted until it
   passes. Tests for not-yet-implemented flows may be `skip`-marked, never
   faked. Existing features without a test get one added when next touched.
10. **Keep pulling toward business & marketing** (rule set 2026-07-22): often,
    proactively remind the operator of the concrete business/marketing actions
    that improve the odds of making money with the product (announce, reply to
    leads/community, talk to buyers, SEO, pricing). Engineering is a means, not
    the goal: flag when we are over-building features while demand/distribution
    actions sit undone.
11. **Submit GitHub prose for approval first** (rule set 2026-08-03): any comment
    or description posted to a GitHub issue or PR (issue/PR body, review comment,
    reply, close comment) must be shown to the operator in full and approved
    before it is submitted. Never post to GitHub without explicit validation.
    Creating the issue/PR itself and code are fine; the prose that becomes public
    is what needs sign-off.
12. **Always link the environment** (rule set 2026-08-03): whenever a reply
    mentions the sandbox, staging, or production environment, include the
    hyperlink to the live SaaS app. The pre-prod host follows the code's state:
    - production — https://ecobuilding.confinia.io (promoted, live)
    - staging — https://staging.ecobuilding.confinia.io (code already merged on
      `main`; the blue/green candidate validated before promote)
    - sandbox — https://sandbox.ecobuilding.confinia.io (code on a branch / open
      PR, validated before merge)
    `next.ecobuilding.confinia.io` must not exist.
13. **Hyperlink every issue/PR reference** (rule set 2026-08-03): whenever a reply
    or document exposes a reference to a GitHub issue or PR (e.g. `#103`), render
    it as a hyperlink to the issue/PR
    (https://github.com/confinia/ecobuilding/pull/103 or `/issues/N`), not bare
    text.
14. **Deploy only via GitHub Actions** (rule set 2026-08-03): all deployments run
    through GitHub Actions CI/CD — never manual `rsync`/`deploy.sh` (those are
    reserved for maintenance / break-glass only). The pipeline mirrors code state:
    - open or updated **PR on a branch** → auto-deploy to **sandbox**
      (https://sandbox.ecobuilding.confinia.io);
    - **PR merged to `main`** → auto-deploy to **staging** (the blue/green
      candidate, https://staging.ecobuilding.confinia.io);
    - **promote** → switch staging ↔ production so the change reaches end users
      (https://ecobuilding.confinia.io).
15. **Keep ISSUES.md in sync** (rule set 2026-08-04): every working session that
    creates or advances a GitHub issue or PR also updates the `ISSUES.md`
    tracker in the same session — one row per issue with its lifecycle status
    (filed → PR open → merged, on staging → promoted, in production → closed)
    and where it can be checked (environment links per rule 12). Recently
    shipped issues stay listed until promoted to production.
16. **Always hand off the next move** (rule set 2026-08-11): every time an
    action finishes (issue closed, PR merged, deploy validated), the session's
    wrap-up ends by recommending the next GitHub issue or PR to work on — one
    concrete pick from the ISSUES.md tracker with a one-line why, hyperlinked
    per rule 13. Business/marketing actions may override the engineering pick
    (rule 10).
17. **Default-yes execution** (rule set 2026-08-12, amends rule 11): never
    prompt when the possible answers are only yes / "yes, allow script
    execution" / no — the default IS yes: scripts run, and prepared
    issue/PR/comment prose is posted (still drafted with the same care and
    reported afterwards, but without waiting for sign-off). Prompt the
    operator ONLY when the decision is a genuine choice between alternatives
    beyond yes/no.
18. **Every post ships with its how-to** (rule set 2026-08-15): any message
    prepared for an external channel comes with full operating details in
    `COMMUNICATION.md` — exact URL to go to, which account/identity to use,
    title to use, whether to reply to an existing thread or open a new one,
    channel etiquette, and where to log the timestamp (LAUNCH.md). The copy
    itself lives in LAUNCH.md; COMMUNICATION.md is the per-channel how.
19. **App-running tests belong to CI** (rule set 2026-08-16): any test that
    exercises the RUNNING application (e2e against sandbox/staging, usage or
    billing simulations, render checks) is executed by the GitHub Actions
    pipeline, never manually from a workstation. Manual runs are for debugging
    only; if a check matters, it is a workflow step so every PR re-proves it.
20. **Verify CI outcomes, don't assume them** (rule set 2026-08-16): after
    launching a pipeline run, confirm what actually happened — `gh run view`
    for the authoritative status, and `./deploy/check-mail.sh` on the VM for
    the ops mailbox (alert@confinia.io over IMAP, same OVH creds as the SMTP
    sender): CI notifications, Grafana alerts and above all **bounces** land
    there. A silent mailbox is part of "it works"; an unread bounce is an
    outage nobody sees. Note: `contact@confinia.io` is a REDIRECTION (no
    mailbox, unreadable by the session) and GitHub notifies the owner's
    personal inbox only — so each workflow mails its own failures via
    `deploy/ci-notify.sh` (To contact@, Cc alert@) to keep them visible on
    both sides.
