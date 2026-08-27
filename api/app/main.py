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
import copy as _copy
import json
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
BAN_REVERSE_URL = "https://api-adresse.data.gouv.fr/reverse/"
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
# Agrégat bâtiment : 6 h par défaut — les sources ouvertes bougent lentement
# (millésime BDNB annuel, DPE mensuel, piézométrie quotidienne).
BUILDING_CACHE_TTL = float(os.environ.get("BUILDING_CACHE_TTL", "21600"))
M_CACHE = _meter.create_counter("ecobuilding_upstream_cache", description="Upstream cache hits/misses", unit="1")


async def _cached_get_json(url: str, params: dict, ttl: float, headers: dict | None = None):
    # `headers` ne participe PAS à la clé : il ne porte que des jetons
    # d'authentification, jamais rien qui change la réponse — et l'y mettre
    # écrirait un secret dans une clé de cache.
    key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.monotonic()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        _CACHE.move_to_end(key)
        M_CACHE.add(1, {"result": "hit"})
        return hit[1]
    M_CACHE.add(1, {"result": "miss"})
    resp = await _client.get(url, params=params, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    _CACHE[key] = (now, data)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return data


# --- Cache disque des tuiles bâtiments (voir /v1/tiles) ----------------------
TILES_DIR = os.environ.get("TILES_DIR", "/tiles")
TILES_UPSTREAM = os.environ.get(
    "BDNB_TILES_URL",
    "https://api.bdnb.io/v1/bdnb/tuiles/batiment_groupe/{z}/{x}/{y}.pbf")
# Le millésime BDNB est annuel : 30 jours de cache est conservateur.
TILE_TTL = float(os.environ.get("TILE_TTL", str(30 * 86400)))
# Garde-fou : les appels amont de tuiles partagent l'IP (donc le quota) avec les
# appels de DONNÉES. On leur réserve un débit borné pour qu'un balayage de carte
# ne puisse jamais assécher les fiches.
TILE_UPSTREAM_RPM = int(os.environ.get("TILE_UPSTREAM_RPM", "40"))
_TILE_LOCKS: dict = {}
_tile_hits: list = []
M_TILES = _meter.create_counter("ecobuilding_tiles", description="Building tile cache", unit="1")


def _tile_budget() -> bool:
    """Fenêtre glissante d'une minute sur les appels amont de tuiles."""
    now = time.monotonic()
    _tile_hits[:] = [t for t in _tile_hits if now - t < 60]
    if len(_tile_hits) >= TILE_UPSTREAM_RPM:
        return False
    _tile_hits.append(now)
    return True


def _tile_read(path: str, ttl):
    """Contenu en cache, ou None. ttl=None : accepte une tuile périmée."""
    try:
        if ttl is not None and time.time() - os.path.getmtime(path) > ttl:
            return None
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _tile_write(path: str, blob: bytes) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, path)                       # jamais de tuile tronquée
    except OSError as e:
        log.warning("cache tuile non écrit (%s): %s", path, e)


def _tile_response(blob: bytes):
    from fastapi.responses import Response
    return Response(
        content=blob, media_type="application/vnd.mapbox-vector-tile",
        headers={"Cache-Control": f"public, max-age={int(TILE_TTL)}",
                 "Access-Control-Allow-Origin": "*"})


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
            "bearing": bearing, "bdnb_id": bdnb_id,
            # Le renderer doit tirer les tuiles de NOTRE cache : sinon chaque
            # fiche consommait ~15 requêtes du quota BDNB de la VM (10 000/mois).
            "tiles": f"{PUBLIC_BASE_URL}/api/v1/tiles/batiment_groupe/"
                     "{z}/{x}/{y}.pbf"}, timeout=45.0)
        r.raise_for_status()
        import base64
        return "data:image/png;base64," + base64.b64encode(r.content).decode()
    except Exception as e:
        log.warning("building map render failed for %s: %s", bdnb_id, e)
        return None


IGN_WMS_URL = "https://data.geopf.fr/wms-r/wms"


async def _building_ring(bdnb_id) -> list[tuple[float, float]] | None:
    """L'emprise du bâtiment en WGS84, ou None.

    Les géométries BDNB sont en Lambert-93 (EPSG:2154) ; tout le reste de la
    fiche raisonne en degrés.
    """
    if not bdnb_id:
        return None
    try:
        rows = await _cached_get_json(
            BDNB_BASE_URL,
            {"batiment_groupe_id": f"eq.{bdnb_id}", "select": "geom_groupe", "limit": "1"},
            ttl=86400)
        if not isinstance(rows, list) or not rows:
            return None
        raw = rows[0].get("geom_groupe")
        if not raw:
            return None
        import json as _json

        from pyproj import Transformer

        to_wgs84 = Transformer.from_crs(2154, 4326, always_xy=True)
        geom = _json.loads(raw) if isinstance(raw, str) else dict(raw)
        polygons = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                    else [geom["coordinates"]])
        rings = []
        for polygon in polygons:
            ring = polygon[0] if polygon else None
            if ring and len(ring) > 3:
                rings.append([to_wgs84.transform(c[0], c[1]) for c in ring])
        # Un « bâtiment groupe » peut réunir plusieurs corps : on garde le plus
        # étendu, celui que le lecteur identifiera comme « la maison ».
        return max(rings, key=len) if rings else None
    except Exception as e:
        log.warning("emprise indisponible (%s): %s", bdnb_id, e)
        return None


async def _aerial_view(bdnb_id, lon, lat, span: float = 0.0009) -> dict:
    """Vue aérienne du bâtiment, et son emprise tracée par-dessus.

    Le rendu 3D dit la CLASSE ÉNERGÉTIQUE ; la photo dit ce qu'on ACHÈTE — le
    terrain, les arbres, la piscine, le portail, l'allée. Rien de tout cela
    n'existe en donnée structurée, et c'est précisément ce qu'un acheteur
    regarde en premier (#200, #258).

    Mais une photo de lotissement où cinq pavillons se ressemblent ne dit pas
    lequel est le sien (#263). D'où deux précautions : la photo est cadrée sur
    le BÂTIMENT et non sur le point d'adresse — souvent situé au portail, le
    bâtiment se retrouvait en haut à gauche —, et son emprise est tracée dessus.

    Photo IGN sous Licence Ouverte, sans clé ni compte. Une panne renvoie
    (None, None) : la fiche se génère toujours, simplement sans cette vue.
    """
    if lon is None or lat is None:
        return {}

    ring = await _building_ring(bdnb_id)
    centre_lon, centre_lat = lon, lat
    if ring:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        centre_lon = (min(xs) + max(xs)) / 2
        centre_lat = (min(ys) + max(ys)) / 2

    # Cadre 16/9 autour du centre, pour la même largeur que le rendu 3D.
    west, south = centre_lon - span, centre_lat - span * 0.56
    width, height = span * 2, span * 2 * 0.56
    bbox = f"{west},{south},{centre_lon + span},{centre_lat + span * 0.56}"
    frame = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
             "CRS": "CRS:84", "BBOX": bbox, "WIDTH": "960", "HEIGHT": "540"}

    async def layer(name, fmt, transparent=False):
        params = dict(frame, LAYERS=name, STYLES="", FORMAT=fmt)
        if transparent:
            params["TRANSPARENT"] = "TRUE"
        r = await _client.get(IGN_WMS_URL, params=params, timeout=25.0)
        r.raise_for_status()
        if not r.headers.get("content-type", "").startswith("image/"):
            return None                      # le WMS répond ses erreurs en XML
        import base64
        return f"data:{fmt};base64," + base64.b64encode(r.content).decode()

    try:
        # DEUX requêtes, et non une composition côté serveur IGN : demander les
        # deux couches d'un coup impose le PNG pour toute l'image (4 canaux),
        # soit 1,4 Mo au lieu de 84 Ko. La photo reste en JPEG, le cadastre seul
        # part en PNG transparent — 303 Ko à deux, 4,5 fois plus léger.
        image, parcels = await asyncio.gather(
            layer("HR.ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"),
            layer("CADASTRALPARCELS.PARCELLAIRE_EXPRESS", "image/png", transparent=True))
        if image is None:
            return {}
    except Exception as e:
        log.warning("vue aérienne indisponible (%s, %s): %s", lon, lat, e)
        return {}

    outline = None
    if ring:
        # Repère 0–100 posé sur l'image : l'axe des ordonnées d'une image
        # descend, celui du monde monte.
        outline = " ".join(
            f"{(plon - west) / width * 100:.2f},{(1 - (plat - south) / height) * 100:.2f}"
            for plon, plat in ring)
    return {"image": image, "parcels": parcels, "outline": outline}


def _rental_ban(dpe_class: str | None) -> dict | None:
    if not dpe_class:
        return None
    date = DPE_BAN_DATES.get(dpe_class.upper())
    return {
        "dpe_class": dpe_class.upper(),
        "rental_ban_date": date,
        # ISO dans le CHAMP, français dans la PHRASE.
        #
        # La note disait « à partir du 2025-01-01 » : une date technique posée
        # dans une phrase française, sur la ligne la plus alarmante de la fiche
        # — celle qui annonce à quelqu'un qu'il ne pourra plus louer son bien.
        # C'est le défaut que nous avions signalé à une source tierce le matin
        # même (confinia-core#269) ; il était chez nous aussi.
        #
        # `rental_ban_date` reste en ISO : un champ se compare et se recopie,
        # une phrase se lit.
        "note": (
            f"Location interdite à partir du {_date_fr(date)} "
            "(loi Climat et Résilience)"
            if date
            else "Aucune interdiction de location prévue pour cette classe"
        ),
    }


# --- Dynamique du marché : DIA Montpellier Méditerranée Métropole (#246) ---
# Indicateur AVANCÉ (déclarations notariales AU MOMENT de la vente) là où DVF
# publie avec ~un semestre de retard. Fichier produit mensuellement par
# `python -m app.dia_refresh` (deploy/dia-refresh.sh) ; absent = bloc absent,
# rien ne casse. ⚠ montants de MISE EN VENTE, pas prix finaux.
DIA_PATH = os.environ.get("DIA_PATH", "/leads/dia.json")
_dia_state = {"mtime": None, "data": None}


def _dia_data():
    try:
        m = os.path.getmtime(DIA_PATH)
    except OSError:
        return None
    if _dia_state["mtime"] != m:
        with open(DIA_PATH) as f:
            _dia_state["data"] = json.load(f)
        _dia_state["mtime"] = m
    return _dia_state["data"]


