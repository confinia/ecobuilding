# MOVE — relocate the EcoBuilding stack to a dedicated rootless user

**Status: ✅ APPLIED (2026-08-02).** The stack runs under the `ecobuilding` rootless
user; `debian` is used only for sudo / the shared platform edge; the `confinia`
user is legacy/empty. The old debian stack was kept for rollback then decommissioned.
Kept for reference; see `STACK_ecobuilding.md` for the current topology.

Goal: move the EcoBuilding stack on the VM from
`/home/debian/projects/ecobuilding` (running under the shared `debian` user) to
`/home/ecobuilding/projects/ecobuilding` (running under a dedicated
`ecobuilding` user), as part of the per-project-user reorganization already
started on the VM (`ecobuilding`, `maplibre`, `mapmax`, `overwatch`,
`indoorequal` users now exist).

Why: isolation (each project confined to its own user + rootless Podman
storage), least privilege, and clean quotas/limits per project.

---

## Access model (which SSH for which step)

Two entry points — **every command below is tagged with the one to use**:

- **`ssh debian`** — the admin user: has **nopasswd sudo** (root operations) **and
  owns the current stack + its rootless Podman volumes**. Use it for: root ops
  (linger, cross-home `rsync`/`chown`), stopping the old stacks, and **exporting**
  the existing volumes (they live in debian's store).
- **`ssh ecobuilding`** — the target rootless user. Use it for: **importing**
  volumes into ecobuilding's store and **bringing the stacks up** there.

Never run the target user's Podman "as debian" (`sudo -iu`): connect with
`ssh ecobuilding` so the rootless session (`XDG_RUNTIME_DIR`, pasta) is correct.

**Post-move operating model:** once the stack runs under `ecobuilding`, all
EcoBuilding VM work goes through **`ssh ecobuilding`** — do **not** use
`ssh debian` / `/home/debian/projects/ecobuilding` anymore (that copy is only a
stopped rollback until decommission). `ssh debian` is then reserved solely for
root-only tasks (platform edge edits, future `sudo`).

## 0. The key fact: rootless Podman storage is per-user

Podman runs **rootless**: every user has its own container/image/volume store
under `~/.local/share/containers/storage`, and its own UID/GID mapping
(`/etc/subuid`, `/etc/subgid`). Moving to a new user therefore is **not** just
`mv` of a directory — the named volumes (Postgres data, Grafana, …) live in
`debian`'s store and must be migrated deliberately. Bind-mounted data lives in
the repo tree and moves with it (with an ownership fix).

Consequence: this is a **cutover with a short downtime window**, not a live move
(the new user must bind the same 127.0.0.1 ports the old one is using, and only
one process can hold a port at a time).

---

## 1. Inventory — what has to move

### 1a. The repo + bind-mounted data (moves with the tree)
`/home/debian/projects/ecobuilding/` → `/home/ecobuilding/projects/ecobuilding/`
- Code, compose files, Caddyfiles, realm JSON.
- **Secrets (must move, keep perms):** `deploy/secrets.env`,
  `sandbox_stack/secrets.env`.
- **Bind-mounted runtime data (in-repo, moves with the tree):**
  - `data/geoip/` (GeoIP DB, provisioned outside git) — copy.
  - `data/leads/` — **business data: `leads.jsonl`, `keys.jsonl`, `pro.json`.
    Must be preserved.**
  - `sandbox_stack/data/leads/` — sandbox equivalents.

### 1b. Large external data (outside the repo)
- `/home/debian/bdnb/` — the BDNB dump: `bdnb_pgdump.tar.gz` (~40 GB) + extracted
  `pgdump/*.sql` (~171 GB) + `doc/`. Source for the `bdnb_pgdata` volume.
  **~210 GB.** Only needed if we re-restore rather than migrate the volume.

### 1c. Named Podman volumes (in `debian`'s rootless store — must be migrated)
Confirmed volume names (compose-prefixed) as `debian`:

| Volume | Project | Contents | Preserve? |
|---|---|---|---|
| `ecobuilding-auth_kc_pgdata` | ecobuilding-auth | **Keycloak prod DB — user accounts + orgs** | **YES (precious, small)** |
| `ecobuilding-sandbox_sandbox_kc_pgdata` | ecobuilding-sandbox | Sandbox Keycloak DB (test users) | Nice-to-have (small) |
| `ecobuilding-bdnb_bdnb_pgdata` | ecobuilding-bdnb | PostGIS: BDNB (~219 GB) + **DVF `dvf` schema** + `prices_for_building()` | Rebuildable, but re-restore is slow (see §4) |
| `ecobuilding-monitoring_prom_data` | ecobuilding-monitoring | Prometheus TSDB (metrics history) | Nice-to-have |
| `ecobuilding-monitoring_grafana_data` | ecobuilding-monitoring | Grafana dashboards | Nice-to-have |

> Possibly stale (verify/skip): `ecobuilding-blue_*`, `ecobuilding-green_*`
> (`prom_data`/`grafana_data`) — leftovers from an earlier per-stack monitoring
> layout; the app compose no longer defines them.
> Sizes: `podman system df -v` as `debian`.

### 1d. Rebuildable — no migration needed
Images (rebuilt from Dockerfiles), the blue/green app containers, the router
caddy, `bdnb-rest` (PostgREST, stateless), the `render` service (stateless).

---

## 2. Prerequisites on the new `ecobuilding` user

Already in place (verified via `ssh ecobuilding`): rootless Podman works
(`rootless: true`, pasta), and the subuid/subgid range is set
(`ecobuilding:427680:65536`). **Only linger is missing.**

```bash
# ssh debian  (root op)  — containers must survive logout/reboot:
sudo loginctl enable-linger ecobuilding
grep '^ecobuilding:' /etc/subgid || echo "WARN: add subgid range"   # verify subgid too

# ssh ecobuilding  — sanity:
podman info | grep -i rootless       # rootless: true
mkdir -p ~/projects
```

Ports: all stack ports are > 1024 (8020, 8021/8022, 8030, 8040, 8181, 3005),
so rootless binding is fine. host.containers.internal keeps working within the
new user's containers.

---

## 3. Migration steps (cutover)

Order matters. Do a maintenance window; announce brief downtime.

### 3.1 Stop the old stacks — `ssh debian` (owns them)
```bash
for p in ecobuilding-blue ecobuilding-green ecobuilding-edge ecobuilding-auth \
         ecobuilding-monitoring ecobuilding-bdnb ecobuilding-render ecobuilding-sandbox; do
  (cd ~/projects/ecobuilding && podman-compose -p "$p" ... down) 2>/dev/null || \
     podman ps -a --filter "label=io.podman.compose.project=$p" -q | xargs -r podman stop
done
```
(Stopping frees the ports and quiesces the Postgres volumes for a clean copy.)

### 3.2 Move the repo + in-repo data — `ssh debian` (needs sudo: cross-home)
```bash
sudo rsync -aHAX --info=progress2 /home/debian/projects/ecobuilding/ \
      /home/ecobuilding/projects/ecobuilding/
sudo chown -R ecobuilding:ecobuilding /home/ecobuilding/projects/ecobuilding
# secrets stay 600:
sudo chmod 600 /home/ecobuilding/projects/ecobuilding/deploy/secrets.env \
               /home/ecobuilding/projects/ecobuilding/sandbox_stack/secrets.env
```
Compose bind mounts are **relative** (`../deploy/secrets.env`, `./data/leads`),
so they stay valid after the move. `data/leads/*` (business data) comes along.

### 3.3 Migrate the precious named volumes (safe cross-user method)
Use `podman volume export | import` — it repacks into the new user's UID map
correctly (a raw `rsync` of `_data` would keep `debian`'s subordinate UIDs and
break Postgres). Small volumes first:
```bash
# ssh debian — export (volumes live in debian's store); /tmp so ecobuilding can read:
podman volume export ecobuilding-auth_kc_pgdata            -o /tmp/kc_pgdata.tar
podman volume export ecobuilding-sandbox_sandbox_kc_pgdata -o /tmp/sandbox_kc_pgdata.tar
# (+ ecobuilding-monitoring_grafana_data / _prom_data to keep dashboards/history)
chmod 644 /tmp/*.tar

# ssh ecobuilding — recreate under the SAME names the compose files expect, then import:
podman volume create ecobuilding-auth_kc_pgdata
podman volume import ecobuilding-auth_kc_pgdata /tmp/kc_pgdata.tar
podman volume create ecobuilding-sandbox_sandbox_kc_pgdata
podman volume import ecobuilding-sandbox_sandbox_kc_pgdata /tmp/sandbox_kc_pgdata.tar
```
> The Keycloak DB password in the moved `secrets.env` is the same value, so the
> migrated `kc_pgdata` authenticates unchanged.

### 3.4 The 219 GB `bdnb_pgdata` — pick one (§4 explains the trade-off)
- **Option A (recommended): migrate the volume** —
  `ssh debian`: `podman volume export ecobuilding-bdnb_bdnb_pgdata -o /tmp/bdnb.tar`
  then `ssh ecobuilding`: `podman volume create ecobuilding-bdnb_bdnb_pgdata &&
  podman volume import ecobuilding-bdnb_bdnb_pgdata /tmp/bdnb.tar`. Preserves BDNB
  **and** the loaded DVF schema + `prices_for_building()` in one shot. Needs
  ~219 GB free scratch and a few hours.
- **Option B: re-restore** — `ssh debian`:
  `sudo rsync -aHAX /home/debian/bdnb/ /home/ecobuilding/bdnb/ && sudo chown -R
  ecobuilding:ecobuilding /home/ecobuilding/bdnb` (~210 GB), then
  `ssh ecobuilding`: re-run `deploy/bdnb-import.sh` → `deploy/dvf-import.sh` →
  `psql < deploy/dvf-prices-function.sql`. Cleaner state, but re-runs both imports
  (longer). During this, prices/DVF are down; the API can temporarily fall back
  to public `api.bdnb.io` (unset `DVF_RPC_URL`).

### 3.5 Bring the stacks up — `ssh ecobuilding`
```bash
cd ~/projects/ecobuilding
./deploy/deploy.sh                 # blue/green app + router
( cd auth_stack && podman-compose -p ecobuilding-auth up -d )
( cd monitoring_stack && podman-compose -p ecobuilding-monitoring up -d )
( cd bdnb_stack && podman-compose -p ecobuilding-bdnb up -d )     # after volume in place
( cd render_stack && podman build -t ecobuilding-render . && podman-compose -p ecobuilding-render up -d )
./deploy/sandbox.sh                # sandbox stack
```
- Re-align the `bdnb` DB password **only if re-restoring** (Option B): as
  `ecobuilding`, `podman exec …bdnb-db psql -U bdnb -c "ALTER USER bdnb WITH
  PASSWORD '<POSTGRES_PASSWORD>'"`. Migrating the volume (Option A) keeps the
  password, so no change.
- **Edge caveat (see §5):** `deploy.sh`/`sandbox.sh` try to append vhosts to
  debian's `~/projects/platform/caddy/Caddyfile` — as `ecobuilding` that write
  **fails silently** (and is skipped anyway since the vhosts already exist). No
  action needed for a like-for-like move; new hostnames must be added from
  `ssh debian`.

---

## 4. `bdnb_pgdata` trade-off

It now holds **three things**: the ~219 GB BDNB import, the `dvf` schema
(18.8 M sales, from `dvf-import.sh`), and the `prices_for_building()` function.
- **Migrate the volume (A):** one transfer, exact state preserved, no re-import.
  Risk: large cross-user `export|import`; verify integrity after.
- **Re-restore (B):** predictable and clean, but re-runs BDNB + DVF imports
  (hours) and needs the 210 GB dump moved too.

Recommendation: **A** if scratch space allows; **B** as the fallback / if the
volume export is problematic.

---

## 5. Cross-user networking & the platform edge

- The platform edge (TLS/443) reverse-proxies `127.0.0.1:8020` (router) and the
  hostnames. **Loopback is shared across users**, so the edge reaches the new
  user's `:8020` with no change — as long as the router binds the same port.
- `host.containers.internal:PORT` (Keycloak 8181, PostgREST 3005, render 8040)
  keeps working: those services move to the **same** new user, and the ports are
  unchanged.
- **Caveat (confirmed):** `platform` is owned by **`debian`**
  (`/home/debian/projects/platform`). `deploy/sandbox.sh` and `deploy.sh` append
  vhosts to `~/projects/platform/caddy/Caddyfile` and reload
  `platform_caddy_1`. Once EcoBuilding runs as `ecobuilding`, that user **cannot
  write** debian's platform Caddyfile. The vhosts already exist, so a like-for-
  like move needs no new write — but **future edge changes** (new hostname,
  `staging.`, etc.) must be applied from `debian` (or `platform` gets its own
  user + a sudo/shared-write path). Options: (a) keep edge edits a `debian`/root
  task; (b) move `platform` to its own user too; (c) give `ecobuilding` a
  narrow sudoers entry to reload the platform caddy.

---

## 6. Verification checklist (post-cutover; container checks via `ssh ecobuilding`)

- [ ] `podman ps` — all stacks up (blue/green, edge, auth, monitoring, bdnb, render, sandbox).
- [ ] `loginctl show-user ecobuilding -p Linger` → `Linger=yes`.
- [ ] Prod: https://ecobuilding.confinia.io loads; `/api/v1/healthz` 200.
- [ ] **Auth preserved:** an existing account can still sign in (kc_pgdata OK).
- [ ] **Leads preserved:** `data/leads/leads.jsonl` present and non-empty.
- [ ] DVF prices: `/v1/buildings/{id}` returns a `prices` block (bdnb_pgdata OK).
- [ ] PDF renders (energy + prices + 3D map + annex).
- [ ] Sandbox: https://sandbox.ecobuilding.confinia.io loads; registration works.
- [ ] `./deploy/test.sh` green.
- [ ] Grafana dashboards present (if monitoring volumes migrated).

---

## 7. Rollback

Keep `debian`'s copy **intact and stopped** (do not delete) until the new user
is fully verified. To roll back: stop the `ecobuilding`-user stacks, restart the
`debian` stacks (`deploy.sh` etc.). Ports/hostnames are identical, so the edge
needs no change.

---

## 8. Decommission (only after a stable verification period)

```bash
# ssh debian — once the new user is proven over a few days:
podman volume rm ecobuilding-auth_kc_pgdata ecobuilding-sandbox_sandbox_kc_pgdata \
                 ecobuilding-bdnb_bdnb_pgdata ecobuilding-monitoring_prom_data \
                 ecobuilding-monitoring_grafana_data
podman system prune -a
rm -rf ~/projects/ecobuilding ~/bdnb
```

---

## 9. Risks & open questions

1. **Downtime**: a cutover window (minutes for app; hours if re-restoring bdnb).
   Mitigate by migrating the volume (Option A) instead of re-restoring.
2. **219 GB volume migration**: needs scratch space + time; verify integrity
   (`podman volume export` then a row-count sanity check on a table).
3. **Rootless UID remapping**: only `export|import` (not raw `rsync`) migrates
   Postgres volumes correctly across users.
4. **subuid range**: must not overlap other users' ranges.
5. **Platform edge ownership** (§5): confirm before the move.
6. **Access**: resolved — `ssh debian` gives the working stack + nopasswd sudo.
   (The `confinia` alias lands as the `confinia` user with no access to
   `debian`'s stack; use `debian` for EcoBuilding VM work until the move.)

---

## 9b. Gotchas hit during the actual move (fix these)

1. **podman-exporter socket path hardcoded to `debian`'s UID.**
   `monitoring_stack/docker-compose.yml` mounted `/run/user/1000/podman/podman.sock`.
   As `ecobuilding` (UID 1005) that path is permission-denied. **Fix (committed):**
   use `${XDG_RUNTIME_DIR}/podman/podman.sock` — portable across users. Also run
   `systemctl --user enable --now podman.socket` as `ecobuilding` first.
2. **Grafana volume import left files with the wrong mapped UID.**
   After `podman volume import`, `ecobuilding-monitoring_grafana_data` files were
   owned by a stray uid (428151) / the login uid (1005) instead of Grafana's 472,
   so Grafana crashed with *"attempt to write a readonly database"*. **Fix:**
   ```
   MP=$(podman volume inspect ecobuilding-monitoring_grafana_data --format '{{.Mountpoint}}')
   podman unshare chown -R 472:472 "$MP"   # Grafana runs as UID 472
   podman start ecobuilding-monitoring_grafana_1
   ```
   Postgres volumes (KC) imported cleanly; **Grafana needed the chown**. After any
   import, if a service errors on write, `podman unshare chown` the volume to the
   container's UID (Grafana 472, Prometheus 65534, Postgres 999).

## 10. TL;DR sequence

1. **`ssh debian`** (sudo): `loginctl enable-linger ecobuilding` (subuid already set).
2. **`ssh debian`**: stop the `ecobuilding-*` stacks.
3. **`ssh debian`** (sudo): `rsync` repo → `/home/ecobuilding/...`; `chown`; secrets 600.
4. **`ssh debian`** export → **`ssh ecobuilding`** import: `ecobuilding-auth_kc_pgdata`
   (+ sandbox + monitoring) via `/tmp/*.tar`.
5. `bdnb_pgdata`: migrate the volume (A, export/import) or re-restore (B).
6. **`ssh ecobuilding`**: bring stacks up; re-align bdnb password only if re-restored.
7. Verify (§6). Keep the `debian` copy **stopped but intact** as rollback.
8. **`ssh debian`**: decommission the `debian` copy after a stable period.
