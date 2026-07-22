#!/bin/bash
# EcoBuilding — restore the BDNB pgdump into the local PostGIS and expose it
# via PostgREST (issue #28). Run ON the VM AFTER the download completes:
#   ~/bdnb/bdnb_pgdump.tar.gz present (see the download step).
# Idempotent-ish: safe to re-run the restore into a fresh volume.
set -eu
cd "$(dirname "$0")/.."
BDNB_DIR=~/bdnb

echo "== 1. verify checksum"
cd "$BDNB_DIR"
echo "d6549a34930ef0d5bba7548471cc858a640c894bc54ced2c04c03d91907a1d34  bdnb_pgdump.tar.gz" | sha256sum -c - \
  || { echo "checksum mismatch — aborting"; exit 1; }

echo "== 2. extract"
tar xzf bdnb_pgdump.tar.gz    # -> a .sql / directory-format dump
DUMP=$(find . -maxdepth 2 -name "*.dump" -o -name "*.sql" | head -1)
echo "   dump artifact: ${DUMP:-<directory-format>}"

echo "== 3. secrets: BDNB DB password"
cd "$(dirname "$0")/.."
grep -q '^BDNB_DB_PASSWORD=' deploy/secrets.env || {
  P=$(openssl rand -hex 24)
  { echo "BDNB_DB_PASSWORD=$P"; echo "POSTGRES_PASSWORD=$P"; } >> deploy/secrets.env
}

echo "== 4. start bdnb-db"
( cd bdnb_stack && podman-compose -p ecobuilding-bdnb -f docker-compose.yml up -d bdnb-db )
echo "   waiting for postgres..."
until podman exec ecobuilding-bdnb_bdnb-db_1 pg_isready -U bdnb >/dev/null 2>&1; do sleep 3; done

echo "== 5. restore (this takes a while: ~120-160 GB)"
# pg_restore for directory/custom format; psql for plain SQL. Detect and run.
if [ -d "$BDNB_DIR"/*pgdump* ] 2>/dev/null || ls "$BDNB_DIR"/*.dump >/dev/null 2>&1; then
  ART=$(ls -d "$BDNB_DIR"/*.dump "$BDNB_DIR"/*pgdump*/ 2>/dev/null | head -1)
  podman exec -i ecobuilding-bdnb_bdnb-db_1 pg_restore -U bdnb -d bdnb --no-owner --no-privileges -j 4 < "$ART" \
    || cat "$ART" | podman exec -i ecobuilding-bdnb_bdnb-db_1 pg_restore -U bdnb -d bdnb --no-owner --no-privileges -j 4
else
  SQL=$(ls "$BDNB_DIR"/*.sql | head -1)
  cat "$SQL" | podman exec -i ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb
fi

echo "== 6. discover the BDNB schema + anon role for PostgREST"
SCHEMA=$(podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb -tAc \
  "select table_schema from information_schema.tables where table_name='batiment_groupe_complet' limit 1")
echo "   schema with batiment_groupe_complet: ${SCHEMA:-NOT FOUND}"
podman exec ecobuilding-bdnb_bdnb-db_1 psql -U bdnb -d bdnb <<SQL
DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='bdnb_anon') THEN CREATE ROLE bdnb_anon NOLOGIN; END IF; END \$\$;
GRANT USAGE ON SCHEMA ${SCHEMA} TO bdnb_anon;
GRANT SELECT ON ALL TABLES IN SCHEMA ${SCHEMA} TO bdnb_anon;
ALTER DEFAULT PRIVILEGES IN SCHEMA ${SCHEMA} GRANT SELECT ON TABLES TO bdnb_anon;
SQL
grep -q '^PGRST_DB_SCHEMAS=' deploy/secrets.env && sed -i "s/^PGRST_DB_SCHEMAS=.*/PGRST_DB_SCHEMAS=${SCHEMA}/" deploy/secrets.env \
  || echo "PGRST_DB_SCHEMAS=${SCHEMA}" >> deploy/secrets.env

echo "== 7. start PostgREST"
( cd bdnb_stack && podman-compose -p ecobuilding-bdnb -f docker-compose.yml up -d bdnb-rest )
sleep 5
echo "== smoke: local PostgREST"
curl -sS -m 10 "http://127.0.0.1:3005/batiment_groupe_complet?limit=1" | head -c 200; echo
echo "== done. Repoint the API by setting BDNB_LOCAL=1 (see docker-compose.yml)."
