"""EcoBuilding API — per-building intelligence on French open data.

Versioning: all routes live under /v1. Breaking changes will ship as /v2;
/v1 keeps working. The public mount point is /api (stripped by the edge
proxy; root_path keeps the OpenAPI docs URLs correct).

Data sources (all open, keyless):
  - BAN  (api-adresse.data.gouv.fr)   — geocoding, Licence Ouverte
  - BDNB (api.bdnb.io, CSTB)          — per-building attributes, Licence Ouverte v2
  - Géorisques (georisques.gouv.fr)   — natural/technological risks, Licence Ouverte
"""

import asyncio
import logging
import math
import os
import time
from collections import OrderedDict

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("ecobuilding")

BAN_URL = "https://api-adresse.data.gouv.fr/search/"
BAN_REVERSE_URL = "https://api-adresse.data.gouv.fr/reverse/"
# Overridable so we can cut over to the self-hosted BDNB (local PostgREST,
# issue #28) with config only, no code change. Defaults = the public BDNB API.
BDNB_URL = os.environ.get(
    "BDNB_URL", "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet/adresse")
BDNB_BASE_URL = os.environ.get(
    "BDNB_BASE_URL", "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet")
# Group <-> addresses relation (#152): a bâtiment groupe can span several
# streets; this lists every address attached to it.
BDNB_REL_ADR_URL = os.environ.get(
    "BDNB_REL_ADR_URL", "https://api.bdnb.io/v1/bdnb/donnees/rel_batiment_groupe_adresse")
# DVF home prices via the local PostgREST RPC (#89). Empty in prod until the
# self-hosted stack is live; when set, building records carry a `prices` block
# (recent parcelle sales + commune median €/m²).
DVF_RPC_URL = os.environ.get("DVF_RPC_URL", "")
# Headless DPE-3D map render for the PDF context page (#88). Empty in prod until
# the render service is wired; when set, the report shows the rendered building.
RENDER_URL = os.environ.get("RENDER_URL", "")
GEORISQUES_URL = "https://georisques.gouv.fr/api/v1/resultats_rapport_risque"
# Groundwater (#119): Hub'Eau piezometry (ADES/BRGM) — nearest active station's
# water-table depth. Keyless, Licence Ouverte.
HUBEAU_STATIONS_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations"
HUBEAU_CHRONIQUES_URL = "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques"
# Solar PV (#119): PVGIS (EU JRC) — yearly yield per kWc at the location.
# Keyless, Europe-wide (reusable for the country-expansion work, #118).
PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
# Drinking-water service indicators (#171): SISPEA per commune via Hub'Eau —
# network efficiency P104.3 (rendement: 70% = 30% leaked) + price D102.0.
SISPEA_URL = "https://hubeau.eaufrance.fr/api/v0/indicateurs_services/communes"
# Official DPE record (#189): BDNB links each groupe to its representative
# dwelling's DPE (identifiant_dpe); the ADEME observatoire then serves the
# official document's substance (annual € costs, insulation quality, systems).
BDNB_REP_DPE_URL = os.environ.get(
    "BDNB_REP_DPE_URL",
    "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_dpe_representatif_logement")
ADEME_DPE_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
ADEME_DPE_SELECT = ",".join((
    "cout_total_5_usages", "cout_chauffage", "cout_ecs", "cout_eclairage",
    "cout_auxiliaires", "cout_refroidissement", "qualite_isolation_enveloppe",
    "qualite_isolation_menuiseries", "qualite_isolation_plancher_bas",
    "qualite_isolation_plancher_haut_comble_perdu",
    "description_installation_chauffage_n1", "description_installation_ecs_n1",
    "type_energie_n1", "type_energie_n2"))

# Rental-ban calendar, loi Climat et Résilience (verified 2026-07-20).
DPE_BAN_DATES = {"G": "2025-01-01", "F": "2028-01-01", "E": "2034-01-01"}

# GeoIP: country-level only (dbip-country-lite), resolved in memory — the IP
# itself is never stored nor logged, matching the "no tracking" promise.
_geoip = None
try:
    import maxminddb

    _GEOIP_DB = os.environ.get("GEOIP_DB", "/geoip/dbip-country-lite.mmdb")
    if os.path.exists(_GEOIP_DB):
        _geoip = maxminddb.open_database(_GEOIP_DB)
except Exception as e:  # missing db/lib must never break the API
    logging.getLogger("ecobuilding").warning("GeoIP unavailable: %s", e)


def _client_country(request: Request) -> str:
    if _geoip is None:
        return "unknown"
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    try:
        rec = _geoip.get(ip) or {}
        return rec.get("country", {}).get("iso_code") or "unknown"
    except Exception:
        return "unknown"

app = FastAPI(
    title="EcoBuilding API",
    version="1.0.0",
    description=(
        "Per-building intelligence for France built on open data: energy class (DPE), "
        "rental-ban status (loi Climat et Résilience), natural risks, construction "
        "attributes and solar potential — one key, one call, one normalized schema.\n\n"
        "Data: BDNB (CSTB), BAN, Géorisques — Licence Ouverte. "
        "Attribution required when redistributing."
    ),
    root_path="/api",
    docs_url="/v1/docs",
    openapi_url="/v1/openapi.json",
    redoc_url="/v1/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- OpenTelemetry -----------------------------------------------------------
# Metrics flow: SDK -> OTLP/http -> otel-collector -> Prometheus -> Grafana.
# The app must run fine without a collector (local dev): exporter failures are
# logged by the SDK, never raised.
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_resource = Resource.create({"service.name": "ecobuilding-api"})
_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(),
    # CI/tests set a huge interval so the exporter never fires without a collector.
    export_interval_millis=int(os.environ.get("OTEL_METRIC_EXPORT_INTERVAL", "15000")),
)
metrics.set_meter_provider(MeterProvider(resource=_resource, metric_readers=[_reader]))
_meter = metrics.get_meter("ecobuilding")

M_REQUESTS = _meter.create_counter(
    "ecobuilding_api_requests", description="API requests", unit="1"
)

# --- Identity gauges (internal dashboard #61): live Keycloak user & org counts.
# Polled from the KC Admin API via an OTel observable gauge, cached 60s. Uses
# bootstrap admin creds (KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD from secrets.env);
# a scoped service account is a SECURITY.md hardening item.
KC_ADMIN_BASE = os.environ.get("KC_ADMIN_BASE", "https://ecobuilding.confinia.io/auth")
KC_ADMIN_USER = os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
KC_ADMIN_PASSWORD = os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "")
_kc_cache = {"ts": 0.0, "users": 0, "orgs": 0, "org_members": {}}


def _poll_keycloak() -> dict:
    now = time.monotonic()
    if now - _kc_cache["ts"] < 60:
        return _kc_cache
    try:
        from collections import Counter
        with httpx.Client(timeout=5.0) as c:
            tok = c.post(
                f"{KC_ADMIN_BASE}/realms/master/protocol/openid-connect/token",
                data={"grant_type": "password", "client_id": "admin-cli",
                      "username": KC_ADMIN_USER, "password": KC_ADMIN_PASSWORD},
            ).json()["access_token"]
            h = {"Authorization": f"Bearer {tok}"}
            users = c.get(f"{KC_ADMIN_BASE}/admin/realms/confinia/users/count", headers=h).json()
            lst = c.get(f"{KC_ADMIN_BASE}/admin/realms/confinia/users",
                        headers=h, params={"max": 10000, "briefRepresentation": False}).json()
            members = Counter(
                u["attributes"]["organization"][0]
                for u in lst
                if u.get("attributes", {}).get("organization")
            )
            _kc_cache.update(ts=now, users=int(users), orgs=len(members),
                             org_members=dict(members))
    except Exception as e:
        log.warning("Keycloak poll failed: %s", e)
    return _kc_cache


def _obs_users(options):
    from opentelemetry.metrics import Observation
    return [Observation(_poll_keycloak()["users"])]


def _obs_orgs(options):
    from opentelemetry.metrics import Observation
    return [Observation(_poll_keycloak()["orgs"])]


def _obs_org_members(options):
    from opentelemetry.metrics import Observation
    return [Observation(n, {"org": org})
            for org, n in _poll_keycloak()["org_members"].items()]


_meter.create_observable_gauge("ecobuilding_kc_users", callbacks=[_obs_users],
                               description="Keycloak user accounts")
_meter.create_observable_gauge("ecobuilding_kc_organizations", callbacks=[_obs_orgs],
                               description="Distinct organizations (user attribute)")
_meter.create_observable_gauge("ecobuilding_kc_org_members", callbacks=[_obs_org_members],
                               description="Members per organization")
M_LOOKUPS = _meter.create_counter(
    "ecobuilding_lookups", description="Building lookups", unit="1"
)
M_FRONTEND = _meter.create_counter(
    "ecobuilding_frontend_events", description="Frontend usage events", unit="1"
)

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

FastAPIInstrumentor.instrument_app(app)
HTTPXClientInstrumentor().instrument()


