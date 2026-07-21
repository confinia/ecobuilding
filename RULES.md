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