def _point_in_ring(lon, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and                 lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _point_in_geom(lon, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    for poly in polys:
        if _point_in_ring(lon, lat, poly[0]) and                 not any(_point_in_ring(lon, lat, hole) for hole in poly[1:]):
            return True
    return False


def _dia_market(lon, lat, commune_insee):
    """Bloc marché DIA pour un bâtiment : sous-quartier (point-in-polygon,
    Montpellier-ville) sinon commune (INSEE). None hors métropole."""
    d = _dia_data()
    if not d:
        return None
    zone = None
    if lon is not None and lat is not None:
        for z in d["zones"]:
            if "polygon" in z and _point_in_geom(lon, lat, z["polygon"]):
                zone = z
                break
    if zone is None and commune_insee:
        zone = next((z for z in d["zones"]
                     if z.get("commune_insee") == str(commune_insee)), None)
    if not zone:
        return None
    return {"zone": zone["name"],
            "scope": "sous-quartier" if "polygon" in zone else "commune",
            "listings_12m": zone["n_12m"], "listings_3m": zone["n_3m"],
            "median_asking_eur": zone["median_asking_eur"],
            "median_asking_eur_m2": zone["median_asking_eur_m2"],
            "types": zone["types"], "updated": d["updated"],
            "note": "Montants de mise en vente déclarés (DIA), pas les prix "
                    "de vente définitifs."}


# --- Référentiel National des Bâtiments -----------------------------------
# L'ID-RNB est l'identifiant PERMANENT (12 caractères) qui sert de clé pivot
# entre cadastre, BAN, BDNB et ADEME — contrairement à l'id BDNB qui peut
# changer d'un millésime à l'autre (#28). Pas de table de liens dans notre
# base : résolution par l'API publique, au centroïde du bâtiment, cache long
# (l'id est permanent par construction).
RNB_API_URL = os.environ.get("RNB_API_URL", "https://rnb-api.beta.gouv.fr/api/alpha").rstrip("/")
RNB_CACHE_TTL = float(os.environ.get("RNB_CACHE_TTL", str(30 * 86400)))


async def _rnb_lookup(lon, lat):
    """ID-RNB du bâtiment au point donné (bbox ~25 m, emprise dont le point de
    référence est le plus proche). None si l'API RNB est down ou ne connaît
    pas le bâtiment — la fiche ne doit jamais en dépendre."""
    if lon is None or lat is None:
        return None
    try:
        d = 0.00022
        data = await _cached_get_json(
            f"{RNB_API_URL}/buildings/",
            {"bbox": f"{lon - d},{lat - d},{lon + d},{lat + d}"},
            ttl=RNB_CACHE_TTL)
        results = (data or {}).get("results") or []
        best, best_d2 = None, None
        for r in results:
            pt = (r.get("point") or {}).get("coordinates")
            if not pt or not r.get("rnb_id"):
                continue
            d2 = (pt[0] - lon) ** 2 + (pt[1] - lat) ** 2
            if best_d2 is None or d2 < best_d2:
                best, best_d2 = r, d2
        if best:
            return {"rnb_id": best["rnb_id"],
                    "url": f"https://rnb.beta.gouv.fr/batiments/{best['rnb_id']}"}
    except Exception as e:
        log.warning("RNB lookup failed (%s,%s): %s", lon, lat, e)
    return None


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


@app.get("/v1/tiles/batiment_groupe/{z}/{x}/{y}.pbf", tags=["buildings"])
async def building_tile(z: int, x: int, y: int):
    """Tuiles vectorielles des bâtiments, servies depuis NOTRE cache disque.

    Pourquoi ce proxy (et pas l'URL BDNB directement dans la carte) :
    api.bdnb.io est anonyme et plafonné à 120 req/min et 10 000 req/MOIS **par
    IP**. Or MapLibre, au-dessus du maxzoom d'une source (14 ici), instancie une
    tuile par identifiant sur-zoomé : à z18 avec du pitch, la MÊME tuile part
    10 à 17 fois en parallèle. Résultat mesuré : ~15 requêtes par affichage,
    donc un 429 au bout de quelques rechargements — la carte 3D se vidait alors
    en silence, et chaque fiche PDF (le renderer tape les mêmes tuiles depuis
    l'IP de la VM) consommait autant du quota mensuel.

    Ici : les N requêtes concurrentes d'un même affichage sont mutualisées en UN
    seul appel amont (verrou par tuile), le résultat est gardé sur disque, et le
    navigateur reçoit un Cache-Control long — que BDNB n'envoie pas. En régime
    établi, une tuile n'est demandée à BDNB qu'une fois par TILE_TTL.
    """
    if not (0 <= z <= 22 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise HTTPException(status_code=404, detail="Tuile hors domaine")

    path = os.path.join(TILES_DIR, str(z), str(x), f"{y}.pbf")
    fresh = _tile_read(path, TILE_TTL)
    if fresh is not None:
        M_TILES.add(1, {"result": "hit"})
        return _tile_response(fresh)

    # Un seul appel amont par tuile, même si 17 requêtes arrivent ensemble.
    lock = _TILE_LOCKS.setdefault((z, x, y), asyncio.Lock())
    async with lock:
        again = _tile_read(path, TILE_TTL)          # remplie pendant l'attente ?
        if again is not None:
            M_TILES.add(1, {"result": "hit_coalesced"})
            return _tile_response(again)
        try:
            if not _tile_budget():
                raise RuntimeError("budget amont épuisé")
            M_TILES.add(1, {"result": "miss"})
            r = await _client.get(TILES_UPSTREAM.format(z=z, x=x, y=y))
            if r.status_code == 404:                # hors couverture BDNB
                _tile_write(path, b"")
                return _tile_response(b"")
            r.raise_for_status()
            _tile_write(path, r.content)
            return _tile_response(r.content)
        except Exception as e:
            # Amont KO (429, panne, timeout) : mieux vaut une tuile périmée
            # qu'une carte vide. Sinon 503 — le front le dit à l'utilisateur.
            stale = _tile_read(path, ttl=None)
            if stale is not None:
                M_TILES.add(1, {"result": "stale"})
                return _tile_response(stale)
            M_TILES.add(1, {"result": "error"})
            log.warning("tuile %s/%s/%s indisponible: %s", z, x, y, e)
            raise HTTPException(status_code=503, detail="Tuiles bâtiments indisponibles",
                                headers={"Retry-After": "60", "Cache-Control": "no-store"})
        finally:
            _TILE_LOCKS.pop((z, x, y), None)


async def _commune_of(lat: float, lon: float) -> str | None:
    """INSEE code of the commune containing a point, via BAN reverse geocoding."""
    try:
        data = await _cached_get_json(
            BAN_REVERSE_URL, {"lat": lat, "lon": lon, "limit": 1}, ttl=86400)
        feats = data.get("features") or []
        return feats[0]["properties"].get("citycode") if feats else None
    except Exception:
        return None


@app.get("/v1/suggest", tags=["geocoding"])
async def suggest(
    q: str = Query(min_length=3, description="Partial address, street or city"),
    lat: float | None = Query(None, ge=-90, le=90, description="Bias results near this point"),
    lon: float | None = Query(None, ge=-180, le=180, description="Bias results near this point"),
):
    """Autocomplete (BAN): cities, streets and full addresses.

    `type` is one of municipality | street | locality | housenumber; only
    housenumber entries can be looked up as buildings — others are navigation
    targets.

    Pass `lat`/`lon` to rank results by proximity. Mobile use is local by
    nature — you are standing in front of the building, or preparing a visit
    nearby — and a common-noun query ("école", "mairie") is meaningless
    nationwide: searching "ecole" returned schools from all over France.
    """
    # Deux requêtes, et non un simple tri.
    #
    # BAN's own `lat`/`lon` bias is too weak to matter, and re-ranking what it
    # returns does nothing: measured from Saint-Vallier (71), NONE of the 20
    # results for "rue de la republique" were within 40 km. The nearby ones are
    # not ranked low — they are absent. Text score decides alone.
    #
    # So we ask twice: once restricted to the commune under the user, once
    # nationwide. Local answers come first, the rest still follows — someone
    # preparing a visit two departments away is not cut off.
    local: list = []
    if lat is not None and lon is not None:
        # Rounded to ~1 km before caching: the exact position would give every
        # user their own cache entry, and store a precision we have no reason
        # to keep.
        citycode = await _commune_of(round(lat, 2), round(lon, 2))
        if citycode:
            near_data = await _cached_get_json(
                BAN_URL, {"q": q, "limit": 6, "citycode": citycode}, ttl=3600)
            local = near_data.get("features") or []
    data = await _cached_get_json(BAN_URL, {"q": q, "limit": 6}, ttl=3600)
    seen = {f["properties"].get("id") for f in local}
    feats = local + [f for f in data.get("features", [])
                     if f["properties"].get("id") not in seen]
    feats = feats[:6]
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


# Départements et collectivités d'outre-mer : la BDNB s'arrête à la métropole
# (zéro ligne sur 971 à 976, vérifié source par source), et aucune adresse
# voisine ne changera cela. Le dire vaut mieux que de laisser chercher.
_OUTRE_MER = ("97", "98")


def _commune_de_ban(ban_id):
    """Code INSEE porté par un identifiant BAN (`97411_1060` -> `97411`)."""
    if not isinstance(ban_id, str) or "_" not in ban_id:
        return None
    code = ban_id.split("_", 1)[0]
    return code if len(code) == 5 else None


def _motif_sans_batiment(ban_id):
    """Pourquoi cette adresse n'a pas de bâtiment — jamais None quand il n'y en a pas.

    Deux motifs, et la différence compte : hors métropole c'est définitif et
    général, ailleurs c'est une lacune ponctuelle que l'adresse voisine peut
    combler. L'ancien message servait la seconde phrase dans les deux cas, donc
    une invitation à chercher là où il n'y a rien à trouver.

    `reason` est stable et destiné au code ; `text` est destiné à l'oeil.
    """
    code = _commune_de_ban(ban_id)
    if code and code.startswith(_OUTRE_MER):
        return {"reason": "outre_mer",
                "text": "La base nationale des bâtiments (BDNB) s'arrête à la "
                        "métropole : aucun bâtiment n'y est décrit outre-mer. "
                        "Ce qui suit ne dépend que de la position."}
    return {"reason": "absent_bdnb",
            "text": "Aucun bâtiment n'est décrit à cette adresse dans la base "
                    "nationale (BDNB). Il l'est peut-être sous une adresse "
                    "voisine. Ce qui suit ne dépend que de la position."}


async def _do_lookup(q, ban_id, address, lon, lat):
    rows = await _cached_get_json(
        BDNB_URL, {"cle_interop_adr": f"eq.{ban_id}", "limit": "5"}, ttl=86400
    )
    if not isinstance(rows, list):
        log.warning("BDNB error: %s", rows)
        rows = []

    commune = (rows[0].get("code_commune_insee") if rows
               else _commune_de_ban(ban_id))
    first_id = rows[0].get("batiment_groupe_id") if rows else None

    # UN SEUL agrégat par bâtiment (demande opérateur : « charger une fois, pas
    # deux »). La recherche par adresse refaisait ici tout l'éventail de sources
    # pour son propre compte ; la fiche PDF, qui passe par building(), ne
    # retrouvait donc rien en cache et rejouait l'orchestration complète
    # (mesuré : 5,7 s de panneau, puis 15,2 s refaits pour le PDF). On délègue
    # au calcul canonique, qui est mis en cache — et l'adresse hérite au passage
    # des prix DVF et de l'ID-RNB, jusqu'ici réservés au clic sur la carte.
    if first_id is not None:
        try:
            agg = await building(first_id, lon, lat)
        except HTTPException:
            agg = None                 # id introuvable : contexte seul, plus bas
        if agg is not None:
            agg["query"] = {"q": q, "ban_id": ban_id, "address": address,
                            "lon": lon, "lat": lat}
            # L'adresse peut couvrir plusieurs « bâtiments groupe » : on garde la
            # liste complète de la recherche, en conservant l'enrichissement
            # (ID-RNB) que building() a posé sur le premier.
            if len(rows) > 1:
                agg["buildings"] = [agg["buildings"][0]] + \
                    [_normalize_building(r) for r in rows[1:]]
            M_LOOKUPS.add(1, {"status": "ok"})
            return agg

    # Aucun bâtiment BDNB à cette adresse : on sert quand même le contexte
    # (risques, nappe, solaire…), qui ne dépend que du point.
    (risks, groundwater, solar_pv, water_network, official_dpe,
     local_taxes, schools, commune_hist) = await asyncio.gather(
        _area_risks(lon, lat), _groundwater(lon, lat), _solar_pv(lon, lat),
        _water_network(commune), _noop(),
        _local_taxes(commune), _nearby_schools(lon, lat),
        _commune_history(commune, lon, lat))

    M_LOOKUPS.add(1, {"status": "no_building"})
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
    market_dia = _dia_market(lon, lat, commune)
    if market_dia:
        sources.append("DIA — Montpellier Méditerranée Métropole — Open Data")
    sources += _credits_confinia(commune_hist, sources)
    result = {
        "query": {"q": q, "ban_id": ban_id, "address": address, "lon": lon, "lat": lat},
        "buildings": [_normalize_building(r) for r in rows],
        "market_dia": market_dia,
        "area_risks": risks,
        "groundwater": groundwater,
        "solar_pv": solar_pv,
        "water_network": water_network,
        "official_dpe": official_dpe,
        "local_taxes": local_taxes,
        "schools": schools,
        "commune": commune_hist,
        "sources": sources,
        "no_building": _motif_sans_batiment(ban_id),
    }
    return result


@app.get("/v1/lookup", tags=["buildings"])
async def lookup(
    request: Request,
    q: str | None = Query(None, description="Free-text address"),
    ban_id: str | None = Query(None, description="BAN interop id, e.g. 80021_6370_00007"),
    lon: float | None = Query(None, description="Longitude (used for the risk report when ban_id is given)"),
    lat: float | None = Query(None, description="Latitude (idem)"),
    rnb_id: str | None = Query(None, min_length=12, max_length=14,
                               description="ID-RNB (Référentiel National des Bâtiments)"),
):
    """Address -> geocode (BAN) -> building record (BDNB) -> risk report (Géorisques)."""
    _meter_if_keyed(request, "lookup")
    if rnb_id:
        # Entrée par la clé pivot de l'écosystème : l'ID-RNB se résout en un
        # point (API RNB), puis le flux position habituel prend le relais.
        try:
            b = await _cached_get_json(f"{RNB_API_URL}/buildings/{rnb_id.replace('-', '').upper()}/",
                                       {}, ttl=RNB_CACHE_TTL)
            pt = (b or {}).get("point", {}).get("coordinates")
        except Exception:
            pt = None
        if not pt:
            raise HTTPException(404, "ID-RNB inconnu")
        lon, lat = pt[0], pt[1]
        # rejoindre le flux normal : point -> adresse BAN la plus proche
        geo = await _cached_get_json(
            BAN_REVERSE_URL, {"lon": lon, "lat": lat, "type": "housenumber"}, ttl=86400)
        feats = geo.get("features", [])
        if not feats:
            raise HTTPException(404, "Aucune adresse BAN au point de l'ID-RNB")
        q, ban_id = None, feats[0]["properties"]["id"]
    q, ban_id, address, lon, lat = await _resolve_address(q, ban_id, lon, lat)
    return await _do_lookup(q, ban_id, address, lon, lat)


async def _resolve_address(q, ban_id, lon, lat):
    """Adresse libre -> (q, ban_id, libellé, lon, lat). Partagé par /v1/lookup
    et sa variante en flux."""
    if not q and not ban_id and lon is None:
        raise HTTPException(422, "Provide q, ban_id or rnb_id")
    address = None
    if not ban_id:
        geo = await _cached_get_json(BAN_URL, {"q": q, "limit": 1, "type": "housenumber"}, ttl=86400)
        feats = geo.get("features", [])
        if not feats:
            M_LOOKUPS.add(1, {"status": "address_not_found"})
            raise HTTPException(404, "Address not found (BAN)")
        pr = feats[0]["properties"]
        ban_id, address = pr["id"], pr["label"]
        lon, lat = feats[0]["geometry"]["coordinates"][:2]
    return q, ban_id, address, lon, lat


@app.get("/v1/lookup/stream", tags=["buildings"])
async def lookup_stream(
    request: Request,
    q: str | None = Query(None, description="Free-text address"),
    ban_id: str | None = Query(None),
    lon: float | None = Query(None),
    lat: float | None = Query(None),
):
    """Recherche par adresse, servie **au fil de l'eau** (NDJSON).

    Même flux d'événements que `/v1/buildings/{id}/stream` : le bâtiment part
    dès que BDNB a répondu, les neuf sources suivent à leur rythme. L'agrégat
    final est mis en cache comme d'habitude, donc la fiche PDF qui suit ne
    rejoue rien."""
    from fastapi.responses import StreamingResponse

    _meter_if_keyed(request, "lookup")
    q, ban_id, address, lon, lat = await _resolve_address(q, ban_id, lon, lat)
    rows = await _cached_get_json(
        BDNB_URL, {"cle_interop_adr": f"eq.{ban_id}", "limit": "5"}, ttl=86400)
    rows = rows if isinstance(rows, list) else []
    if not rows:
        # Pas de bâtiment : on renvoie l'agrégat de contexte en une seule ligne.
        data = await _do_lookup(q, ban_id, address, lon, lat)

        async def one():
            yield json.dumps({"type": "core", "query": data["query"],
                              "buildings": data["buildings"],
                              "no_building": data.get("no_building")}) + "\n"
            # Le contexte part en BLOCS, comme sur le chemin ordinaire.
            #
            # Il ne partait qu'avec `done`, et les applications mobiles, qui
            # n'affichent que des blocs, restaient donc sur un écran vide alors
            # que les risques de la zone étaient déjà en main.
            for nom in ("area_risks", "groundwater", "solar_pv",
                        "water_network", "official_dpe", "local_taxes",
                        "schools", "commune"):
                yield json.dumps({"type": "block", "name": nom,
                                  "value": data.get(nom)}) + "\n"
            yield json.dumps(dict(data, type="done")) + "\n"
        return StreamingResponse(one(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store"})

    extra = [_normalize_building(r) for r in rows[1:]]
    events = _building_events(rows[0]["batiment_groupe_id"], lon, lat,
                              # `address` seulement s'il existe : sinon il
                              # écraserait le titre arbitré au point cliqué.
                              query_extra={k: v for k, v in
                                           (("q", q), ("ban_id", ban_id), ("address", address))
                                           if v is not None},
                              extra_rows=extra)
    return StreamingResponse(events, media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


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
    # Cache de l'AGRÉGAT (demande opérateur) : chaque affichage refaisait
    # l'orchestration complète (BDNB, Géorisques, Hub'Eau, DVF, ADEME,
    # fiscalité, écoles, PVGIS…) même quand chaque source était en cache.
    # Clé = bâtiment + position arrondie (~11 m) : l'arbitrage d'adresse (#152)
    # dépend du point cliqué. COPIE défensive à la lecture ET à l'écriture —
    # la route PDF mute query.address et contaminerait l'entrée sinon.
    cache_key = (f"building:{bdnb_id}:"
                 f"{round(lon, 4) if lon is not None else '-'}:"
                 f"{round(lat, 4) if lat is not None else '-'}")
    hit = _CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < BUILDING_CACHE_TTL:
        _CACHE.move_to_end(cache_key)
        M_CACHE.add(1, {"result": "hit_building"})
        return _copy.deepcopy(hit[1])
    rows = await _cached_get_json(
        BDNB_BASE_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "1"}, ttl=86400
    )
    if not isinstance(rows, list) or not rows:
        raise HTTPException(404, "Unknown building id")
    row = rows[0]
    M_LOOKUPS.add(1, {"status": "by_id"})
    vals = dict(zip(_BLOCK_NAMES, await asyncio.gather(
        *_building_block_coros(bdnb_id, lon, lat, row))))
    result = _assemble_building(bdnb_id, lon, lat, row, vals)
    _CACHE[cache_key] = (time.monotonic(), _copy.deepcopy(result))
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result


# Les neuf sources d'un bâtiment, NOMMÉES : l'agrégat classique les attend
# toutes, le flux (/v1/buildings/{id}/stream) les émet au fil de l'eau.
_BLOCK_NAMES = ("prices", "area_risks", "groundwater", "solar_pv", "click_addr",
                "water_network", "official_dpe", "local_taxes", "schools", "rnb",
                "commune", "dpe_spread")


def _building_block_coros(bdnb_id, lon, lat, row):
    commune = row.get("code_commune_insee")
    return (_dvf_prices(bdnb_id), _area_risks(lon, lat),
            _groundwater(lon, lat), _solar_pv(lon, lat),
            _click_address(bdnb_id, lon, lat),
            _water_network(commune), _official_dpe(bdnb_id),
            _local_taxes(commune), _nearby_schools(lon, lat),
            _rnb_lookup(lon, lat), _commune_history(commune, lon, lat),
            _dpe_spread(bdnb_id, lon, lat))



def _credits_confinia(commune_hist, deja):
    """Crédits des sources que Confinia a RÉELLEMENT lues pour cette commune.

    La donnée est ouverte, pas anonyme : `INTEGRATION.md` en fait une
    obligation, et `sources` y nomme le millésime lu — jamais « le dernier ».
    """
    lignes = []
    for a in (commune_hist or {}).get("attribution") or []:
        mention, licence = a.get("attribution"), a.get("license")
        if not mention:
            continue
        ligne = f"{mention} — {licence}" if licence else mention
        if ligne not in deja and ligne not in lignes:
            lignes.append(ligne)
    return lignes


def _assemble_building(bdnb_id, lon, lat, row, v):
    """Agrégat final à partir des blocs (tous présents, éventuellement None)."""
    prices, risks, groundwater = v["prices"], v["area_risks"], v["groundwater"]
    solar_pv, click_addr = v["solar_pv"], v["click_addr"]
    water_network, official_dpe = v["water_network"], v["official_dpe"]
    local_taxes, schools, rnb = v["local_taxes"], v["schools"], v["rnb"]
    commune_hist = v.get("commune")
    dpe_spread = v.get("dpe_spread")
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
    market_dia = _dia_market(lon, lat, row.get("code_commune_insee"))
    if rnb:
        sources.append("Référentiel National des Bâtiments (RNB) — Licence Ouverte")
    if market_dia:
        sources.append("DIA — Montpellier Méditerranée Métropole — Open Data")
    sources += _credits_confinia(commune_hist, sources)
    result = {
        # Prefer the group-member address at the clicked point (#152); the
        # principal address stays on buildings[0].address for the UI's row.
        "query": {"bdnb_id": bdnb_id,
                  "address": click_addr or row.get("libelle_adr_principale_ban"),
                  "lon": lon, "lat": lat},
        "buildings": [dict(_normalize_building(row),
                           **({"rnb_id": rnb["rnb_id"]} if rnb else {}))],
        "rnb": rnb,
        "market_dia": market_dia,
        "area_risks": risks,
        "groundwater": groundwater,
        "solar_pv": solar_pv,
        "water_network": water_network,
        "official_dpe": official_dpe,
        "local_taxes": local_taxes,
        "schools": schools,
        "prices": prices,
        "commune": commune_hist,
        "dpe_spread": dpe_spread,
        "sources": sources,
    }
    return result


async def _named_block(name, coro):
    """(nom, valeur) pour pouvoir émettre un bloc dès qu'il arrive."""
    try:
        return name, await coro
    except Exception as e:                 # une source KO n'arrête pas le flux
        log.warning("bloc %s indisponible: %s", name, e)
        return name, None


@app.get("/v1/buildings/{bdnb_id}/stream", tags=["buildings"])
async def building_stream(
    bdnb_id: str,
    lon: float | None = Query(None),
    lat: float | None = Query(None),
    request: Request = None,
):
    """Même agrégat que `/v1/buildings/{id}`, mais **au fil de l'eau** (NDJSON).

    Neuf sources ouvertes sont interrogées par bâtiment : attendre la plus lente
    pour afficher quoi que ce soit faisait patienter devant un panneau vide.
    Ici le bâtiment part dès que BDNB a répondu, puis chaque bloc est émis à son
    arrivée. Une ligne JSON par événement :
      {"type":"core", "query":…, "buildings":[…]}
      {"type":"block","name":"area_risks","value":…}          (×9)
      {"type":"done", "sources":[…], "market_dia":…, "query":…}
    L'agrégat complet est mis en cache à la fin, sous la MÊME clé que
    `/v1/buildings` : la fiche PDF qui suit ne rejoue donc rien.
    """
    from fastapi.responses import StreamingResponse

    if request is not None:
        _meter_if_keyed(request, "buildings")
    return StreamingResponse(_building_events(bdnb_id, lon, lat),
                             media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store",
                                      "X-Accel-Buffering": "no"})


async def _building_events(bdnb_id, lon, lat, query_extra=None, extra_rows=()):
    """Flux NDJSON d'un bâtiment. `query_extra` / `extra_rows` servent au
    chemin « recherche par adresse » (q/ban_id, et les autres bâtiments
    groupe de la même adresse)."""
    def _q(base):
        return dict(base, **(query_extra or {}))

    cache_key = (f"building:{bdnb_id}:"
                 f"{round(lon, 4) if lon is not None else '-'}:"
                 f"{round(lat, 4) if lat is not None else '-'}")
    hit = _CACHE.get(cache_key)
    if hit and time.monotonic() - hit[0] < BUILDING_CACHE_TTL:
        _CACHE.move_to_end(cache_key)
        M_CACHE.add(1, {"result": "hit_building"})
        done = _copy.deepcopy(hit[1])
        yield json.dumps({"type": "core", "query": _q(done["query"]),
                          "buildings": done["buildings"] + list(extra_rows)}) + "\n"
        for name in ("area_risks", "groundwater", "solar_pv", "water_network",
                     "official_dpe", "local_taxes", "schools", "prices", "rnb",
                     "commune", "dpe_spread"):
            yield json.dumps({"type": "block", "name": name,
                              "value": done.get(name)}) + "\n"
        yield json.dumps({"type": "done", "sources": done["sources"],
                          "market_dia": done.get("market_dia"),
                          "buildings": done["buildings"] + list(extra_rows),
                          "query": _q(done["query"])}) + "\n"
        return

    rows = await _cached_get_json(
        BDNB_BASE_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "1"}, ttl=86400)
    if not isinstance(rows, list) or not rows:
        yield json.dumps({"type": "error", "status": 404,
                          "detail": "Unknown building id"}) + "\n"
        return
    row = rows[0]
    M_LOOKUPS.add(1, {"status": "by_id_stream"})
    # Le bâtiment lui-même part TOUT DE SUITE : c'est ce que l'utilisateur
    # est venu voir (adresse, DPE, année, hauteur).
    yield json.dumps({"type": "core",
                      "query": _q({"bdnb_id": bdnb_id,
                                   "address": row.get("libelle_adr_principale_ban"),
                                   "lon": lon, "lat": lat}),
                      "buildings": [_normalize_building(row)] + list(extra_rows)}) + "\n"

    vals = {}
    coros = _building_block_coros(bdnb_id, lon, lat, row)
    for fut in asyncio.as_completed(
            [_named_block(n, c) for n, c in zip(_BLOCK_NAMES, coros)]):
        name, value = await fut
        vals[name] = value
        if name != "click_addr":       # interne : sert à titrer, pas un bloc
            yield json.dumps({"type": "block", "name": name, "value": value}) + "\n"

    result = _assemble_building(bdnb_id, lon, lat, row, vals)
    _CACHE[cache_key] = (time.monotonic(), _copy.deepcopy(result))
    _CACHE.move_to_end(cache_key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    # `done` porte ce qui ne se calcule qu'à la fin : le titre arbitré
    # (#152), les sources effectivement utilisées, le bloc DIA.
    yield json.dumps({"type": "done", "query": _q(result["query"]),
                      "buildings": result["buildings"] + list(extra_rows),
                      "market_dia": result.get("market_dia"),
                      "sources": result["sources"]}) + "\n"




# --- DPE par LOGEMENT, et non par bâtiment (#287) -----------------------------
#
# Retour d'une professionnelle de la promotion immobilière : « Tu raisonnes en
# DPE par bâtiment. Mais il arrive que les apparts d'une même résidence aient
# des DPE différents. » Elle a raison bien au-delà de son exemple — mesuré sur
# 1 000 diagnostics d'appartements : dès qu'une adresse porte plusieurs DPE,
# DEUX FOIS SUR TROIS les classes diffèrent. Un immeuble montpelliérain en
# aligne douze, de C à G.
#
# Annoncer une classe unique, c'est donc se tromper pour presque tous les
# logements de l'immeuble. Ce bloc dit l'éventail réel.
ADEME_SPREAD_MAX = int(os.environ.get("ADEME_SPREAD_MAX", "3"))   # adresses sondées


def _classe_min_max(classes):
    """Bornes de l'éventail, dans l'ordre A..G et non alphabétique."""
    ordre = "ABCDEFG"
    connues = sorted({c for c in classes if c in ordre}, key=ordre.index)
    return (connues[0], connues[-1]) if connues else (None, None)


async def _dpe_spread(bdnb_id, lon, lat):
    """Les DPE connus aux adresses du bâtiment, et leur dispersion.

    None quand il n'y a rien à dire — zéro ou un seul diagnostic — pour que la
    fiche reste inchangée là où elle a déjà raison, c'est-à-dire sur l'immense
    majorité des maisons.

    Ce qu'on ne prétend PAS : une adresse BAN n'est pas un bâtiment groupe, et
    seuls les logements diagnostiqués figurent. L'éventail est un minimum
    observé, jamais un inventaire — le libellé doit dire « à cette adresse ».
    """
    try:
        rel = await _cached_get_json(
            BDNB_REL_ADR_URL, {"batiment_groupe_id": f"eq.{bdnb_id}", "limit": "200"},
            ttl=86400)
        adresses = [r.get("cle_interop_adr") for r in (rel if isinstance(rel, list) else [])]
        adresses = [a for a in dict.fromkeys(adresses) if a][:ADEME_SPREAD_MAX]
        if not adresses:
            return None

        logements = []
        for ban in adresses:
            d = await _cached_get_json(
                ADEME_DPE_URL,
                {"identifiant_ban_eq": ban, "size": "100",
                 "select": ",".join(("etiquette_dpe", "surface_habitable_logement",
                                     "numero_etage_appartement", "type_batiment",
                                     "type_installation_chauffage", "date_etablissement_dpe"))},
                ttl=7 * 86400)
            for r in (d.get("results") or []):
                if r.get("etiquette_dpe"):
                    logements.append({
                        "classe": r["etiquette_dpe"],
                        "surface_m2": r.get("surface_habitable_logement"),
                        # L'étage n'est renseigné que dans 17 % des cas : on le
                        # porte quand il existe, on n'en fait jamais un axe.
                        "etage": r.get("numero_etage_appartement"),
                        "type": r.get("type_batiment"),
                        "chauffage": r.get("type_installation_chauffage"),
                        "etabli_le": (r.get("date_etablissement_dpe") or "")[:10] or None,
                    })
        if len(logements) < 2:
            return None

        classes = [x["classe"] for x in logements]
        basse, haute = _classe_min_max(classes)
        logements.sort(key=lambda x: -(x.get("surface_m2") or 0))
        return {
            "diagnostics": len(logements),
            "adresses_sondees": len(adresses),
            "classe_min": basse,
            "classe_max": haute,
            "identiques": basse == haute,
            "repartition": {c: classes.count(c) for c in sorted(set(classes))},
            # Assez pour montrer l'éventail sans transformer la fiche en liste.
            "logements": logements[:12],
        }
    except Exception as e:
        log.info("DPE par logement (%s): %s", bdnb_id, e)
        return None


# --- Histoire de la commune (Confinia, #275) ---------------------------------
#
# EcoBuilding répond « qu'est-ce que ce bâtiment ». Confinia répond « dans
# quelle commune il est au sens civil, et comment elle s'appelait avant ». Un
# acte ancien nomme parfois une commune qui n'existe plus : en Haute-Garonne,
# trois ont disparu en dix ans. Router le code mort vers son successeur est ce
# que personne d'autre ne fait — et pour l'immense majorité des bâtiments il ne
# s'est rien passé, ce qui mérite aussi d'être dit, daté et sourcé.
CONFINIA_BASE_URL = os.environ.get("CONFINIA_BASE_URL", "https://api.confinia.io/v1")
CONFINIA_API_KEY = os.environ.get("CONFINIA_API_KEY", "")
# La réponse ne bouge qu'à la ré-ingestion, côté Confinia. Une journée de cache
# est déjà généreuse pour nous, et économe pour eux : `/facts` consomme une
# unité par commune distincte, même sous une clé illimitée.
CONFINIA_TTL = float(os.environ.get("CONFINIA_TTL", str(86400)))

_MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet",
            "août", "septembre", "octobre", "novembre", "décembre")


def _date_fr(iso):
    """« 2019-01-01 » -> « 1ᵉʳ janvier 2019 ». Rend l'entrée telle quelle si ce
    n'est pas une date."""
    if not isinstance(iso, str) or len(iso) < 10:
        return iso
    try:
        a, m, j = int(iso[0:4]), int(iso[5:7]), int(iso[8:10])
        assert 1 <= m <= 12 and 1 <= j <= 31
    except (ValueError, AssertionError):
        return iso
    return f"{'1ᵉʳ' if j == 1 else j} {_MOIS_FR[m - 1]} {a}"


def _reformule_dates(texte):
    """Passe en toutes lettres une date ISO qui traînerait dans une phrase.

    Filet, plus correctif. Confinia servait « au 2026-01-01 » dans sa prose
    française — ce qui n'est pas du français — et l'a corrigé le 2026-08-26,
    dans les deux langues (confinia-core#269). Sur les charges utiles
    d'aujourd'hui cette fonction ne remplace donc rien.

    On la garde parce que ces phrases atterrissent dans une fiche remise à un
    acheteur : si une date ISO réapparaissait un jour dans un enregistrement ou
    une langue qu'on ne surveille pas, mieux vaut qu'elle se lise. Reformuler
    est explicitement permis — « print it, or re-word it, but do not drop it » :
    on change la tournure, jamais le fond.
    """
    import re as _re

    if not isinstance(texte, str):
        return texte
    return _re.sub(r"\d{4}-\d{2}-\d{2}", lambda m: _date_fr(m.group(0)), texte)


async def _nom_d_avant(lon, lat, depuis, nom_actuel):
    """Comment s'appelait CE lieu la veille du changement.

    On interroge le POINT à une date, pas le lignage du code : quand
    Saint-Béat absorbe Lez, le code 31471 s'est appelé « Saint-Béat » —
    c'est vrai du code, et faux pour un bâtiment qui était à Lez. Seul le
    point tranche, et c'est précisément ce que l'API sait faire.

    Vérifié : un point intérieur de l'ancienne Lez rend « Lez » au
    2018-12-31 et « Saint-Béat-Lez » au 2019-01-01.
    """
    if lon is None or lat is None or not isinstance(depuis, str) or len(depuis) < 10:
        return None
    try:
        from datetime import date, timedelta

        veille = (date(int(depuis[0:4]), int(depuis[5:7]), int(depuis[8:10]))
                  - timedelta(days=1)).isoformat()
        avant = await _cached_get_json(
            f"{CONFINIA_BASE_URL}/communes",
            {"lat": round(lat, 6), "lon": round(lon, 6), "at": veille},
            ttl=CONFINIA_TTL)
        props = (avant or {}).get("properties") or {}
        nom = props.get("nom")
        if not nom or nom == nom_actuel:
            return None
        return {"nom": nom, "code": props.get("code"),
                "jusqu_au": depuis, "jusqu_au_fr": _date_fr(depuis)}
    except Exception as e:
        log.info("Confinia nom d'avant (%s,%s au %s): %s", lon, lat, depuis, e)
        return None


async def _commune_history(commune, lon=None, lat=None):
    """La commune au sens civil, ses noms passés, et ce qui borne ces faits.

    Rend None — donc pas de bloc — si la clé manque ou si Confinia se tait :
    la fiche ne doit jamais dépendre d'un tiers.

    Ce qu'on ne jette JAMAIS, parce que c'est ce qui distingue une donnée
    sourcée d'une affirmation : `declined` (pourquoi un fait n'a PAS pu être
    établi — sans quoi on ne distingue pas « jamais calculé » de « pas
    établissable ici »), `limitations` (ce que les faits ne soutiennent pas) et
    `attribution` (la donnée est ouverte, pas anonyme).
    """
    if not commune or not CONFINIA_API_KEY:
        return None
    try:
        entetes = {"X-API-Key": CONFINIA_API_KEY}
        faits = await _cached_get_json(
            f"{CONFINIA_BASE_URL}/communes/{commune}/facts",
            {"country": "FR", "lang": "fr"}, ttl=CONFINIA_TTL, headers=entetes)
        unite = faits.get("unit") or {}
        if not unite.get("code"):
            return None

        actuel = unite.get("name")
        # Un seul nom d'avant, jamais une frise : la fiche dit « Lez jusqu'au
        # 1ᵉʳ janvier 2019 », elle ne déroule pas l'histoire (hors périmètre).
        precedent = await _nom_d_avant(lon, lat, unite.get("valid_from"), actuel)

        return {
            "code": unite.get("code"),
            "nom": actuel,
            "depuis": unite.get("valid_from"),
            "depuis_fr": _date_fr(unite.get("valid_from")),
            "existe_encore": unite.get("valid_to") is None,
            "precedent": precedent,
            "arret_des_donnees": faits.get("as_known_on"),
            "arret_des_donnees_fr": _date_fr(faits.get("as_known_on")),
            "non_etablis": [{"raison": d.get("reason"),
                             "texte": _reformule_dates(d.get("text"))}
                            for d in (faits.get("declined") or [])],
            "limites": [_reformule_dates(x) for x in (faits.get("limitations") or [])],
            "attribution": faits.get("attribution") or [],
        }
    except Exception as e:
        log.warning("Confinia commune %s: %s", commune, e)
        return None


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
from datetime import date, datetime, timedelta, timezone

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
#   sans compte  : 10 fiches/mois
#   compte gratuit: 10 fiches/mois
#   pro          : 10 fiches offertes, puis 0,49 EUR la fiche, plafond 99 EUR
#
# Le plafond anonyme passe de 3 à 10 le 2026-08-26 : à 3, une personne à qui on
# montre le produit était bloquée avant d'avoir compris à quoi il sert — le cas
# s'est présenté lors d'une démonstration à une professionnelle de l'immobilier.
#
# CONSÉQUENCE ASSUMÉE : le compte gratuit donne le MÊME nombre de fiches, donc
# il n'apporte plus rien pour l'instant. Le plafond bas existait justement pour
# provoquer l'inscription (#206). Rétablir un écart demandera de monter le
# compte gratuit, pas de redescendre l'anonyme.
ANON_MONTHLY_REPORTS = int(os.environ.get("ANON_MONTHLY_REPORTS", "10"))
FREE_ACCOUNT_REPORTS = int(os.environ.get("FREE_ACCOUNT_REPORTS", "10"))
# Pricing v4 (PRICING.md) — subscription tiers. The v3 metered grid
# (0,49 €/fiche, plafond 99 €) died with the move to Creem as merchant of
# record: Creem bills fixed recurring amounts only, no metering. Decision
# 2026-08-17: paliers plutôt que packs (subscription-first, cf BUSINESS.md).
# JSON env override so a price fix stays a config change, not a deploy.
PRO_TIERS: dict = json.loads(os.environ.get("PRO_TIERS_JSON", "") or """{
  "s": {"eur": 9,  "fiches": 30,   "label": "Pro S"},
  "m": {"eur": 29, "fiches": 100,  "label": "Pro M"},
  "l": {"eur": 99, "fiches": null, "label": "Pro L"}
}""")
# --- Mobile (MOBILE.md) -------------------------------------------------------
# Paliers SÉPARÉS de PRO_TIERS, volontairement : la promesse mobile n'est pas
# celle du web (le mobile donne des fiches ; le web garde la clé API et
# l'export), et les prix des magasins ne doivent pas apparaître sur /offres.html.
MOBILE_TIERS: dict = json.loads(os.environ.get("MOBILE_TIERS_JSON", "") or """{
  "m30":  {"eur": 4.99,  "fiches": 30,  "label": "Terrain 30"},
  "m150": {"eur": 12.99, "fiches": 150, "label": "Terrain 150"}
}""")
# Fiche à l'unité : un CONSOMMABLE, pas un abonnement. Le particulier prospecte
# par à-coups ; lui vendre un engagement mensuel, c'est de la friction à l'achat
# puis des oublis de résiliation.
MOBILE_UNIT_EUR = float(os.environ.get("MOBILE_UNIT_EUR", "0.99"))
# Fiches offertes par INSTALLATION (à vie, pas par mois) : c'est l'essai.
# Porté de 3 à 10 le 2026-08-21 : à 3, le mur tombait avant que l'usage ait pris
# — on ne teste pas un outil de terrain trois fois. L'objectif de cette étape
# est l'adhésion, pas le revenu (13 abonnés couvrent les frais de l'année).
MOBILE_FREE_REPORTS = int(os.environ.get("MOBILE_FREE_REPORTS", "10"))
# Limite mobile exprimée en BÂTIMENTS DISTINCTS PAR JOUR plutôt qu'en total
# mensuel (demande opérateur 2026-08-22). Deux raisons : « 10 par jour » se
# comprend sans calcul, là où un solde mensuel oblige à se rationner ; et
# retélécharger la MÊME fiche ne doit rien coûter — c'est le même document, et
# le refuser passerait pour une panne.
MOBILE_DAILY_REPORTS = int(os.environ.get("MOBILE_DAILY_REPORTS", "10"))
DAILY_PATH = os.environ.get("DAILY_PATH", "/leads/mobile_daily.json")
# Cache des fiches PDF : 24 h. Une fiche coûte 15 à 45 s de rendu ; la même
# demandée deux fois doit être servie, pas refabriquée.
PDF_CACHE_DIR = os.environ.get("PDF_CACHE_DIR", "/tiles/pdf")
PDF_CACHE_TTL = float(os.environ.get("PDF_CACHE_TTL", str(24 * 3600)))
# Le quota anonyme du web se compte par IP — inutilisable sur réseau mobile, où
# des milliers d'abonnés partagent une adresse : les fiches offertes d'un
# utilisateur seraient consommées par des inconnus. On compte donc par
# identifiant d'installation, fourni par l'app dans cet en-tête. Ce n'est PAS
# de l'authentification (réinstaller remet le compteur à zéro) : l'enjeu vaut
# 0,99 €, et un contrôle plus dur coûterait plus en adhésion qu'il ne
# rapporterait.
DEVICE_HEADER = "x-install-id"
# Bêta-testeurs NOMMÉMENT identifiés, exemptés de quota le temps de recueillir
# leurs retours. Une liste d'identifiants d'installation, pas un interrupteur
# global : ouvrir le quota à tout le monde reviendrait à offrir le produit, et
# un réglage temporaire de ce genre s'oublie. Format : identifiants séparés par
# des virgules (l'app affiche le sien quand on touche le numéro de version).
MOBILE_BETA_IDS = {x.strip() for x in
                   os.environ.get("MOBILE_BETA_IDS", "").split(",") if x.strip()}
CREDITS_PATH = os.environ.get("CREDITS_PATH", "/leads/credits.json")

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


def _usage_total(key_id: str) -> int:
    """Crédits consommés depuis TOUJOURS par ce seau, tous mois confondus.

    Les fiches offertes du mobile sont un essai unique, pas un robinet mensuel :
    elles se comptent donc sur la durée de vie de l'installation."""
    return sum(int(m.get(key_id, 0)) for m in _usage_load().values()
               if isinstance(m, dict))


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


def _tier_for(fiches: int) -> str:
    """Smallest tier whose allowance covers this monthly volume (v4)."""
    for k in ("s", "m", "l"):
        q = PRO_TIERS[k]["fiches"]
        if q is None or fiches <= q:
            return k
    return "l"


def _usage_cost(fiches: int) -> dict:
    """Pricing v4: fixed tiers, no metering. The 'cost' of a volume is the
    price of the smallest tier that covers it — that is what the simulator
    and /v1/pricing answer."""
    tier = _tier_for(fiches)
    return {
        "fiches": fiches,
        "credits": fiches,                  # kept: same number, one unit
        "recommended_tier": tier,
        "cost_eur": 0.0 if fiches <= FREE_ACCOUNT_REPORTS else float(PRO_TIERS[tier]["eur"]),
        "tiers": {k: {"eur": v["eur"], "fiches_month": v["fiches"], "label": v["label"]}
                  for k, v in PRO_TIERS.items()},
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


def _device_bucket(request: Request) -> str | None:
    """Seau d'usage d'une INSTALLATION de l'app mobile, ou None hors mobile."""
    dev = (request.headers.get(DEVICE_HEADER) or "").strip()
    if not dev or len(dev) < 8 or len(dev) > 128:
        return None
    return "dev:" + hashlib.sha256(dev.encode()).hexdigest()[:16]


def _credits_load() -> dict:
    try:
        with open(CREDITS_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _credits_get(bucket: str) -> dict:
    """{"units": n, "tier": "m30"|None, "until": iso|None} pour un seau."""
    return _credits_load().get(bucket) or {}


def _credits_add(bucket: str, units: int = 0, **extra) -> dict:
    """Crédite des fiches à l'unité et/ou pose un palier d'abonnement.

    Les deux coexistent : un consommable acheté ne disparaît pas quand un
    abonnement se termine, et il ne confère aucun statut.
    """
    data = _credits_load()
    entry = data.get(bucket) or {"units": 0}
    entry["units"] = int(entry.get("units", 0)) + units
    entry.update({k: v for k, v in extra.items() if v is not None})
    entry["updated"] = datetime.now(timezone.utc).isoformat()
    data[bucket] = entry
    try:
        os.makedirs(os.path.dirname(CREDITS_PATH), exist_ok=True)
        tmp = CREDITS_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CREDITS_PATH)
    except OSError as e:
        log.warning("crédits non écrits (%s): %s", bucket, e)
    return entry


def _quota_reset(month: bool = False) -> str:
    """Instant de remise à zéro du quota, en ISO 8601 avec fuseau.

    Le client affiche une DURÉE (« dans 3 heures ») : « demain » est inutile à
    23 h 50, et faux pour qui vient de changer de fuseau."""
    now = datetime.now().astimezone()
    if month:
        nxt = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
    else:
        nxt = now + timedelta(days=1)
    return nxt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _daily_load() -> dict:
    try:
        with open(DAILY_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _daily_seen(bucket: str) -> list:
    """Bâtiments déjà servis à cette installation AUJOURD'HUI."""
    e = _daily_load().get(bucket) or {}
    return e.get("ids", []) if e.get("day") == date.today().isoformat() else []


def _daily_add(bucket: str, subject: str) -> None:
    data = _daily_load()
    today = date.today().isoformat()
    e = data.get(bucket) or {}
    if e.get("day") != today:
        e = {"day": today, "ids": []}
    if subject not in e["ids"]:
        e["ids"].append(subject)
    data[bucket] = e
    try:
        os.makedirs(os.path.dirname(DAILY_PATH), exist_ok=True)
        tmp = DAILY_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, DAILY_PATH)
    except OSError as e2:
        log.warning("journal quotidien non écrit (%s): %s", bucket, e2)


def _mobile_gate(request: Request, endpoint: str, subject: str | None = None) -> str | None:
    """Échelle mobile (MOBILE.md §5.2) : 3 fiches offertes par installation,
    puis fiches à l'unité et/ou abonnement. Renvoie None si l'appel ne vient
    pas de l'app (pas d'en-tête d'installation)."""
    bucket = _device_bucket(request)
    if bucket is None:
        return None
    if endpoint != "report":
        return "mobile"
    # Bêta-testeur identifié : aucun quota, aucun mur. Son retour vaut plus que
    # la vente, et un blocage en pleine démonstration devant un client serait
    # rédhibitoire.
    if (request.headers.get(DEVICE_HEADER) or "").strip() in MOBILE_BETA_IDS:
        _usage_add(bucket, CREDIT_COST["report"])
        return "mobile_beta"
    ent = _credits_get(bucket)
    tier = ent.get("tier")

    # 0. Fiche DÉJÀ obtenue aujourd'hui : gratuite et non décomptée. C'est le
    #    même document ; le refuser au motif d'un quota passerait pour une panne.
    seen = _daily_seen(bucket)
    if subject and subject in seen:
        return "mobile_repeat"

    # 1. abonnement en cours : quota mensuel du palier
    if tier and tier in MOBILE_TIERS:
        quota = MOBILE_TIERS[tier]["fiches"]
        used_month = (_usage_load().get(_month_key()) or {}).get(bucket, 0) \
            // CREDIT_COST["report"]
        if quota is None or used_month < quota:
            _usage_add(bucket, CREDIT_COST["report"])
            return "mobile_sub"
        nxt = "m150" if tier == "m30" else None
        raise HTTPException(429, f"{MOBILE_TIERS[tier]['label']} : {quota} fiches "
                            "ce mois-ci, quota atteint. "
                            + (f"Passez à {MOBILE_TIERS[nxt]['label']} "
                               f"({MOBILE_TIERS[nxt]['eur']:.2f} €/mois)."
                               if nxt else f"Écrivez-nous : {SUPPORT_EMAIL}"))

    # 2. quota du jour, en bâtiments DISTINCTS
    if len(seen) < MOBILE_DAILY_REPORTS:
        if subject:
            _daily_add(bucket, subject)
        _usage_add(bucket, CREDIT_COST["report"])
        return "mobile_free"

    # 3. fiches achetées à l'unité
    if int(ent.get("units", 0)) > 0:
        _credits_add(bucket, units=-1)
        if subject:
            _daily_add(bucket, subject)
        _usage_add(bucket, CREDIT_COST["report"])
        return "mobile_unit"

    raise HTTPException(429, f"Limite du jour atteinte : {MOBILE_DAILY_REPORTS} "
                        "bâtiments différents. Elle se remet à zéro demain, et "
                        "les fiches déjà obtenues aujourd'hui restent accessibles.")


def _seau_ip(request: Request) -> str:
    """Seau de comptage d'une adresse IP. Nommé une fois : la règle du document
    déjà servi et le décompte anonyme DOIVENT viser le même seau, sans quoi
    l'une ne voit pas ce que l'autre a enregistré."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "?"
    return "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]


def _quota_gate(request: Request, endpoint: str, subject: str | None = None):
    """Tiered access (#206), subscription-first ladder:
      anonymous      -> ANON_MONTHLY_REPORTS fiches/month per IP
      free account   -> FREE_ACCOUNT_REPORTS fiches/month (API key)
      pro subscriber -> metered, hard-capped, never blocked
    Returns the caller kind for metrics."""
    # L'app mobile s'identifie par son installation, sans compte ni clé : sa
    # propre échelle passe donc AVANT (voir _mobile_gate).
    mobile = _mobile_gate(request, endpoint, subject)
    if mobile:
        return mobile
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
                    f"Les offres Pro démarrent à {PRO_TIERS['s']['eur']:.0f} €/mois "
                    f"({PRO_TIERS['s']['fiches']} fiches) : "
                    f"https://ecobuilding.confinia.io/offres.html — une question ? {SUPPORT_EMAIL}")
        _meter_call(request, endpoint, key)
        return "key"
    sub = _bearer_sub(request)
    if sub:
        # Signed-in browser user: same ladder as a key holder, no key needed.
        uid = "kc:" + hashlib.sha256(sub.encode()).hexdigest()[:14]
        if _pro_active(sub):
            tier = _pro_tier(sub) or "s"
            quota = PRO_TIERS[tier]["fiches"]        # None = illimité (fair-use)
            if endpoint == "report":
                if quota is not None:
                    used = (_usage_load().get(_month_key()) or {}).get(uid, 0) \
                           // CREDIT_COST["report"]
                    if used >= quota:
                        nxt = {"s": "m", "m": "l"}.get(tier)
                        raise HTTPException(
                            429,
                            f"{PRO_TIERS[tier]['label']} : {quota} fiches par mois atteintes. "
                            + (f"Passez à {PRO_TIERS[nxt]['label']} "
                               f"({PRO_TIERS[nxt]['eur']:.0f} €/mois) : "
                               "https://ecobuilding.confinia.io/offres.html"
                               if nxt else "")
                            + f" — une question ? {SUPPORT_EMAIL}")
                _usage_add(uid, CREDIT_COST["report"])
                M_CREDITS.add(CREDIT_COST["report"], {"endpoint": endpoint, "plan": "pro"})
                if PAYMENT_PROVIDER == "polar":
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
                    f"Les offres Pro démarrent à {PRO_TIERS['s']['eur']:.0f} €/mois "
                    f"({PRO_TIERS['s']['fiches']} fiches) : "
                    f"https://ecobuilding.confinia.io/offres.html — une question ? {SUPPORT_EMAIL}")
            _usage_add(uid, CREDIT_COST["report"])
        return "user_free"
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "?"
    if endpoint == "report":
        # Fiche DÉJÀ servie à cette adresse aujourd'hui : gratuite et non
        # décomptée — comme sur mobile (voir _mobile_gate).
        #
        # La règle ne vaut QUE pour un appel anonyme, et c'est délibéré. Le web
        # télécharge la fiche avec son jeton puis fait naviguer l'onglet vers
        # la même URL : cette seconde requête arrive sans autorisation, et
        # c'est elle qu'il faut épargner. Un appelant IDENTIFIÉ, lui, est
        # toujours décompté sur son propre compte — sinon l'activité d'un
        # collègue derrière la même sortie internet offrirait des fiches à un
        # autre, ce qu'un parcours e2e a montré en partageant l'IP de la VM.
        if subject and subject in _daily_seen(_seau_ip(request)):
            return "web_repeat"
        # Monthly, not daily: a daily cap of 20 was never reached, so nobody
        # ever created an account (#206).
        bucket = _seau_ip(request)
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
<p><strong>Déjà un compte ?</strong> Cette page ne vous a pas reconnu :
connectez-vous, votre quota est celui de votre offre.</p>
<p><a class="btn p" href="https://ecobuilding.confinia.io/?login=1">Se connecter</a>
<a class="btn s" href="https://ecobuilding.confinia.io/?signup=1">Créer un compte gratuit</a></p>
<p>Sans compte comme avec un compte gratuit, {ANON_MONTHLY_REPORTS} fiches par
mois sont offertes. Le compte ajoute :</p>
<ul>
  <li>Une clé API pour vos propres outils</li>
  <li>Le suivi de votre consommation</li>
  <li>Un quota qui vous suit, quel que soit l'appareil ou le réseau</li>
</ul>
<p><a class="btn s" href="https://ecobuilding.confinia.io/offres.html">Voir les offres Pro</a></p>
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
    """Current-month usage and cost for the calling API key.

    Pricing v4 : paliers d'abonnement. Le coût d'un abonné est le prix de son
    palier ; l'échelle des fiches restantes est montrée pour tous les plans
    quota-limités (gratuit, Pro S, Pro M)."""
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    sub = _bearer_sub(request)
    tier = None
    if key and key in _load_keys():
        bucket = hashlib.sha256(key.encode()).hexdigest()[:16]
        plan = _key_plans().get(key, "free")
        if plan == "pro":
            tier = _pro_tier(_key_owners().get(key)) or "s"
    elif sub:
        bucket = "kc:" + hashlib.sha256(sub.encode()).hexdigest()[:14]
        plan = "pro" if _pro_active(sub) else "free"
        if plan == "pro":
            tier = _pro_tier(sub) or "s"
    else:
        raise HTTPException(401, "Clé API (X-API-Key) ou session requise")
    month = _month_key()
    credits = (_usage_load().get(month) or {}).get(bucket, 0)
    used = credits // CREDIT_COST["report"]
    body = {"month": month, "plan": plan, "credit_costs": CREDIT_COST,
            **_usage_cost(credits)}
    if plan == "pro":
        quota = PRO_TIERS[tier]["fiches"]
        body |= {"tier": tier, "tier_label": PRO_TIERS[tier]["label"],
                 "cost_eur": float(PRO_TIERS[tier]["eur"]),
                 "reports_used": used, "reports_included": quota,
                 "reports_left": (None if quota is None
                                  else max(0, quota - used))}
    else:
        # A free account owes nothing: show the allowance, not a bill.
        body |= {"cost_eur": 0.0, "reports_used": used,
                 "reports_included": FREE_ACCOUNT_REPORTS,
                 "reports_left": max(0, FREE_ACCOUNT_REPORTS - used)}
    return body


@app.get("/v1/quota", tags=["meta"])
async def quota_preflight(request: Request):
    """Pré-vol du quota fiches — LECTURE SEULE, ne consomme rien.

    Demande opérateur (2026-08-18) : le message « Limite atteinte » arrivait
    après tout le cérémonial de génération ; le client doit pouvoir bloquer le
    déclenchement AVANT. Mêmes seaux que _quota_gate, sans incrément."""
    key = request.headers.get("x-api-key") or request.query_params.get("key")
    sub = _bearer_sub(request)
    tier = None
    # L'app mobile n'a ni clé ni session : elle s'identifie par son
    # installation. Sans cette branche, elle recevait le quota ANONYME par IP —
    # donc un chiffre faux, et sur réseau mobile un chiffre partagé avec des
    # milliers d'inconnus.
    device = _device_bucket(request)
    if device is not None:
        ent = _credits_get(device)
        mob_tier = ent.get("tier")
        beta = (request.headers.get(DEVICE_HEADER) or "").strip() in MOBILE_BETA_IDS
        if mob_tier and mob_tier in MOBILE_TIERS:
            included = MOBILE_TIERS[mob_tier]["fiches"]
            used = (_usage_load().get(_month_key()) or {}).get(device, 0) // CREDIT_COST["report"]
            plan = "mobile_sub"
        else:
            # Limite du JOUR, en bâtiments distincts.
            included = None if beta else MOBILE_DAILY_REPORTS
            used = len(_daily_seen(device))
            plan = "mobile_beta" if beta else "mobile_free"
        return {"plan": plan, "tier": mob_tier, "reports_used": used,
                "reports_included": included,
                "reports_left": None if included is None else max(0, included - used),
                # Fiches achetées à l'unité : elles survivent au quota mensuel.
                "units": int(ent.get("units", 0)),
                # « par jour » plutôt qu'un solde mensuel : le client doit
                # pouvoir le DIRE, pas seulement afficher un nombre.
                "period": "month" if mob_tier else "day",
                # Instant EXACT de réouverture. « Demain » ne dit rien à 23 h 50 ;
                # le client peut en tirer « dans 10 minutes ». Le serveur seul
                # connaît la borne, c'est donc lui qui la donne.
                "resets_at": _quota_reset(month=bool(mob_tier)),
                # Bâtiments déjà obtenus aujourd'hui : les redemander est libre.
                "free_again": _daily_seen(device)}
    if key and key in _load_keys():
        plan = _key_plans().get(key, "free")
        bucket = hashlib.sha256(key.encode()).hexdigest()[:16]
        if plan == "pro":
            tier = _pro_tier(_key_owners().get(key)) or "s"
    elif sub:
        plan = "pro" if _pro_active(sub) else "free"
        bucket = "kc:" + hashlib.sha256(sub.encode()).hexdigest()[:14]
        if plan == "pro":
            tier = _pro_tier(sub) or "s"
    else:
        plan = "anonymous"
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or "?"
        bucket = "ip:" + hashlib.sha256(ip.encode()).hexdigest()[:16]
    used = (_usage_load().get(_month_key()) or {}).get(bucket, 0) // CREDIT_COST["report"]
    included = (PRO_TIERS[tier]["fiches"] if tier
                else FREE_ACCOUNT_REPORTS if plan == "free"
                else ANON_MONTHLY_REPORTS)
    return {"plan": plan, "tier": tier, "reports_used": used,
            "reports_included": included,
            "reports_left": None if included is None else max(0, included - used)}


@app.get("/v1/config", tags=["meta"])
async def config():
    """Public runtime facts the UI must not guess (#221): which payment
    environment is wired. A SANDBOX payment mode must be visible in the UI so
    nobody mistakes a test checkout for a real one."""
    if PAYMENT_PROVIDER == "creem":
        mode = "sandbox" if "test-api" in CREEM_API_BASE else "live"
    elif PAYMENT_PROVIDER == "polar":
        mode = "sandbox" if "sandbox" in POLAR_BASE_URL else "live"
    else:
        mode = "disabled"
    return {"payment_mode": mode,
            "payment_provider": PAYMENT_PROVIDER,
            "pro_tiers": {k: {"eur": v["eur"], "fiches_month": v["fiches"],
                              "label": v["label"]} for k, v in PRO_TIERS.items()},
            "free_tiers": {"anonymous_reports_month": ANON_MONTHLY_REPORTS,
                           "free_account_reports_month": FREE_ACCOUNT_REPORTS},
            # Intégrations dont la présence dépend d'un secret, DÉCLARÉES ici.
            #
            # Le bloc commune disparaît quand Confinia est injoignable — c'est
            # voulu, la fiche ne doit jamais dépendre d'un tiers. Mais ce
            # silence masquait sa propre panne : le conteneur ne joignait pas
            # l'API, et le contrôle public passait quand même, puisqu'il
            # acceptait les deux réponses. En déclarant ce qui EST configuré,
            # on rend l'écart détectable : configuré et absent = panne.
            "integrations": {"commune_history": bool(CONFINIA_API_KEY)},
            # Offre MOBILE, distincte des paliers web (MOBILE.md §5.2) : l'app
            # lit ses prix ici plutôt que de les écrire en dur, comme le web.
            "mobile": {"tiers": {k: {"eur": v["eur"], "fiches_month": v["fiches"],
                                     "label": v["label"]} for k, v in MOBILE_TIERS.items()},
                       "unit_eur": MOBILE_UNIT_EUR,
                       "free_reports": MOBILE_FREE_REPORTS},
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

# --- Creem (Merchant of Record, EU/Estonie) — décision 2026-08-17 ------------
# Souveraineté : le client veut un MoR incorporé dans l'UE qui émet la facture
# (report de la création d'entreprise). SANDBOX UNIQUEMENT pour l'instant :
# une clé creem_test_ pointe d'elle-même sur l'environnement de test isolé.
CREEM_API_KEY = os.environ.get("CREEM_API_KEY", "")
CREEM_API_BASE = (os.environ.get("CREEM_API_BASE")
                  or ("https://test-api.creem.io/v1" if CREEM_API_KEY.startswith("creem_test_")
                      else "https://api.creem.io/v1")).rstrip("/")
CREEM_WEBHOOK_SECRET = os.environ.get("CREEM_WEBHOOK_SECRET", "")
# tier -> product id Creem, créés par deploy/creem-setup.sh
CREEM_PRODUCTS: dict = json.loads(os.environ.get("CREEM_PRODUCTS_JSON", "") or "{}")
# Un seul fournisseur actif à la fois ; Creem gagne s'il est configuré.
PAYMENT_PROVIDER = ("creem" if CREEM_API_KEY
                    else "polar" if os.environ.get("POLAR_ACCESS_TOKEN")
                    else "none")
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


def _pro_tier(ext_id: str | None) -> str | None:
    """Palier actif ("s"/"m"/"l") d'un abonné, None sinon. Un enregistrement
    actif sans palier (donnée d'avant la v4) est traité comme "s" : ne jamais
    accorder plus que ce qui a été payé par défaut."""
    if not ext_id:
        return None
    rec = _pro_load().get(ext_id, {})
    if rec.get("status") == "active":
        t = rec.get("tier")
        return t if t in PRO_TIERS else "s"
    return None


def _creem_find_subscription(email: str) -> dict | None:
    """L'abonnement Creem ACTIF d'un e-mail, ou None. Creem ne sait pas
    filtrer par external_id : on remonte e-mail -> customer -> abonnements.
    /subscriptions/search refuse tout filtre customer_id (400 « property
    customer_id should not exist ») : la forme qui marche est la ressource
    imbriquée — vérifié contre test-api le 2026-08-18."""
    if not (CREEM_API_KEY and email):
        return None
    with httpx.Client(timeout=6.0, headers={"x-api-key": CREEM_API_KEY}) as c:
        r = c.get(f"{CREEM_API_BASE}/customers", params={"email": email})
        r.raise_for_status()
        cust = r.json() or {}
        cust_id = cust.get("id") or ((cust.get("items") or [{}])[0].get("id"))
        if not cust_id:
            return None
        r = c.get(f"{CREEM_API_BASE}/customers/{cust_id}/subscriptions")
        r.raise_for_status()
        items = (r.json().get("items") if isinstance(r.json(), dict) else r.json()) or []
        return next((s for s in items if s.get("status") == "active"), None)


def _creem_tier_of(sub: dict) -> str:
    prod = (sub.get("product") or {}).get("id") or sub.get("product_id")
    return next((t for t, pid in CREEM_PRODUCTS.items() if pid == prod), "s")


def _creem_subscription_active(ext_id: str) -> bool:
    """Réconciliation Creem : le webhook est une optimisation, pas une
    dépendance (même philosophie que #228 côté Polar). Échec = False : un
    incident fournisseur ne doit jamais accorder l'accès."""
    email = _pro_load().get(ext_id, {}).get("email")
    try:
        sub = _creem_find_subscription(email)
        if sub:
            _pro_set(ext_id, True, source="reconciled", tier=_creem_tier_of(sub),
                     subscription_id=sub.get("id"))
            return True
    except Exception as e:
        log.warning("Creem subscription check failed for %s: %s", ext_id, e)
    return False


def _pro_active(ext_id: str | None) -> bool:
    if not ext_id:
        return False
    if _pro_load().get(ext_id, {}).get("status") == "active":
        return True
    # Pas actif localement : réconcilier avec le fournisseur (le webhook a pu
    # ne jamais arriver).
    if PAYMENT_PROVIDER == "creem":
        now = time.monotonic()
        hit = _pro_check.get(ext_id)
        if hit and now - hit[0] < PRO_RECHECK_TTL:
            return hit[1]
        active = _creem_subscription_active(ext_id)
        _pro_check[ext_id] = (now, active)
        return active
    return _polar_subscription_active(ext_id)


def _sub_external_id(data: dict) -> str | None:
    """Extract our Keycloak sub from a Polar subscription/order payload."""
    cust = data.get("customer") or {}
    return (cust.get("external_id")
            or data.get("customer_external_id")
            or (data.get("metadata") or {}).get("kc_sub"))


@app.get("/v1/pro/checkout", tags=["account"])
async def pro_checkout(request: Request,
                       tier: str = Query("s", pattern="^[sml]$",
                                         description="Palier v4 : s, m ou l")):
    """Start a hosted checkout for a pro tier (signed-in users). Returns the
    provider-hosted checkout URL as JSON (the frontend redirects to it); the
    user's Keycloak sub travels in the metadata so the webhook (or the
    reconciliation) can upgrade the right account."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    email = claims.get("email") or claims.get("preferred_username")
    if PAYMENT_PROVIDER == "creem":
        # Déjà abonné : un checkout créerait un DEUXIÈME abonnement qui
        # s'additionne — le changement de palier passe par /v1/pro/upgrade
        # (prorata géré par Creem). 409 pour que le client route vers lui.
        if _pro_active(claims.get("sub")):
            raise HTTPException(409, "Déjà abonné — utilisez /v1/pro/upgrade")
        product = CREEM_PRODUCTS.get(tier)
        if not product:
            raise HTTPException(503, "Pro plan not configured")
        try:
            resp = await _client.post(
                f"{CREEM_API_BASE}/checkouts",
                # Creem refuse un customer_email à plat (« property
                # customer_email should not exist ») : l'e-mail voyage dans
                # l'objet customer — vérifié contre test-api le 2026-08-17.
                json={"product_id": product,
                      "success_url": f"{PUBLIC_BASE_URL}/?pro=success",
                      "customer": {"email": email},
                      "metadata": {"kc_sub": claims.get("sub"), "tier": tier}},
                headers={"x-api-key": CREEM_API_KEY})
            resp.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("Creem checkout failed: %s", e)
            raise HTTPException(502, "Checkout provider error")
        # L'e-mail est la clé de réconciliation côté Creem (pas d'external_id
        # chez eux) : on le note tout de suite, sans activer quoi que ce soit.
        _pro_set(claims.get("sub"), False, email=email, tier=tier, source="checkout")
        M_PRO.add(1, {"event": "checkout", "provider": "creem", "tier": tier})
        body = resp.json()
        return {"url": body.get("checkout_url") or body.get("url"),
                "checkout_id": body.get("id")}
    if not (POLAR_ACCESS_TOKEN and POLAR_PRODUCT_ID):
        raise HTTPException(503, "Pro plan not configured")
    payload = {
        "products": [POLAR_PRODUCT_ID],
        "success_url": f"{PUBLIC_BASE_URL}/?pro=success",
        "customer_email": email,
        "customer_external_id": claims.get("sub"),
        # Prefilled billing country: the product is FR-only today (#118 will
        # revisit), and every field removed from the hosted checkout is one
        # less place to abandon. The customer can still change it on the page.
        "customer_billing_address": {"country": "FR"},
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


@app.post("/v1/pro/upgrade", tags=["account"])
async def pro_upgrade(request: Request,
                      tier: str = Query(..., pattern="^[sml]$")):
    """Changer de palier (montée OU descente) : upgrade de l'abonnement Creem
    EXISTANT, prorata immédiat géré par Creem — jamais un second checkout."""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    try:
        claims = _decode_token(auth[7:].strip())
    except Exception:
        raise HTTPException(401, "Invalid token")
    sub_id_kc = claims.get("sub")
    email = claims.get("email") or claims.get("preferred_username")
    target = CREEM_PRODUCTS.get(tier)
    if not (PAYMENT_PROVIDER == "creem" and target):
        raise HTTPException(503, "Changement d'offre indisponible")
    try:
        cur = _creem_find_subscription(email)
    except Exception as e:
        log.warning("Creem lookup failed for upgrade (%s): %s", email, e)
        raise HTTPException(502, "Fournisseur de paiement injoignable")
    if not cur:
        raise HTTPException(409, "Aucun abonnement actif — utilisez le checkout")
    if _creem_tier_of(cur) == tier:
        raise HTTPException(409, "Vous êtes déjà sur ce palier")
    try:
        resp = await _client.post(
            f"{CREEM_API_BASE}/subscriptions/{cur['id']}/upgrade",
            # `update_behavior` est facultatif et vaut « proration-charge-immediately »
            # par défaut — on l'écrit quand même : c'est une décision de
            # facturation, elle doit se lire dans le code et non dépendre d'un
            # défaut qui peut changer. `proration-charge` est d'ailleurs déjà
            # déprécié chez eux.
            json={"product_id": target,
                  "update_behavior": "proration-charge-immediately"},
            headers={"x-api-key": CREEM_API_KEY})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        # Le CORPS de la réponse, pas seulement le code.
        #
        # Ce bloc n'a longtemps journalisé que « 403 Client error », et il a
        # fallu des jours pour découvrir que le corps distinguait un vrai refus
        # de portée (`Forbidden` avec message) d'une erreur serveur déguisée
        # (`Bad Request` sans message). Se priver du corps, c'est se priver du
        # seul endroit où le fournisseur explique.
        corps = getattr(getattr(e, "response", None), "text", "")
        log.warning("Creem upgrade failed (%s -> %s): %s | %s",
                    _creem_tier_of(cur), tier, e, corps[:500])
        raise HTTPException(502, "Échec du changement d'offre")
    _pro_set(sub_id_kc, True, tier=tier, subscription_id=cur["id"], source="upgrade")
    M_PRO.add(1, {"event": "upgrade", "tier": tier})
    return {"tier": tier, "label": PRO_TIERS[tier]["label"]}


@app.post("/v1/pro/webhook", tags=["account"], status_code=202)
async def pro_webhook(request: Request):
    """Webhook du fournisseur de paiement, signé. Bascule l'abonné :
    actif -> pro (avec palier), annulé/impayé -> free.
    Creem : en-tête `creem-signature` = HMAC-SHA256 hex du corps brut.
    Polar : Standard Webhooks (conservé tant que la bascule n'est pas actée
    en production)."""
    body = await request.body()
    if PAYMENT_PROVIDER == "creem":
        if not CREEM_WEBHOOK_SECRET:
            raise HTTPException(503, "Webhook not configured")
        import hmac as _hmac
        expected = _hmac.new(CREEM_WEBHOOK_SECRET.encode(), body,
                             hashlib.sha256).hexdigest()
        got = request.headers.get("creem-signature", "")
        if not _hmac.compare_digest(expected, got):
            M_PRO.add(1, {"event": "webhook_rejected", "provider": "creem"})
            raise HTTPException(401, "Invalid signature")
        event = json.loads(body)
        etype = event.get("eventType") or event.get("type", "")
        data = event.get("object") or event.get("data") or {}
        meta = data.get("metadata") or {}
        ext_id = meta.get("kc_sub")
        prod = (data.get("product") or {}).get("id") or data.get("product_id")
        tier = (meta.get("tier")
                or next((t for t, pid in CREEM_PRODUCTS.items() if pid == prod), None)
                or "s")
        if etype in ("checkout.completed", "subscription.active", "subscription.paid"):
            _pro_set(ext_id, True, tier=tier, subscription_id=data.get("id"),
                     product_id=prod, source="webhook")
        elif etype in ("subscription.canceled", "subscription.past_due", "subscription.expired"):
            _pro_set(ext_id, False, subscription_id=data.get("id"), source="webhook")
        M_PRO.add(1, {"event": "webhook", "provider": "creem", "type": etype})
        return {"received": True, "type": etype}
    if not POLAR_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook not configured")
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

    _quota_gate(request, "report", subject=bdnb_id)
    # Le document servi est enregistré pour CETTE adresse, quel que soit le
    # plan — sans quoi la seconde requête n'en profite pas.
    #
    # Le web télécharge la fiche avec son jeton, puis fait NAVIGUER l'onglet
    # vers la même URL pour que le nom de fichier du serveur survive (#282) :
    # une navigation ne porte aucun en-tête d'autorisation, donc cette seconde
    # requête arrive anonyme. Un abonné se retrouvait bloqué par le quota des
    # visiteurs sur sa propre fiche, et lisait « limite sans compte » alors
    # qu'il paie.
    _daily_add(_seau_ip(request), bdnb_id)
    # Cache 24 h de la fiche elle-même : redemander le MÊME document ne doit ni
    # relancer 15 à 45 s de rendu, ni consommer le quota amont. La clé inclut
    # l'adresse cherchée, qui TITRE la fiche (#146) — deux titres différents
    # sont deux documents différents.
    pdf_key = hashlib.sha256(
        f"{bdnb_id}|{address or ''}|{round(lon, 4) if lon else ''}|"
        f"{round(lat, 4) if lat else ''}".encode()).hexdigest()[:24]
    pdf_path = os.path.join(PDF_CACHE_DIR, pdf_key + ".pdf")
    cached = _tile_read(pdf_path, PDF_CACHE_TTL)
    if cached:
        M_CACHE.add(1, {"result": "hit_pdf"})
        # Le nom voyage dans un fichier voisin : sur un cache chaud, l'adresse
        # n'a pas encore été chargée, et re-générer la fiche pour la connaître
        # coûterait les quinze secondes qu'on vient justement d'économiser.
        nom = (_tile_read(pdf_path + ".nom", None) or b"").decode() \
            or _nom_de_fiche(None, bdnb_id)
        return Response(cached, media_type="application/pdf",
                        headers={"Content-Disposition": _disposition(nom)})
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
    # Les deux vues en parallèle : le rendu 3D et la photo aérienne se
    # complètent, et les demander l'une après l'autre doublerait l'attente.
    map_img, aerial = await asyncio.gather(
        _building_map_png(q.get("lon"), q.get("lat"), bdnb_id),
        _aerial_view(bdnb_id, q.get("lon"), q.get("lat")))
    pdf = build_report_pdf(data, photos=photos, map_img=map_img,
                           aerial_img=aerial.get("image"),
                           aerial_parcels=aerial.get("parcels"),
                           aerial_outline=aerial.get("outline"))
    _tile_write(pdf_path, pdf)          # même écriture atomique que les tuiles
    nom = _nom_de_fiche(q.get("address") or (data["buildings"][0] or {}).get("address"),
                        bdnb_id)
    _tile_write(pdf_path + ".nom", nom.encode())
    M_REPORTS.add(1, {"has_dpe": str(bool((data["buildings"][0].get("energy") or {}).get("dpe_class"))).lower()})
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _disposition(nom)},
    )


_INTERDITS_FICHIER = str.maketrans({c: None for c in '/\\:*?"<>|\r\n\t'})


def _nom_de_fiche(adresse, bdnb_id):
    """Nom du fichier PDF, tel qu'il apparaîtra dans les pièces jointes.

    La fiche s'appelait « ecobuilding-bdnb-bg-6ZEE-2XTC-6ZUK.pdf » : un
    identifiant qui ne veut rien dire hors de ce dépôt. Or ce document se
    classe, se transfère à un notaire, à un confrère, à un client — il doit
    porter le nom sous lequel le bien existe pour tout le monde : son adresse.

    Sans adresse connue, on garde l'identifiant plutôt que d'inventer.
    """
    base = (adresse or "").translate(_INTERDITS_FICHIER).strip()
    base = " ".join(base.split())          # espaces multiples, sauts de ligne
    if not base:
        base = bdnb_id
    if len(base) > 110:                    # les systèmes de fichiers plafonnent
        base = base[:110].rsplit(" ", 1)[0]
    return f"EcoBuilding — {base}.pdf"


def _disposition(nom):
    """En-tête `Content-Disposition` acceptant les accents.

    `filename=` ne transporte que de l'ASCII : « rue de l'Aiguillerie » y perd
    ses accents ou casse l'en-tête. `filename*` (RFC 5987) porte l'UTF-8, et
    l'ASCII reste là pour les clients anciens.
    """
    import urllib.parse

    ascii_ = " ".join(nom.encode("ascii", "ignore").decode().split()) \
        or "EcoBuilding.pdf"
    return (f'inline; filename="{ascii_}"; '
            f"filename*=UTF-8''{urllib.parse.quote(nom)}")


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


COMMONS_URL = "https://commons.wikimedia.org/w/api.php"


async def _commons_photos(lon: float, lat: float, radius_m: int = 120) -> list:
    """Photos géolocalisées de Wikimedia Commons autour du point.

    Panoramax couvre bien les villes et mal le reste : sur beaucoup d'adresses,
    la fiche n'affiche aucune image, alors qu'un acheteur veut d'abord VOIR
    l'environnement du bien (#200). Commons complète — sans clé, sans compte —
    et couvre en particulier les bâtiments remarquables, églises, mairies,
    monuments, dont un quartier tire une bonne part de son caractère.

    Chaque image porte sa licence et son auteur : l'attribution est une
    OBLIGATION des licences CC-BY-SA, pas une politesse.
    """
    try:
        data = await _cached_get_json(COMMONS_URL, {
            "action": "query", "generator": "geosearch",
            "ggscoord": f"{lat}|{lon}", "ggsradius": str(radius_m),
            "ggslimit": "6", "ggsnamespace": "6",
            "prop": "imageinfo", "iiprop": "url|extmetadata",
            "iiurlwidth": "640", "format": "json",
        }, ttl=86400)
    except Exception as e:
        log.warning("Commons indisponible (%s, %s): %s", lon, lat, e)
        return []

    photos = []
    for page in ((data.get("query") or {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        thumb = info.get("thumburl") or info.get("url")
        if not thumb:
            continue
        photos.append({
            "id": str(page.get("pageid")),
            "thumb": thumb,
            "sd": info.get("url"),
            "viewer": info.get("descriptionurl"),
            "is_360": False,
            "title": (page.get("title") or "").removeprefix("File:"),
            "date": (meta.get("DateTimeOriginal") or {}).get("value"),
            "licence": (meta.get("LicenseShortName") or {}).get("value"),
            # Le champ Artist contient du HTML : on ne garde que le texte.
            "author": _strip_html((meta.get("Artist") or {}).get("value", "")),
            "source": "Wikimedia Commons",
        })
    return photos


def _strip_html(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html or "").strip()[:120]


@app.get("/v1/streetview", tags=["buildings"])
async def streetview(
    lon: float = Query(description="Longitude"),
    lat: float = Query(description="Latitude"),
    radius: float = Query(0.0006, description="Half-size of the search bbox in degrees"),
):
    """Photos ouvertes autour d'un point : Panoramax d'abord (vue au sol
    française, la plus fraîche), puis Wikimedia Commons en complément.

    L'ordre compte : la vue au sol montre ce qu'on verrait en arrivant devant
    le bien ; Commons apporte le contexte — l'église, la mairie, le monument
    voisin — là où Panoramax n'a rien (#200)."""
    street, commons = await asyncio.gather(
        _nearby_photos(lon, lat, radius),
        _commons_photos(lon, lat))
    for p in street:
        p.setdefault("source", "Panoramax")
        p.setdefault("licence", "CC-BY-SA 4.0")
    return {"photos": street + commons,
            "sources": ["Panoramax — CC-BY-SA 4.0", "Wikimedia Commons"]}


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