@app.middleware("http")
async def count_requests(request, call_next):
    response = await call_next(request)
    M_REQUESTS.add(
        1,
        {
            "route": request.url.path,
            "method": request.method,
            "status": str(response.status_code),
        },
    )
    return response


# --- Helpers -----------------------------------------------------------------

_client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "ecobuilding.confinia.io"})

# In-process TTL+LRU cache on upstream calls. Guards the BDNB free tier
# (10k calls/month) against traffic spikes; building data changes rarely.
_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 5000
M_CACHE = _meter.create_counter("ecobuilding_upstream_cache", description="Upstream cache hits/misses", unit="1")


async def _cached_get_json(url: str, params: dict, ttl: float):
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        _CACHE.move_to_end(key)
        M_CACHE.add(1, {"result": "hit"})
        return hit[1]
    M_CACHE.add(1, {"result": "miss"})
    resp = await _client.get(url, params=params)
    resp.raise_for_status()
    data = resp.json()
    _CACHE[key] = (now, data)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return data


async def _dvf_prices(bdnb_id: str):
    """DVF price block for a building (recent parcelle sales + commune median
    €/m²), via the local PostgREST RPC. None when DVF is not wired or on error,
    so a DVF hiccup never breaks the building record."""
    if not DVF_RPC_URL:
        return None
    try:
        return await _cached_get_json(DVF_RPC_URL, {"bdnb_id": bdnb_id}, ttl=86400)
    except Exception as e:
        log.warning("DVF prices failed for %s: %s", bdnb_id, e)
        return None


async def _building_map_png(lon, lat, bdnb_id, bearing: float = -30.0):
    """Rendered DPE-3D map (PNG data URI) centered on the building, via the
    headless render service (#88). None when not wired or on error, so the
    report always generates."""
    if not RENDER_URL or lon is None or lat is None:
        return None
    try:
        r = await _client.get(RENDER_URL, params={
            "lon": lon, "lat": lat, "zoom": 18, "pitch": 60,
            "bearing": bearing, "bdnb_id": bdnb_id}, timeout=45.0)
        r.raise_for_status()
        import base64
        return "data:image/png;base64," + base64.b64encode(r.content).decode()
    except Exception as e:
        log.warning("building map render failed for %s: %s", bdnb_id, e)
        return None


def _rental_ban(dpe_class: str | None) -> dict | None:
    if not dpe_class:
        return None
    date = DPE_BAN_DATES.get(dpe_class.upper())
    return {
        "dpe_class": dpe_class.upper(),
        "rental_ban_date": date,
        "note": (
            f"Location interdite à partir du {date} (loi Climat et Résilience)"
            if date
            else "Aucune interdiction de location prévue pour cette classe"
        ),
    }


def _normalize_building(r: dict) -> dict:
    """BDNB batiment_groupe_complet/adresse row -> stable public schema (v1)."""
    return {
        "bdnb_id": r.get("batiment_groupe_id"),
        "address": r.get("libelle_adr_principale_ban"),
        "construction_year": r.get("annee_construction"),
        "height_m": r.get("hauteur_mean"),
        "floors": r.get("nb_niveau"),
        "dwellings": r.get("nb_log"),
        "wall_material": r.get("mat_mur_txt"),
        "roof_material": r.get("mat_toit_txt"),
        "energy": {
            "dpe_class": r.get("classe_bilan_dpe"),
            "dpe_date": r.get("date_reception_dpe"),
            "consumption_kwh_m2y": r.get("conso_5_usages_ep_m2"),
            "ghg_kgco2_m2y": r.get("emission_ges_5_usages_m2"),
            "dpe_class_counts": {
                c: r.get(f"nb_classe_bilan_dpe_{c.lower()}") for c in "ABCDEFG"
            },
            "rental_ban": _rental_ban(r.get("classe_bilan_dpe")),
        },
        "risks": {
            "clay_shrink_swell": r.get("alea_argile"),
        },
        "cooling": {
            # BDNB fields from DPE — answers the OSM-FR "carte des lieux
            # climatisés" thread (issue #23).
            "generator_type": r.get("type_generateur_climatisation"),
            "generator_age": r.get("type_generateur_climatisation_anciennete"),
            "has_cooling": bool(r.get("type_generateur_climatisation")),
        },
        "solar": {
            "thermal_favourable": r.get("batenr_favorabilite_solaire_thermique"),
            "thermal_potential_kwh_y": r.get("batenr_potentiel_prod_solaire_thermique_annuelle"),
        },
        "consumption_2020": {
            "residential_elec_kwh": r.get("conso_res_dle_elec_2020"),
            "residential_gas_kwh": r.get("conso_res_dle_gaz_2020"),
        },
    }


# --- Routes ------------------------------------------------------------------


@app.get("/v1/healthz", tags=["meta"])
async def healthz():
    return {"status": "ok", "service": "ecobuilding-api", "api_version": "v1"}


@app.get("/v1/suggest", tags=["geocoding"])
async def suggest(q: str = Query(min_length=3, description="Partial address, street or city")):
    """Autocomplete (BAN): cities, streets and full addresses.

    `type` is one of municipality | street | locality | housenumber; only
    housenumber entries can be looked up as buildings — others are navigation
    targets.
    """
    data = await _cached_get_json(BAN_URL, {"q": q, "limit": 6}, ttl=3600)
    feats = data.get("features", [])
    return {
        "suggestions": [
            {
                "label": f["properties"]["label"],
                "ban_id": f["properties"]["id"],
                "type": f["properties"].get("type"),
                "city": f["properties"].get("city"),
                "lon": f["geometry"]["coordinates"][0],
                "lat": f["geometry"]["coordinates"][1],
            }
            for f in feats
        ]
    }


async def _area_risks(lon, lat):
    if lon is None or lat is None:
        return None
    try:
        gj = await _cached_get_json(GEORISQUES_URL, {"latlon": f"{lon},{lat}"}, ttl=86400)
        return {
            "commune": (gj.get("commune") or {}).get("libelle"),
            "report_url": gj.get("url"),
            "risques_naturels": [
                k
                for k, v in (gj.get("risquesNaturels") or {}).items()
                if isinstance(v, dict) and v.get("present")
            ],
            "risques_technologiques": [
                k
                for k, v in (gj.get("risquesTechnologiques") or {}).items()
                if isinstance(v, dict) and v.get("present")
            ],
        }
    except httpx.HTTPError as e:
        log.warning("Géorisques unavailable: %s", e)
        return None


def _haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


async def _groundwater(lon, lat):
    """Water-table block (#119): nearest ACTIVE piezometer (Hub'Eau niveaux_nappes,
    ADES/BRGM) + its latest measured depth. Honest-data: the measurement is at a
    station, not on the parcel — the station distance is always returned and the
    depth is never interpolated. None on failure so a Hub'Eau hiccup never breaks
    a building record."""
    if lon is None or lat is None:
        return None
    try:
        d = 0.15  # ~11-17 km search box around the building
        st = await _cached_get_json(HUBEAU_STATIONS_URL, {
            "bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}",
            # Only stations still in service with a real history: central Paris
            # e.g. holds 1300+ piezometers of which almost all are historical.
            # "In service" = debut <= date <= fin, and fin lags weeks behind the
            # last real measurement — asking for "today" excludes everything, so
            # ask for "active 60 days ago" (verified live on Hub'Eau, #119).
            "date_recherche": time.strftime("%Y-%m-%d", time.gmtime(time.time() - 60 * 86400)),
            "nb_mesures_piezo_min": "50",
            "size": "200", "format": "json"}, ttl=86400)
        stations = [s for s in (st.get("data") or [])
                    if s.get("x") is not None and s.get("y") is not None]
        if not stations:
            return {"available": False,
                    "note": "Aucun piézomètre actif à proximité (réseau Hub'Eau/ADES)"}
        near = min(stations, key=lambda s: _haversine_m(lon, lat, s["x"], s["y"]))
        chron = await _cached_get_json(HUBEAU_CHRONIQUES_URL, {
            "code_bss": near["code_bss"], "size": "1", "sort": "desc",
            "format": "json"}, ttl=86400)
        m = (chron.get("data") or [{}])[0]
        return {
            "available": True,
            "station_code_bss": near.get("code_bss"),
            "station_commune": near.get("nom_commune"),
            "station_distance_m": round(_haversine_m(lon, lat, near["x"], near["y"])),
            "water_table_depth_m": m.get("profondeur_nappe"),
            "level_masl": m.get("niveau_nappe_eau"),
            "measured_on": m.get("date_mesure"),
            "note": ("Profondeur mesurée au piézomètre le plus proche, pas sur la "
                     "parcelle: la nappe varie localement."),
            "well_regulation": ("Tout puits ou forage à usage domestique (< 1000 m³/an) "
                                "doit être déclaré en mairie (décret n° 2008-652)."),
        }
    except Exception as e:
        log.warning("Hub'Eau groundwater failed for %s,%s: %s", lon, lat, e)
        return None


