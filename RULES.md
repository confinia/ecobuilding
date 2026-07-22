# Working rules

1. **Every change is tracked in GitHub** (rule set 2026-07-21):
   - open an **issue** describing the change (bug, feature, infra, docs);
   - work happens on a **branch**, submitted as a **PR** referencing the issue
     (`Closes #N`);
   - merge → deploy to the candidate stack (`./deploy/deploy.sh`) → validate on
     https://next.ecobuilding.confinia.io → `./deploy/promote.sh`.
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
