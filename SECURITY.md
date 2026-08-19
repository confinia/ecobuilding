# SECURITY — EcoBuilding

Security posture, threat analysis, and disaster recovery. Structured loosely on
ISO/IEC 27001 Annex A control themes, scaled to a solo-run side project. This is
a working assessment, not a certification.

## 1. Assets & classification

| Asset | Confidentiality | Where | If lost / leaked |
|---|---|---|---|
| Open building data (BDNB/BAN/Géorisques) | Public | upstream + cache | No impact — re-fetchable |
| Source code | Low (private repo, but no secrets in it) | GitHub `confinia/ecobuilding` | Low — no secrets embedded |
| **User accounts / organizations** | **High** | Keycloak Postgres (`ecobuilding-auth_kc_pgdata`) | GDPR-relevant personal data; account takeover |
| **Leads (email, org, need)** | **High** | `data/leads/leads.jsonl` on VM | Sales pipeline + personal data exposure |
| Secrets (`deploy/secrets.env`) | **Critical** | VM only, `0600`, gitignored | Full compromise of DB, Grafana, KC admin |
| Grafana admin / dashboards | Medium | monitoring volume | Usage history loss; admin abuse |
| GitHub token (operator laptop) | **Critical** | operator env (`GH_TOKEN`) | Repo write + **delete_repo** (see §4) |

## 2. Current controls (what is in place)

- **Secrets management (A.9/A.10):** `secrets.env` is `0600`, gitignored, never
  committed. Verified: no password/token/key material across 65 commits.
  Generated on the VM (`openssl rand`), not shipped from the laptop.