async def _solar_pv(lon, lat):
    """PV yield block (#119): PVGIS (EU JRC, keyless) — yearly production of a
    1 kWc system at optimal fixed tilt, plus plane-of-array irradiation. None on
    failure, same graceful pattern as DVF."""
    if lon is None or lat is None:
        return None
    try:
        pv = await _cached_get_json(PVGIS_URL, {
            "lat": round(lat, 4), "lon": round(lon, 4), "peakpower": "1",
            "loss": "14", "optimalinclination": "1", "outputformat": "json"},
            ttl=86400)
        tot = ((pv.get("outputs") or {}).get("totals") or {}).get("fixed") or {}
        if tot.get("E_y") is None:
            return None
        angle = ((((pv.get("inputs") or {}).get("mounting_system") or {})
                  .get("fixed") or {}).get("slope") or {}).get("value")
        return {
            "yield_kwh_per_kwc_y": tot.get("E_y"),
            "irradiation_kwh_m2_y": tot.get("H(i)_y"),
            "optimal_tilt_deg": angle,
            "assumptions": ("1 kWc, pertes système 14 %, inclinaison fixe optimale "
                            "(PVGIS v5.2)"),
        }
    except Exception as e:
        log.warning("PVGIS failed for %s,%s: %s", lon, lat, e)
        return None


async def _do_lookup(q, ban_id, address, lon, lat):
    rows = await _cached_get_json(
        BDNB_URL, {"cle_interop_adr": f"eq.{ban_id}", "limit": "5"}, ttl=86400
    )
    if not isinstance(rows, list):
        log.warning("BDNB error: %s", rows)
        rows = []

    commune = rows[0].get("code_commune_insee") if rows else None
    first_id = rows[0].get("batiment_groupe_id") if rows else None
    (risks, groundwater, solar_pv, water_network, official_dpe,
     local_taxes, schools) = await asyncio.gather(
        _area_risks(lon, lat), _groundwater(lon, lat), _solar_pv(lon, lat),
        _water_network(commune), _official_dpe(first_id) if first_id else _noop(),
        _local_taxes(commune), _nearby_schools(lon, lat))

    M_LOOKUPS.add(1, {"status": "ok" if rows else "no_building"})
    sources = [
        "BDNB (CSTB) — Licence Ouverte v2.0",
        "BAN — Licence Ouverte",
        "Géorisques — Licence Ouverte",
    ]
    if groundwater:
        sources.append("Hub'Eau piézométrie (ADES/BRGM) — Licence Ouverte")
    if solar_pv:
        sources.append("PVGIS (JRC) — © Union européenne")
    if water_network:
        sources.append("SISPEA / OFB (services d'eau) — Licence Ouverte")
    if official_dpe and official_dpe.get("dpe_number"):
        sources.append("ADEME — Observatoire DPE — Licence Ouverte")
    if local_taxes:
        sources.append("DGFiP — Fiscalité directe locale — Licence Ouverte")
    if schools:
        sources.append("Annuaire de l'éducation (MENJ) — Licence Ouverte")
    return {
        "query": {"q": q, "ban_id": ban_id, "address": address, "lon": lon, "lat": lat},
        "buildings": [_normalize_building(r) for r in rows],
        "area_risks": risks,
        "groundwater": groundwater,
        "solar_pv": solar_pv,
        "water_network": water_network,
        "official_dpe": official_dpe,
        "local_taxes": local_taxes,
        "schools": schools,
        "sources": sources,
    }


@app.get("/v1/lookup", tags=["buildings"])
async def lookup(
    request: Request,
    q: str | None = Query(None, description="Free-text address"),
    ban_id: str | None = Query(None, description="BAN interop id, e.g. 80021_6370_00007"),
    lon: float | None = Query(None, description="Longitude (used for the risk report when ban_id is given)"),
    lat: float | None = Query(None, description="Latitude (idem)"),
):
    """Address -> geocode (BAN) -> building record (BDNB) -> risk report (Géorisques)."""
    _meter_if_keyed(request, "lookup")
    if not q and not ban_id:
        raise HTTPException(422, "Provide q or ban_id")

    address = None
    if not ban_id:
        geo = await _cached_get_json(BAN_URL, {"q": q, "limit": 1, "type": "housenumber"}, ttl=86400)
        feats = geo.get("features", [])
        if not feats:
            M_LOOKUPS.add(1, {"status": "address_not_found"})
            raise HTTPException(404, "Address not found (BAN)")
        p = feats[0]["properties"]
        ban_id, address = p["id"], p["label"]
        lon, lat = feats[0]["geometry"]["coordinates"][:2]

    return await _do_lookup(q, ban_id, address, lon, lat)


@app.get("/v1/reverse", tags=["buildings"])
async def reverse(
    request: Request,
    lon: float = Query(description="Longitude (e.g. from GPS)"),
    lat: float = Query(description="Latitude"),
):
    """GPS position -> nearest address (BAN reverse) -> building record (BDNB)."""
    _meter_if_keyed(request, "reverse")
    geo = await _cached_get_json(BAN_REVERSE_URL, {"lon": lon, "lat": lat, "type": "housenumber"}, ttl=86400)
    feats = geo.get("features", [])
    if not feats:
        M_LOOKUPS.add(1, {"status": "reverse_not_found"})
        raise HTTPException(404, "No address near this position (BAN reverse)")
    p = feats[0]["properties"]
    return await _do_lookup(None, p["id"], p["label"], lon, lat)


def _l93_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:2154 (Lambert-93, GRS80) -> (lon, lat). Exact inverse LCC — BDNB's
    rel_batiment_groupe_adresse ships its address points in Lambert-93 and
    pulling in pyproj for one projection is not worth the dependency."""
    a, f = 6378137.0, 1 / 298.257222101
    e = math.sqrt(2 * f - f * f)
    lat0, lat1, lat2 = math.radians(46.5), math.radians(44.0), math.radians(49.0)
    lon0, x0, y0 = math.radians(3.0), 700000.0, 6600000.0

    def _m(phi):
        return math.cos(phi) / math.sqrt(1 - (e * math.sin(phi)) ** 2)

    def _t(phi):
        return (math.tan(math.pi / 4 - phi / 2)
                / ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))

    n = (math.log(_m(lat1)) - math.log(_m(lat2))) / (math.log(_t(lat1)) - math.log(_t(lat2)))
    F = _m(lat1) / (n * _t(lat1) ** n)
    rho0 = a * F * _t(lat0) ** n
    dx, dy = x - x0, rho0 - (y - y0)
    rho = math.copysign(math.hypot(dx, dy), n)
    t = (rho / (a * F)) ** (1 / n)
    lam = math.atan2(dx, dy) / n + lon0
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(6):
        phi = math.pi / 2 - 2 * math.atan(
            t * ((1 - e * math.sin(phi)) / (1 + e * math.sin(phi))) ** (e / 2))
    return math.degrees(lam), math.degrees(phi)


FISCALITE_URL = ("https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/"
                 "fiscalite-locale-des-particuliers-geo/records")
SCHOOLS_URL = ("https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
               "fr-en-annuaire-education/records")


async def _local_taxes(commune_insee):
    """Local recurring taxes (#193): DGFiP fiscalité directe locale — the
    buyer's other cost sheet next to the DPE €/an. Latest exercice; global
    rates (commune + interco + syndicats). None on any miss."""
    if not commune_insee:
        return None
    try:
        d = await _cached_get_json(FISCALITE_URL, {
            "where": f'insee_com="{commune_insee}"',
            "order_by": "exercice desc", "limit": "1"}, ttl=7 * 86400)
        r = (d.get("results") or [{}])[0]
        if not r.get("taux_global_tfb"):
            return None
        return {
            "year": r.get("exercice"),
            "property_tax_built_pct": r.get("taux_global_tfb"),
            "property_tax_unbuilt_pct": r.get("taux_global_tfnb"),
            "waste_tax_pct": r.get("taux_plein_teom"),
            "intercommunalite": r.get("q03"),
        }
    except Exception as e:
        log.warning("local taxes failed for %s: %s", commune_insee, e)
        return None


async def _nearby_schools(lon, lat, radius_km: float = 2.0):
    """Nearest schools (#194) from the annuaire de l'éducation. Honest caveat
    carried in the UI: proximity is NOT the carte scolaire assignment."""
    if lon is None or lat is None:
        return None
    try:
        d = await _cached_get_json(SCHOOLS_URL, {
            "where": f"within_distance(position, geom'POINT({lon} {lat})', {radius_km}km)",
            "select": "nom_etablissement,type_etablissement,statut_public_prive,position",
            "limit": "40"}, ttl=86400)
        rows = d.get("results") or []
        out = []
        for r in rows:
            pos = r.get("position") or {}
            if pos.get("lon") is None:
                continue
            out.append({
                "name": r.get("nom_etablissement"),
                "type": r.get("type_etablissement"),
                "statut": r.get("statut_public_prive"),
                "distance_m": round(_haversine_m(lon, lat, pos["lon"], pos["lat"])),
            })
        if not out:
            return {"within_2km": 0, "nearest": []}
        out.sort(key=lambda s: s["distance_m"])
        return {"within_2km": len(out), "nearest": out[:5]}
    except Exception as e:
        log.warning("schools failed for %s,%s: %s", lon, lat, e)
        return None


async def _noop():
    return None


async def _official_dpe(bdnb_id: str):
    """Official-DPE block (#189): BDNB's representative dwelling gives the real
    ADEME DPE number, surface and final energy; the ADEME observatoire adds the
    official document's substance — annual energy costs in €, insulation
    quality per envelope element, heating/ECS system descriptions. Honest
    framing: this describes the group's REPRESENTATIVE dwelling, not every
    unit. None on any miss; never breaks a building record."""
    try:
        rep = await _cached_get_json(
            BDNB_REP_DPE_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "1"},
            ttl=86400)
        if not isinstance(rep, list) or not rep:
            return None
        r = rep[0]
        num = r.get("identifiant_dpe")
        established = (r.get("date_etablissement_dpe") or "")[:10] or None
        block = {
            "dpe_number": num,
            "established_on": established,
            # Legal validity: 10 years (art. L126-26 CCH).
            "valid_until": (str(int(established[:4]) + 10) + established[4:])
            if established else None,
            "surface_habitable_m2": r.get("surface_habitable_logement")
            or r.get("surface_habitable_immeuble"),
            "final_energy_kwh_m2y": r.get("conso_5_usages_ef_m2"),
        }
        if num:
            adm = await _cached_get_json(
                ADEME_DPE_URL,
                {"qs": f'numero_dpe:"{num}"', "size": "1", "select": ADEME_DPE_SELECT},
                ttl=7 * 86400)
            res = (adm.get("results") or [{}])[0]
            if res:
                block.update({
                    "annual_cost_eur": res.get("cout_total_5_usages"),
                    "cost_breakdown_eur": {
                        "chauffage": res.get("cout_chauffage"),
                        "eau_chaude": res.get("cout_ecs"),
                        "eclairage": res.get("cout_eclairage"),
                        "auxiliaires": res.get("cout_auxiliaires"),
                        "refroidissement": res.get("cout_refroidissement"),
                    },
                    "insulation": {
                        "enveloppe": res.get("qualite_isolation_enveloppe"),
                        "menuiseries": res.get("qualite_isolation_menuiseries"),
                        "plancher_bas": res.get("qualite_isolation_plancher_bas"),
                        "plancher_haut": res.get("qualite_isolation_plancher_haut_comble_perdu"),
                    },
                    "heating": res.get("description_installation_chauffage_n1"),
                    "hot_water": res.get("description_installation_ecs_n1"),
                    "energies": [e for e in (res.get("type_energie_n1"),
                                             res.get("type_energie_n2")) if e],
                })
        return block
    except Exception as e:
        log.warning("official DPE failed for %s: %s", bdnb_id, e)
        return None


async def _water_network(commune_insee):
    """Commune drinking-water service block (#171): SISPEA network efficiency
    (P104.3 — rendement; 70% means 30% of treated water leaks before the tap)
    and water price (D102.0, €/m³ for 120 m³). Small communes report sporadic
    years: pick the LATEST year carrying the indicator and label it. None on
    any miss so a SISPEA hiccup never breaks a building record."""
    if not commune_insee:
        return None
    try:
        data = await _cached_get_json(
            SISPEA_URL, {"code_commune": commune_insee, "type_service": "AEP"},
            ttl=7 * 86400)
        rows = [r for r in (data.get("data") or [])
                if (r.get("indicateurs") or {}).get("P104.3") is not None]
        if not rows:
            return None
        r = max(rows, key=lambda r: r.get("annee") or 0)
        ind = r["indicateurs"]
        eff = round(float(ind["P104.3"]), 1)
        price = ind.get("D102.0")
        return {
            "efficiency_pct": eff,
            "losses_pct": round(100 - eff, 1),
            "year": r.get("annee"),
            "price_eur_m3": round(float(price), 2) if price is not None else None,
            "commune": r.get("nom_commune"),
            "commune_insee": commune_insee,
        }
    except Exception as e:
        log.warning("SISPEA failed for %s: %s", commune_insee, e)
        return None


async def _click_address(bdnb_id: str, lon, lat):
    """Address at the clicked point (#152), honest two-step:
    1. BAN-reverse the click; keep it ONLY if that address belongs to the
       clicked group (rel_batiment_groupe_adresse) — a group can span several
       streets and the principal address then reads as the wrong building.
    2. Else: the group's OWN address nearest to the click (<150 m) — BDNB
       sometimes attaches a 'principal' label that is not even in the group's
       address list (observed: principal Marronniers, members all Châtaigniers).
    None on any miss/failure -> caller falls back to the principal address."""
    if lon is None or lat is None:
        return None
    try:
        rel = await _cached_get_json(
            BDNB_REL_ADR_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "200"},
            ttl=86400)
        rows = rel if isinstance(rel, list) else []
        members = {r.get("cle_interop_adr") for r in rows}
        geo = await _cached_get_json(
            BAN_REVERSE_URL, {"lon": lon, "lat": lat, "type": "housenumber"}, ttl=86400)
        feats = geo.get("features", [])
        if feats:
            p = feats[0]["properties"]
            if p.get("id") in members:
                return p.get("label")
            # BDNB's relation can be plain wrong (observed: every member point
            # 200+ m from the footprint) while BAN's reverse sits ON the
            # building — trust the ground truth when it is that close.
            if (p.get("distance") or 9999) <= 30:
                return p.get("label")
        best, best_d = None, 150.0  # never label with an address >150 m away
        for r in rows:
            coords = ((r.get("geom_adresse") or {}).get("coordinates"))
            if not coords or not r.get("libelle_adresse"):
                continue
            alon, alat = _l93_to_wgs84(coords[0], coords[1])
            d = _haversine_m(lon, lat, alon, alat)
            if d < best_d:
                best, best_d = r["libelle_adresse"], d
        return best
    except Exception as e:
        log.warning("click-address failed for %s: %s", bdnb_id, e)
    return None


@app.get("/v1/buildings/{bdnb_id}", tags=["buildings"])
async def building(
    bdnb_id: str,
    lon: float | None = Query(None, description="Longitude (adds the Géorisques area report)"),
    lat: float | None = Query(None, description="Latitude (idem)"),
    request: Request = None,   # None when called internally by the report route
):
    """Full record of one building by its BDNB id (e.g. from a map click)."""
    if request is not None:
        _meter_if_keyed(request, "buildings")
    rows = await _cached_get_json(
        BDNB_BASE_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "1"}, ttl=86400
    )
    if not isinstance(rows, list) or not rows:
        raise HTTPException(404, "Unknown building id")
    row = rows[0]
    M_LOOKUPS.add(1, {"status": "by_id"})
    (prices, risks, groundwater, solar_pv, click_addr, water_network,
     official_dpe, local_taxes, schools) = await asyncio.gather(
        _dvf_prices(bdnb_id), _area_risks(lon, lat),
        _groundwater(lon, lat), _solar_pv(lon, lat),
        _click_address(bdnb_id, lon, lat),
        _water_network(row.get("code_commune_insee")),
        _official_dpe(bdnb_id),
        _local_taxes(row.get("code_commune_insee")),
        _nearby_schools(lon, lat))
    sources = ["BDNB (CSTB) — Licence Ouverte v2.0", "Géorisques — Licence Ouverte"]
    if prices:
        sources.append("DVF (DGFiP) / Etalab — Licence Ouverte")
    if groundwater:
        sources.append("Hub'Eau piézométrie (ADES/BRGM) — Licence Ouverte")
    if solar_pv:
        sources.append("PVGIS (JRC) — © Union européenne")
    if water_network:
        sources.append("SISPEA / OFB (services d'eau) — Licence Ouverte")
    if official_dpe and official_dpe.get("dpe_number"):
        sources.append("ADEME — Observatoire DPE — Licence Ouverte")
    if local_taxes:
        sources.append("DGFiP — Fiscalité directe locale — Licence Ouverte")
    if schools:
        sources.append("Annuaire de l'éducation (MENJ) — Licence Ouverte")
    return {
        # Prefer the group-member address at the clicked point (#152); the
        # principal address stays on buildings[0].address for the UI's row.
        "query": {"bdnb_id": bdnb_id,
                  "address": click_addr or row.get("libelle_adr_principale_ban"),
                  "lon": lon, "lat": lat},
        "buildings": [_normalize_building(row)],
        "area_risks": risks,
        "groundwater": groundwater,
        "solar_pv": solar_pv,
        "water_network": water_network,
        "official_dpe": official_dpe,
        "local_taxes": local_taxes,
        "schools": schools,
        "prices": prices,
        "sources": sources,
    }


# --- Identity (Keycloak, shared /auth) ---------------------------------------
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "https://ecobuilding.confinia.io/auth/realms/confinia")
# JWKS fetched via the host-internal route (api runs in a stack network).
OIDC_JWKS_URL = os.environ.get(
    "OIDC_JWKS_URL",
    "https://ecobuilding.confinia.io/auth/realms/confinia/protocol/openid-connect/certs",
)
_jwks_client = None


def _get_signing_key(token: str):
    """Resolve the RS256 signing key for a token (separated for tests)."""
    global _jwks_client
    import jwt as pyjwt

    if _jwks_client is None:
        _jwks_client = pyjwt.PyJWKClient(OIDC_JWKS_URL, cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(token).key


def _decode_token(token: str) -> dict:
    import jwt as pyjwt

    key = _get_signing_key(token)
    return pyjwt.decode(
        token, key, algorithms=["RS256"], issuer=OIDC_ISSUER,
        options={"verify_aud": False},
    )


@app.get("/v1/me", tags=["account"])
async def me(request: Request):
    """Identity of the signed-in user (Keycloak JWT). Tier is 'free' until
    the Polar pro plan ships (#35)."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    return {
        "sub": claims.get("sub"),
        "email": claims.get("email") or claims.get("preferred_username"),
        "organization": claims.get("org"),
        "tier": "pro" if _pro_active(claims.get("sub")) else "free",
    }


M_REPORTS = _meter.create_counter("ecobuilding_reports", description="PDF fiches generated", unit="1")

# --- API keys & soft quota (issue #27) ---------------------------------------
# Keys are minted by signed-in users (bound to their org) and stored on the
# shared data volume. The daily cap applies ONLY to value endpoints (report,
# export) so the free map (suggest/lookup/buildings) stays unlimited. During
# beta a valid key lifts the cap entirely. The per-IP counter is in-memory
# (soft, resets on restart / differs per stack) — a nudge, not hard billing.
import hashlib
import secrets as _secrets
from collections import defaultdict
from datetime import date

KEYS_PATH = os.environ.get("KEYS_PATH", "/leads/keys.jsonl")
ANON_DAILY_CAP = int(os.environ.get("ANON_DAILY_CAP", "20"))
_anon_counts: dict = defaultdict(int)
_anon_day = {"d": None}
M_KEYS = _meter.create_counter("ecobuilding_api_keys", description="API key events", unit="1")
M_KEYED_CALLS = _meter.create_counter("ecobuilding_keyed_calls", description="Value calls per key", unit="1")
M_CREDITS = _meter.create_counter("ecobuilding_credits", description="Billable credits consumed", unit="1")


def _key_owners() -> dict:
    """key -> Keycloak sub. Keys are minted for a signed-in user, so a
    subscription attaches to the ACCOUNT and every key of that account
    inherits it — nothing to sync when a user rotates a key (#206)."""
    owners = {}
    try:
        with open(KEYS_PATH) as f:
            import json as _json
            for line in f:
                rec = _json.loads(line)
                owners[rec["key"]] = rec.get("sub") or ""
    except (OSError, ValueError):
        pass
    return owners


def _key_plans() -> dict:
    """key -> plan ("free" | "pro"), resolved from the LIVE subscription state
    (pro.json, written by the Polar webhook)."""
    return {k: ("pro" if _pro_active(sub) else "free")
            for k, sub in _key_owners().items()}


def _bearer_sub(request: Request) -> str | None:
    """Keycloak sub of the signed-in caller, if the request carries a valid
    Bearer token. Lets the WEB APP consume the same tiers as API keys: a
    registered user gets the free-account allowance straight from the browser."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    try:
        return _decode_token(auth[7:].strip()).get("sub")
    except Exception:
        return None


def _load_keys() -> set:
    keys = set()
    try:
        with open(KEYS_PATH) as f:
            import json as _json
            for line in f:
                keys.add(_json.loads(line)["key"])
    except OSError:
        pass
    return keys


# --- Pay-as-you-go metering (#201) -------------------------------------------
# The PDF fiche is the sellable deliverable, so it is billed FROM THE FIRST
# ONE (0,20 €): a free monthly allowance on fiches would just give the product
# away (operator decision 2026-08-16, BUSINESS.md). Raw API calls are 20x
# cheaper (0,01 €) because they are an input, not a deliverable. A HARD monthly
# cap keeps the worst case knowable — the selling point for cost-controlled
# companies. Anonymous browsing (no key) stays free and uncapped.
# Pricing v3 (#224) — the billed unit is the FICHE, not an internal credit:
# the Polar checkout showed « credits €0.01/unit », which read as if a PDF cost
# one cent. Raw API calls are no longer billed at all (they only added noise).
#   sans compte  : 3 fiches/mois
#   compte gratuit: 10 fiches/mois
#   pro          : 10 fiches offertes, puis 0,49 EUR la fiche, plafond 99 EUR
PRICE_PER_FICHE_EUR = float(os.environ.get("PRICE_PER_FICHE_EUR", "0.49"))
MONTHLY_CAP_EUR = float(os.environ.get("MONTHLY_CAP_EUR", "99"))
ANON_MONTHLY_REPORTS = int(os.environ.get("ANON_MONTHLY_REPORTS", "3"))
FREE_ACCOUNT_REPORTS = int(os.environ.get("FREE_ACCOUNT_REPORTS", "10"))
INCLUDED_FICHES = int(os.environ.get("INCLUDED_FICHES", "10"))
# Self-service means: never leave a user stuck without a way out (#212).
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "contact@confinia.io")
# One unit = one fiche. Everything else is free, so the customer's invoice
# has exactly one line and needs no explanation.
CREDIT_COST = {"lookup": 0, "buildings": 0, "reverse": 0, "report": 1, "suggest": 0}
USAGE_PATH = os.environ.get("USAGE_PATH", "/leads/usage.json")


def _month_key() -> str:
    return date.today().strftime("%Y-%m")


def _usage_load() -> dict:
    import json as _json
    try:
        with open(USAGE_PATH) as f:
            return _json.load(f)
    except (OSError, ValueError):
        return {}


def _usage_add(key_id: str, credits: int) -> int:
    """Add credits to this month's counter; returns the new monthly total.
    Stored on the shared /leads volume so both blue/green stacks and promotes
    keep one truth per customer."""
    import json as _json
    if not key_id or credits <= 0:
        return 0
    store = _usage_load()
    month = _month_key()
    bucket = store.setdefault(month, {})
    bucket[key_id] = bucket.get(key_id, 0) + credits
    # Keep the current + previous month only (invoice window), tiny file.
    for old in [m for m in store if m < month][:-1]:
        store.pop(old, None)
    try:
        os.makedirs(os.path.dirname(USAGE_PATH), exist_ok=True)
        tmp = USAGE_PATH + ".tmp"
        with open(tmp, "w") as f:
            _json.dump(store, f)
        os.replace(tmp, USAGE_PATH)
    except OSError as e:
        log.warning("usage not persisted: %s", e)
    return bucket[key_id]


def _usage_cost(fiches: int) -> dict:
    """Monthly cost in FICHES: the first INCLUDED_FICHES are free, the rest
    cost PRICE_PER_FICHE_EUR each, and the total never exceeds the cap."""
    billable = max(0, fiches - INCLUDED_FICHES)
    raw = round(billable * PRICE_PER_FICHE_EUR, 2)
    capped = min(raw, MONTHLY_CAP_EUR)
    return {
        "fiches": fiches,
        "credits": fiches,                  # kept: same number, one unit
        "included_fiches": INCLUDED_FICHES,
        "billable_fiches": billable,
        "billable_credits": billable,
        "price_per_fiche_eur": PRICE_PER_FICHE_EUR,
        "cost_eur": capped,
        "monthly_cap_eur": MONTHLY_CAP_EUR,
        "cap_reached": raw >= MONTHLY_CAP_EUR,
        "saved_vs_cap_eur": round(MONTHLY_CAP_EUR - capped, 2),
        "free_tiers": {"anonymous_reports_month": ANON_MONTHLY_REPORTS,
                       "free_account_reports_month": FREE_ACCOUNT_REPORTS},
    }


async def _polar_ingest(key_id: str, endpoint: str, credits: int):
    """Report usage to Polar for metered billing (#201). Fire-and-forget: a
    billing-provider hiccup must never fail a customer's API call — the local
    counter stays the source of truth and can be replayed."""
    if not (POLAR_ACCESS_TOKEN and credits > 0):
        return
    try:
        await _client.post(
            f"{POLAR_BASE_URL}/v1/events/ingest",
            headers={"Authorization": f"Bearer {POLAR_ACCESS_TOKEN}"},
            json={"events": [{
                "name": POLAR_METER_EVENT,
                "external_customer_id": key_id,
                # One event = one fiche, so the customer's invoice line reads
                # "fiches PDF x N" instead of an internal credit count (#224).
                "metadata": {"fiches": credits, "endpoint": endpoint},
            }]})
    except Exception as e:
        log.warning("Polar ingest failed (%s credits, %s): %s", credits, endpoint, e)


def _meter_call(request: Request, endpoint: str, key: str):
    """Count the credits of one keyed call and report them to Polar."""
    credits = CREDIT_COST.get(endpoint, 1)
    if credits <= 0:
        return
    key_id = hashlib.sha256(key.encode()).hexdigest()[:16]
    _usage_add(key_id, credits)
    M_CREDITS.add(credits, {"endpoint": endpoint})
    try:
        asyncio.get_running_loop().create_task(_polar_ingest(key_id, endpoint, credits))
    except RuntimeError:  # no loop (unit tests): local counter already updated
        pass


def _meter_if_keyed(request: Request, endpoint: str):
    """Meter a keyed call WITHOUT applying the anonymous cap: the browse
    endpoints stay free for anonymous visitors (launch traffic must never be
    429-ed); only key holders consume credits."""
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    if key and key in _load_keys():
        _meter_call(request, endpoint, key)


def _reports_this_month(bucket_id: str) -> int:
    """Fiches already generated this month by an IP or a key (#206)."""
    used = (_usage_load().get(_month_key()) or {}).get(bucket_id, 0)
    return used // CREDIT_COST["report"] if bucket_id.startswith("ip:") else used


def _quota_gate(request: Request, endpoint: str):
    """Tiered access (#206), subscription-first ladder:
      anonymous      -> ANON_MONTHLY_REPORTS fiches/month per IP
      free account   -> FREE_ACCOUNT_REPORTS fiches/month (API key)
      pro subscriber -> metered, hard-capped, never blocked
    Returns the caller kind for metrics."""
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    if key and key in _load_keys():
        plan = _key_plans().get(key, "free")
        M_KEYED_CALLS.add(1, {"endpoint": endpoint, "plan": plan,
                              "key": hashlib.sha256(key.encode()).hexdigest()[:12]})
        if plan != "pro" and endpoint == "report":
            key_id = hashlib.sha256(key.encode()).hexdigest()[:16]
            used = (_usage_load().get(_month_key()) or {}).get(key_id, 0) // CREDIT_COST["report"]
            if used >= FREE_ACCOUNT_REPORTS:
                raise HTTPException(
                    429,
                    f"Compte gratuit : {FREE_ACCOUNT_REPORTS} fiches par mois atteintes. "
                    f"L'offre Pro (paiement à l'usage : {INCLUDED_FICHES} fiches offertes, "
                    f"puis {PRICE_PER_FICHE_EUR:.2f} € la fiche, plafond {MONTHLY_CAP_EUR:.0f} €/mois) : "
                    f"https://ecobuilding.confinia.io/offres.html — une question ? {SUPPORT_EMAIL}")
        _meter_call(request, endpoint, key)
        return "key"
    sub = _bearer_sub(request)
    if sub:
        # Signed-in browser user: same ladder as a key holder, no key needed.
        uid = "kc:" + hashlib.sha256(sub.encode()).hexdigest()[:14]
        if _pro_active(sub):
            if endpoint == "report":
                _usage_add(uid, CREDIT_COST["report"])
                M_CREDITS.add(CREDIT_COST["report"], {"endpoint": endpoint, "plan": "pro"})
                try:
                    asyncio.get_running_loop().create_task(
                        _polar_ingest(uid, endpoint, CREDIT_COST["report"]))
                except RuntimeError:
                    pass
            return "user_pro"
        if endpoint == "report":
            used = (_usage_load().get(_month_key()) or {}).get(uid, 0) // CREDIT_COST["report"]
            if used >= FREE_ACCOUNT_REPORTS:
                raise HTTPException(
                    429,
                    f"Compte gratuit : {FREE_ACCOUNT_REPORTS} fiches par mois atteintes. "
                    f"L'offre Pro (paiement à l'usage : {INCLUDED_FICHES} fiches offertes, "
                    f"puis {PRICE_PER_FICHE_EUR:.2f} € la fiche, plafond {MONTHLY_CAP_EUR:.0f} €/mois) : "
                    f"https://ecobuilding.confinia.io/offres.html — une question ? {SUPPORT_EMAIL}")
            _usage_add(uid, CREDIT_COST["report"])
        return "user_free"
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "?"
    if endpoint == "report":
        # Monthly, not daily: a daily cap of 20 was never reached, so nobody
        # ever created an account (#206).
        bucket = "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]
        used = _usage_add(bucket, CREDIT_COST["report"]) // CREDIT_COST["report"]
        if used > ANON_MONTHLY_REPORTS:
            raise HTTPException(
                429,
                f"Limite gratuite atteinte ({ANON_MONTHLY_REPORTS} fiches par mois sans compte). "
                f"Créez un compte gratuit (30 secondes) pour {FREE_ACCOUNT_REPORTS} fiches par mois : "
                f"https://ecobuilding.confinia.io/?signup=1 — une question ? {SUPPORT_EMAIL}")
    return "anon"


from fastapi.responses import HTMLResponse


@app.exception_handler(HTTPException)
async def _http_exc_handler(request: Request, exc: HTTPException):
    """Render the free-limit (429) as a friendly HTML page for browser
    navigations (e.g. a PDF link), keep JSON for API clients."""
    from fastapi.exception_handlers import http_exception_handler

    if exc.status_code == 429 and "text/html" in request.headers.get("accept", ""):
        # Self-service (#212): the page must say what happened, what to do
        # next in ONE click, and how to reach a human if it goes wrong.
        return HTMLResponse(status_code=429, content=f"""<!DOCTYPE html><html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Limite gratuite atteinte — EcoBuilding</title>
<link rel="icon" href="/assets/logo.svg" type="image/svg+xml">
<style>body{{font-family:system-ui,sans-serif;max-width:560px;margin:10vh auto;padding:0 20px;color:#222;text-align:center}}
h1{{font-size:22px}}.c{{background:#fdecea;color:#b3261e;border-radius:10px;padding:14px;margin:18px 0}}
ul{{text-align:left;display:inline-block;color:#444;line-height:1.7}}
a.btn{{display:inline-block;margin:6px;padding:11px 18px;border-radius:8px;text-decoration:none;font-weight:600}}
.p{{background:#2b7a4b;color:#fff}}.s{{border:1px solid #2b7a4b;color:#2b7a4b}}
.help{{margin-top:26px;font-size:14px;color:#666}}</style></head><body>
<h1>🏢 Limite gratuite atteinte</h1>
<div class="c">{exc.detail}</div>
<p><strong>Créez un compte gratuit</strong> (30 secondes, sans carte bancaire) :</p>
<ul>
  <li>{FREE_ACCOUNT_REPORTS} fiches PDF par mois au lieu de {ANON_MONTHLY_REPORTS}</li>
  <li>Une clé API pour vos propres outils</li>
  <li>Le suivi de votre consommation en temps réel</li>
</ul>
<p><a class="btn p" href="https://ecobuilding.confinia.io/?signup=1">Créer un compte gratuit</a>
<a class="btn s" href="https://ecobuilding.confinia.io/offres.html">Voir les offres</a></p>
<p class="help">Un problème, une question ? Écrivez à
<a href="mailto:{SUPPORT_EMAIL}?subject=EcoBuilding%20-%20aide">{SUPPORT_EMAIL}</a>, on répond.</p>
</body></html>""")
    return await http_exception_handler(request, exc)


@app.get("/v1/keys", tags=["account"])
async def list_keys(request: Request):
    """The caller's own API keys, MASKED (#220). A key value is shown exactly
    once, at creation: this listing exists so the user can see what they have
    and when it was created, not to recover a lost secret."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    sub = claims.get("sub")
    import json as _json
    out = []
    try:
        with open(KEYS_PATH) as f:
            for line in f:
                rec = _json.loads(line)
                if rec.get("sub") and rec["sub"] == sub:
                    k = rec["key"]
                    out.append({"masked": k[:7] + "…" + k[-4:],
                                "created": rec.get("created"),
                                "plan": "pro" if _pro_active(sub) else "free"})
    except (OSError, ValueError):
        pass
    return {"keys": out, "count": len(out)}


@app.post("/v1/keys", tags=["account"], status_code=201)
async def create_key(request: Request):
    """Mint an API key for the signed-in user (Keycloak JWT). Free during beta."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    key = "eco_" + _secrets.token_urlsafe(24)
    import json as _json
    from datetime import datetime, timezone

    rec = {"key": key, "sub": claims.get("sub"),
           "org": claims.get("org"), "email": claims.get("email"),
           "created": datetime.now(timezone.utc).isoformat()}
    os.makedirs(os.path.dirname(KEYS_PATH), exist_ok=True)
    with open(KEYS_PATH, "a") as f:
        f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    M_KEYS.add(1, {"event": "created"})
    return {"api_key": key, "note": "Passez-la en en-tête X-API-Key."}


@app.get("/v1/usage", tags=["account"])
async def usage(request: Request):
    """Current-month usage and cost for the calling API key (#201).

    Pay-as-you-go from the first fiche, with a hard monthly cap — a client can
    always answer "what is my worst case?". 20 credits (0,20 €) per PDF fiche,
    1 credit (0,01 €) per API record, autocomplete free.
    """
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    sub = _bearer_sub(request)
    if key and key in _load_keys():
        bucket = hashlib.sha256(key.encode()).hexdigest()[:16]
        plan = _key_plans().get(key, "free")
    elif sub:
        bucket = "kc:" + hashlib.sha256(sub.encode()).hexdigest()[:14]
        plan = "pro" if _pro_active(sub) else "free"
    else:
        raise HTTPException(401, "Clé API (X-API-Key) ou session requise")
    month = _month_key()
    credits = (_usage_load().get(month) or {}).get(bucket, 0)
    body = {"month": month, "plan": plan, "credit_costs": CREDIT_COST,
            **_usage_cost(credits)}
    if plan != "pro":
        # A free account owes nothing: show the allowance, not a bill.
        used = credits // CREDIT_COST["report"]
        body |= {"cost_eur": 0.0, "reports_used": used,
                 "reports_included": FREE_ACCOUNT_REPORTS,
                 "reports_left": max(0, FREE_ACCOUNT_REPORTS - used)}
    return body


@app.get("/v1/config", tags=["meta"])
async def config():
    """Public runtime facts the UI must not guess (#221): which payment
    environment is wired. A SANDBOX payment mode must be visible in the UI so
    nobody mistakes a test checkout for a real one."""
    if not POLAR_ACCESS_TOKEN:
        mode = "disabled"
    elif "sandbox" in POLAR_BASE_URL:
        mode = "sandbox"
    else:
        mode = "live"
    return {"payment_mode": mode,
            "free_tiers": {"anonymous_reports_month": ANON_MONTHLY_REPORTS,
                           "free_account_reports_month": FREE_ACCOUNT_REPORTS},
            "support_email": SUPPORT_EMAIL}


@app.get("/v1/pricing", tags=["account"])
async def pricing(credits: int = Query(0, ge=0, le=10_000_000,
                                       description="Simulate this monthly volume")):
    """Public price simulator (#201): what a given monthly volume costs."""
    return {"credit_costs": CREDIT_COST, **_usage_cost(credits)}


# --- Pro plan via Polar (Merchant of Record) — issue #35 / sandbox #90 --------
# Self-serve upgrade: a signed-in user starts a Polar checkout; on payment Polar
# sends a signed webhook (Standard Webhooks) that flips the user to the pro tier.
# All money flows through Polar (EU VAT handled). Runs against the Polar SANDBOX
# during beta (POLAR_BASE_URL=https://sandbox-api.polar.sh); no real money until
# RULES.md #7 is met. Tier is stored on the shared /leads volume, like keys.
POLAR_BASE_URL = os.environ.get("POLAR_BASE_URL", "https://api.polar.sh").rstrip("/")
POLAR_ACCESS_TOKEN = os.environ.get("POLAR_ACCESS_TOKEN", "")
POLAR_PRODUCT_ID = os.environ.get("POLAR_PRODUCT_ID", "")
POLAR_WEBHOOK_SECRET = os.environ.get("POLAR_WEBHOOK_SECRET", "")
# Usage-based billing (#201): the meter/event name configured on the Polar
# product; each keyed call ingests one event carrying its credit count.
POLAR_METER_EVENT = os.environ.get("POLAR_METER_EVENT", "ecobuilding_fiche")
PUBLIC_BASE_URL = (os.environ.get("PUBLIC_BASE_URL")
                   or OIDC_ISSUER.split("/auth/")[0]).rstrip("/")
PRO_PATH = os.environ.get("PRO_PATH", "/leads/pro.json")
M_PRO = _meter.create_counter("ecobuilding_pro_events", description="Pro plan events", unit="1")


def _pro_load() -> dict:
    import json as _json
    try:
        with open(PRO_PATH) as f:
            return _json.load(f)
    except (OSError, ValueError):
        return {}


def _pro_set(ext_id: str, active: bool, **extra):
    """Upsert a user's pro status, keyed by their Keycloak sub (external_id)."""
    import json as _json
    from datetime import datetime, timezone
    if not ext_id:
        return
    store = _pro_load()
    rec = store.get(ext_id, {})
    rec.update(status="active" if active else "inactive",
               updated=datetime.now(timezone.utc).isoformat(), **extra)
    store[ext_id] = rec
    os.makedirs(os.path.dirname(PRO_PATH), exist_ok=True)
    tmp = PRO_PATH + ".tmp"
    with open(tmp, "w") as f:
        _json.dump(store, f, ensure_ascii=False)
    os.replace(tmp, PRO_PATH)


# Reconciliation cache: {ext_id: (checked_at, active)}. Polar is the source of
# truth for money; pro.json is our fast local copy.
_pro_check: dict = {}
PRO_RECHECK_TTL = float(os.environ.get("PRO_RECHECK_TTL", "60"))


def _polar_subscription_active(ext_id: str) -> bool:
    """Ask Polar whether this account has an ACTIVE subscription (#228).

    The webhook is an optimisation, not a dependency: declaring it needs a
    token scope we do not have, and webhooks can be missed anyway. A short
    cache keeps this to at most one upstream call per user per minute, and any
    failure answers False so a Polar hiccup never grants nor breaks access."""
    if not (POLAR_ACCESS_TOKEN and ext_id):
        return False
    now = time.monotonic()
    hit = _pro_check.get(ext_id)
    if hit and now - hit[0] < PRO_RECHECK_TTL:
        return hit[1]
    active = False
    try:
        with httpx.Client(timeout=6.0) as c:
            r = c.get(f"{POLAR_BASE_URL}/v1/subscriptions/",
                      params={"external_customer_id": ext_id, "active": "true", "limit": 1},
                      headers={"Authorization": f"Bearer {POLAR_ACCESS_TOKEN}"})
            r.raise_for_status()
            active = bool((r.json().get("items") or []))
    except Exception as e:
        log.warning("Polar subscription check failed for %s: %s", ext_id, e)
    _pro_check[ext_id] = (now, active)
    if active:
        _pro_set(ext_id, True, source="reconciled")
    return active


def _pro_active(ext_id: str | None) -> bool:
    if not ext_id:
        return False
    if _pro_load().get(ext_id, {}).get("status") == "active":
        return True
    # Not active locally: reconcile with Polar (webhook may never have come).
    return _polar_subscription_active(ext_id)


def _sub_external_id(data: dict) -> str | None:
    """Extract our Keycloak sub from a Polar subscription/order payload."""
    cust = data.get("customer") or {}
    return (cust.get("external_id")
            or data.get("customer_external_id")
            or (data.get("metadata") or {}).get("kc_sub"))


@app.get("/v1/pro/checkout", tags=["account"])
async def pro_checkout(request: Request):
    """Start a Polar checkout for the pro plan (signed-in users). Returns the
    Polar-hosted checkout URL as JSON (the frontend redirects to it); the user's
    Keycloak sub travels as the customer external_id so the webhook can upgrade
    the right account."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    if not (POLAR_ACCESS_TOKEN and POLAR_PRODUCT_ID):
        raise HTTPException(503, "Pro plan not configured")
    payload = {
        "products": [POLAR_PRODUCT_ID],
        "success_url": f"{PUBLIC_BASE_URL}/?pro=success",
        "customer_email": claims.get("email") or claims.get("preferred_username"),
        "customer_external_id": claims.get("sub"),
        # Polar rejects EMPTY metadata values (min_length 1), so only non-empty
        # entries are sent: a user without an `org` claim would otherwise get a
        # 422 on every checkout attempt.
        "metadata": {k: v for k, v in (("kc_sub", claims.get("sub")),
                                       ("org", claims.get("org"))) if v},
    }
    try:
        resp = await _client.post(
            f"{POLAR_BASE_URL}/v1/checkouts/", json=payload,
            headers={"Authorization": f"Bearer {POLAR_ACCESS_TOKEN}"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Polar checkout failed: %s", e)
        raise HTTPException(502, "Checkout provider error")
    M_PRO.add(1, {"event": "checkout"})
    body = resp.json()
    return {"url": body["url"], "checkout_id": body.get("id")}


@app.post("/v1/pro/webhook", tags=["account"], status_code=202)
async def pro_webhook(request: Request):
    """Polar webhook (Standard Webhooks, signed). Verifies the signature, then
    flips the subscriber's tier: active -> pro, canceled/revoked -> free."""
    if not POLAR_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook not configured")
    body = await request.body()
    try:
        from standardwebhooks import Webhook
        wh = Webhook(POLAR_WEBHOOK_SECRET)
        event = wh.verify(body, {
            "webhook-id": request.headers.get("webhook-id", ""),
            "webhook-timestamp": request.headers.get("webhook-timestamp", ""),
            "webhook-signature": request.headers.get("webhook-signature", ""),
        })
    except Exception:
        M_PRO.add(1, {"event": "webhook_rejected"})
        raise HTTPException(401, "Invalid signature")
    if isinstance(event, (bytes, str)):
        import json as _json
        event = _json.loads(event)
    etype = event.get("type", "")
    data = event.get("data", {}) or {}
    ext_id = _sub_external_id(data)
    if etype in ("subscription.created", "subscription.active", "subscription.updated"):
        active = (data.get("status") in ("active", "trialing")) or etype == "subscription.active"
        _pro_set(ext_id, active, subscription_id=data.get("id"), product_id=data.get("product_id"))
    elif etype in ("subscription.canceled", "subscription.revoked"):
        _pro_set(ext_id, False, subscription_id=data.get("id"))
    M_PRO.add(1, {"event": "webhook", "type": etype})
    return {"received": True, "type": etype}


@app.get("/v1/report/{bdnb_id}.pdf", tags=["reports"])
async def report(
    request: Request,
    bdnb_id: str,
    lon: float | None = Query(None),
    lat: float | None = Query(None),
    address: str | None = Query(None, max_length=250, description=(
        "The address the user actually searched. A BDNB 'bâtiment groupe' can "
        "span several streets: without this, the fiche titles with the group's "
        "principal address (#146), which reads as the wrong building.")),
):
    """Normalized one-page PDF fiche of a building (free during beta).

    Informational document for pre-sale/diagnostic preparation — replaces
    neither an official DPE nor a regulatory ERP. Anonymous daily cap applies;
    a free API key lifts it (issue #27).
    """
    from fastapi.responses import Response

    from .report import build_report_pdf

    _quota_gate(request, "report")
    data = await building(bdnb_id, lon, lat)
    q = data.get("query", {})
    if address:
        q["address"] = address  # title with the searched address (#146)
    # Self-resolve coordinates from the building's address if the caller did not
    # pass them, so the Panoramax context page works regardless of entry point.
    if q.get("lon") is None and (data.get("buildings") or [{}])[0].get("address"):
        try:
            geo = await _cached_get_json(
                BAN_URL, {"q": data["buildings"][0]["address"], "limit": 1}, ttl=86400)
            feats = geo.get("features", [])
            if feats:
                q["lon"], q["lat"] = feats[0]["geometry"]["coordinates"][:2]
        except httpx.HTTPError:
            pass
    photos = []
    if q.get("lon") is not None and q.get("lat") is not None:
        try:
            photos = await _nearby_photos(q["lon"], q["lat"])
        except httpx.HTTPError:
            pass
    map_img = await _building_map_png(q.get("lon"), q.get("lat"), bdnb_id)
    pdf = build_report_pdf(data, photos=photos, map_img=map_img)
    M_REPORTS.add(1, {"has_dpe": str(bool((data["buildings"][0].get("energy") or {}).get("dpe_class"))).lower()})
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="ecobuilding-{bdnb_id}.pdf"'},
    )


PANORAMAX_URL = "https://api.panoramax.xyz/api/search"


async def _nearby_photos(lon: float, lat: float, radius: float = 0.0006) -> list:
    """Nearest Panoramax photos around a point. Each item carries thumb, a
    full-size (sd) href for embedding, and a web-viewer deep link."""
    bbox = f"{lon - radius},{lat - radius},{lon + radius},{lat + radius}"
    data = await _cached_get_json(PANORAMAX_URL, {"bbox": bbox, "limit": "4"}, ttl=3600)
    photos = []
    for f in data.get("features", [])[:4]:
        assets = f.get("assets", {})
        thumb = (assets.get("thumb") or assets.get("sd") or {}).get("href")
        sd = (assets.get("sd") or assets.get("thumb") or {}).get("href")
        # Deep-link into the Panoramax web viewer (the STAC "self" link is raw
        # JSON, not a human page).
        viewer = f"https://api.panoramax.xyz/#focus=pic&pic={f['id']}"
        fov = (f.get("properties", {}).get("pers:interior_orientation") or {}).get("field_of_view")
        if thumb:
            photos.append({"id": f["id"], "thumb": thumb, "sd": sd, "viewer": viewer,
                           "is_360": fov == 360,
                           "date": (f.get("properties") or {}).get("datetime"),  # provenance (#93)
                           "coordinates": f.get("geometry", {}).get("coordinates")})
    return photos


@app.get("/v1/streetview", tags=["buildings"])
async def streetview(
    lon: float = Query(description="Longitude"),
    lat: float = Query(description="Latitude"),
    radius: float = Query(0.0006, description="Half-size of the search bbox in degrees"),
):
    """Nearest Panoramax street-level photos around a point (open imagery,
    CC-BY-SA). Bridges toward the photosphere vision — issue #22."""
    return {"photos": await _nearby_photos(lon, lat, radius), "source": "Panoramax — CC-BY-SA 4.0"}


@app.get("/v1/export", tags=["data"])
async def export_geojson(
    request: Request,
    commune: str = Query(description="INSEE commune code, e.g. 35238 (Rennes)"),
    limit: int = Query(2000, le=10000, description="Max features"),
):
    """GeoJSON of a commune's buildings (DPE, cooling, clay risk) for reuse
    (uMap, QGIS, data journalism). Attribution embedded. Open data, Licence
    Ouverte — issue #24."""
    from fastapi.responses import JSONResponse

    _quota_gate(request, "export")
    fields = ("batiment_groupe_id,libelle_adr_principale_ban,classe_bilan_dpe,"
              "annee_construction,hauteur_mean,alea_argile,"
              "type_generateur_climatisation,geom_groupe")
    rows = await _cached_get_json(
        BDNB_BASE_URL,
        {"code_commune_insee": f"eq.{commune}", "select": fields, "limit": str(limit)},
        ttl=86400,
    )
    if not isinstance(rows, list):
        raise HTTPException(502, "Upstream error")
    import json as _json

    from pyproj import Transformer

    # BDNB geometries are Lambert-93 (EPSG:2154); GeoJSON must be WGS84.
    to_wgs84 = Transformer.from_crs(2154, 4326, always_xy=True)

    def reproject(coords):
        if coords and isinstance(coords[0], (int, float)):
            lon, lat = to_wgs84.transform(coords[0], coords[1])
            return [round(lon, 6), round(lat, 6)]
        return [reproject(c) for c in coords]

    feats = []
    for r in rows:
        geom = r.get("geom_groupe")
        if not geom:
            continue
        try:
            g = _json.loads(geom) if isinstance(geom, str) else dict(geom)
            g = {"type": g["type"], "coordinates": reproject(g["coordinates"])}
        except (ValueError, TypeError, KeyError):
            continue
        feats.append({
            "type": "Feature", "geometry": g,
            "properties": {k: v for k, v in r.items() if k != "geom_groupe"},
        })
    return JSONResponse({
        "type": "FeatureCollection",
        "features": feats,
        "metadata": {"source": "BDNB (CSTB), Licence Ouverte", "commune": commune, "count": len(feats)},
    })


class Lead(BaseModel):
    email: str
    org: str | None = None
    need: str | None = None


M_LEADS = _meter.create_counter("ecobuilding_leads", description="Access requests / waitlist signups", unit="1")
LEADS_PATH = os.environ.get("LEADS_PATH", "/leads/leads.jsonl")


def _send_lead_email(rec: dict) -> bool:
    """Lead notification (#196): alert@ -> operator mailbox, using the SMTP
    creds provisioned by #128 (secrets.env via env_file). Returns False and
    only logs when creds are absent (CI/dev) or the relay fails — a lead is
    ALWAYS persisted first; mail is best-effort."""
    host, pwd = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_PASSWORD")
    if not host or not pwd:
        return False
    import smtplib
    import ssl
    from email.message import EmailMessage

    env_label = os.environ.get("OIDC_REALM", "confinia")
    m = EmailMessage()
    m["From"] = os.environ.get("SMTP_FROM", "alert@confinia.io")
    m["To"] = os.environ.get("ALERT_RCPT", "contact@confinia.io")
    m["Subject"] = f"[EcoBuilding{'/' + env_label if 'sandbox' in env_label else ''}] Nouveau lead: {rec.get('org') or rec.get('email')}"
    m.set_content(
        f"E-mail: {rec.get('email')}\nOrganisation: {rec.get('org') or '-'}\n"
        f"Besoin:\n{rec.get('need') or '-'}\n\nHorodatage: {rec.get('ts')}")
    port = int(os.environ.get("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(os.environ.get("SMTP_USER", ""), pwd)
        s.send_message(m)
    return True


@app.post("/v1/leads", tags=["telemetry"], status_code=204)
async def create_lead(lead: Lead):
    """Access request / waitlist signup (offer page). Stored locally, never shared."""
    import json as _json
    from datetime import datetime, timezone

    rec = {"ts": datetime.now(timezone.utc).isoformat(), "email": lead.email[:200],
           "org": (lead.org or "")[:200], "need": (lead.need or "")[:2000]}
    try:
        os.makedirs(os.path.dirname(LEADS_PATH), exist_ok=True)
        with open(LEADS_PATH, "a") as f:
            f.write(_json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as e:
        log.error("lead not persisted: %s", e)
        raise HTTPException(500, "Storage error")
    M_LEADS.add(1, {"kind": "enterprise" if "10" in (lead.need or "") else "waitlist"})

    async def _notify():
        try:
            await asyncio.to_thread(_send_lead_email, rec)
        except Exception as e:  # mail is best-effort, the lead is already saved
            log.warning("lead email failed: %s", e)

    asyncio.get_running_loop().create_task(_notify())
    return None


class FrontendEvent(BaseModel):
    event: str
    meta: str | None = None


@app.post("/v1/events", tags=["telemetry"], status_code=204)
async def track(ev: FrontendEvent, request: Request):
    """Anonymous frontend usage beacon -> OTel counter.

    No cookies, no IP stored: the IP is only mapped in-memory to a country
    code (dbip-country-lite) used as a metric label.
    """
    M_FRONTEND.add(1, {"event": ev.event[:40], "country": _client_country(request)})
    return None