- **Network exposure (A.13):** every service binds `127.0.0.1`; only the
  platform edge caddy owns public 80/443 (TLS, Let's Encrypt auto-renew).
  App stacks are unreachable from the internet except through the edge → router
  → stack chain.
- **Edge hardening (A.13):** scanner/probe paths (`/.env`, `/.git`, `wp-*`, …)
  return 403 and are logged; real client IP preserved for country metrics only
  (never stored).
- **Rootless containers (A.12):** podman rootless — a container escape lands on
  the unprivileged `debian` user, not root. `linger` on for reboot survival.
- **AuthN (A.9):** Keycloak (OIDC, Auth Code + PKCE public client); API
  validates RS256 JWTs against the realm JWKS, checks issuer and expiry.
  Registration currently open (self-serve) — email verification OFF (no SMTP
  yet — tracked; a hardening item before paid tiers).
- **Privacy (A.18):** free tier account-less; no cookies; IP → country in
  memory only, never persisted; usage is aggregate counters.
- **Zero-downtime deploys (A.12):** blue/green with manual promote gate;
  instant rollback.
- **Change control (A.12/A.14):** every change via GitHub issue → PR → tests →
  staging validation → promote.

## 3. CI/CD security — HONEST STATE

- **GitHub Actions is NOT active.** The workflow lives at
  `ci/github-workflow-ci.yml` (not `.github/workflows/`) because the operator
  token lacks the `workflow` scope. All test runs to date are **manual**, in a
  clean `python:3.12-slim` container on the VM. Consequence: no automated gate
  blocks a bad merge today — discipline is the only gate.
- **Deploy path is rsync-over-SSH from the laptop**, not a CI runner. No CI
  system holds production credentials → CI compromise cannot reach prod. The
  trust anchor is the **operator's SSH key and laptop**, not a pipeline.
- **Token scope is too broad:** `GH_TOKEN` carries `repo` + **`delete_repo`**.
  A leaked token could delete the repository. Action: reduce to `repo` (+
  `workflow` when enabling CI), drop `delete_repo`.
- **Activation (operator, when wanted):**
  `gh auth refresh -h github.com -s workflow`, move the workflow into
  `.github/workflows/ci.yml`, push. Until then use the pre-push gate below.

## 4. Compromise scenarios — "what does the attacker reach?"

1. **Leaked `GH_TOKEN`** → repo write + delete. *Not* prod (no deploy creds in
   GitHub). Mitigate: drop `delete_repo`; rotate on suspicion; enable 2FA.
2. **Operator laptop / SSH key compromise** → **full control** (SSH to VM,
   read `secrets.env`, all data). This is the single biggest blast radius.
   Mitigate: passphrase on the SSH key, disk encryption, `ssh-agent` timeout.
3. **VM / container escape** → rootless limits it to the `debian` user, but that
   user already has all app data + secrets, so effectively full app compromise.
   Mitigate: keep the host patched; minimize the exposed surface (done).
4. **`secrets.env` disclosure** → attacker gets KC admin, DB, Grafana admin →
   account data + ability to impersonate. Mitigate: `0600` (done); rotate all
   secrets if suspected; never copy it off-VM in cleartext.
5. **Keycloak compromise / registration abuse** → fake accounts, potential
   account takeover if email verification stays off. Mitigate: enable SMTP +
   email verification + rate-limiting before paid tiers.
6. **Supply chain (dependency / base image)** → pinned versions reduce drift;
   Dependabot/pip-audit recommended once CI is active.
7. **Payment layer** — not yet wired; when Polar lands, webhook **signature
   verification is mandatory** (specified in TEST_CREEM.md; TEST_POLAR.md is archived) so a forged
   webhook cannot provision a paid tier.

**Reachable sensitive data, worst case (laptop or VM compromise):** user
accounts, leads, all secrets. Everything else is public open data.

## 5. Disaster recovery

### 5.1 What can be lost, and how bad

| Data | Recoverable without backup? | RPO target | RTO target |
|---|---|---|---|
| Open data (cache) | Yes — re-fetch upstream | n/a | minutes |
| Code | Yes — GitHub | 0 | minutes |
| **User accounts (KC)** | **No** | ≤ 24h | ~1h |
| **Leads** | **No** | ≤ 24h | minutes |
| Grafana history | Partially (recreated empty) | best-effort | minutes |
| Secrets | No — but regenerated by deploy.sh (new values) | n/a | minutes* |

\* Regenerating secrets invalidates existing sessions and needs KC/DB
re-alignment — acceptable early, painful once real users exist → back them up
out-of-band once accounts are live.

### 5.2 Backup mechanism (`deploy/backup.sh`)

Backs up the irreplaceable, stateful data — **Keycloak Postgres (pg_dump),
`leads.jsonl`, Grafana volume** — into a single archive, **encrypted at rest
with `age`**. Retention: 14 local archives. Schedule via cron:

```
# on the VM
0 3 * * *  /home/debian/projects/ecobuilding/deploy/backup.sh >> ~/backups/backup.log 2>&1
```

⚠ **A backup on the same VM is not disaster recovery.** The archive is
`age`-encrypted specifically so it can be copied off-box safely (rclone to
object storage, scp to another host). Until an off-site copy exists, a VM loss
still loses everything. This is the top open DR item.

### 5.3 Recovery procedures

- **Restore accounts:** new VM → deploy stacks → `podman exec -i
  ecobuilding-auth_kc-db_1 psql -U keycloak keycloak < keycloak.sql`.
- **Restore leads:** copy `leads.jsonl` back to `data/leads/`.
- **Total VM loss:** provision VM → clone platform + ecobuilding repos →
  `./deploy/deploy.sh` (rebuilds everything from code) → restore the two data
  archives → repoint DNS if the IP changed. Estimated RTO ~1–2h with backups
  in hand; **unbounded without them** (accounts unrecoverable).
- **Bad deploy:** `./deploy/rollback.sh` (previous stack still running).
- **Secret compromise:** rotate `secrets.env` values → recreate auth + DB (or
  re-key), invalidate sessions, force password resets.

## 6. Prioritized remediation

| Priority | Item | Status |
|---|---|---|
| P0 | Automated encrypted backups (accounts + leads) | script added — needs cron + `age` key + **off-site copy** |
| P0 | Off-site backup copy | OPEN (operator) |
| P1 | Drop `delete_repo` from `GH_TOKEN`; enable GitHub 2FA | OPEN (operator) |
| P1 | Keycloak admin port 8181 bound to 0.0.0.0 (reachable by app containers via host gateway) is protected ONLY by ufw — verify 8181 stays out of the ufw allow-list; a scoped view-users service account would also reduce the API's KC privilege | ufw-dependent |
| P1 | SMTP + email verification + registration rate-limit before paid tiers | OPEN |
| P2 | Activate GitHub Actions (real CI gate) + Dependabot/pip-audit | OPEN (needs `workflow` scope) |
| P2 | SSH key passphrase + laptop disk encryption | operator hygiene |
| P3 | Polar webhook signature verification | specified, lands with #35 |

## 7. Incident response (solo)

1. **Contain:** suspected token/key leak → revoke it immediately (GitHub token
   settings / `ssh-keygen` new key + update `authorized_keys`).
2. **Rotate:** regenerate `secrets.env`, redeploy auth/DB.
3. **Assess:** check edge + API logs for the access window; leads/accounts are
   the sensitive scope.
4. **Notify:** if personal data (leads/accounts) was exposed, GDPR breach
   notification duties apply (CNIL, 72h) once real users exist.
5. **Recover:** restore from the latest good backup; document in a GitHub issue.
