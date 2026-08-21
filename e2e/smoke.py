#!/usr/bin/env python3
"""Contrôle de bon fonctionnement d'un environnement déployé — en LECTURE SEULE.

Pourquoi ce fichier existe : le 2026-08-20, cinq pannes bien réelles vivaient en
production sans qu'aucun test ne les voie, parce que la vérification de
déploiement se limitait à un appel à /v1/healthz et que l'e2e Selenium ne tourne
que sur le sandbox. Chaque contrôle ci-dessous correspond à une panne vécue :

  tuiles 3D      la carte se vidait en silence (quota BDNB épuisé, 429)
  flux           le panneau attendait la source la plus lente (5,7 s de vide)
  chargement     la fiche PDF recollectait tout une seconde fois (15,2 s)
  prix DVF       le bloc n'apparaissait JAMAIS (RPC 60 s > timeout 15 s)
  authentification  connexion impossible sur staging (cookie sur le mauvais
                 domaine, « Cookie introuvable »)

Aucune écriture : ni compte créé, ni paiement, ni fiche consommée. Le script est
donc sûr sur n'importe quel environnement, production comprise — contrairement à
run.sh, qui inscrit et paie et refuse la production pour cette raison.

Usage :  python3 e2e/smoke.py [https://staging.ecobuilding.confinia.io]
Sortie  : 0 si tout passe, 1 sinon (utilisable comme garde-fou de déploiement).
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

APP = (sys.argv[1] if len(sys.argv) > 1 else "https://staging.ecobuilding.confinia.io").rstrip("/")
API = f"{APP}/api/v1"
UA = {"User-Agent": "ecobuilding-smoke/1.0"}

# Bâtiment de référence : Montpellier centre, couvert par la BDNB ET par DVF
# (c'est lui qui a servi à mesurer la RPC prix à 60 s puis à 131 ms).
REF_ADDRESS = "7 rue Foch Montpellier"
# Tuile z14 couvrant le 1er arrondissement de Paris — BDNB ne publie que le z14.
REF_TILE = "14/8297/5635"

results = []


def check(name, fn):
    t0 = time.time()
    try:
        detail = fn()
        ok = True
    except AssertionError as e:
        detail, ok = str(e), False
    except Exception as e:                       # réseau, JSON, timeout…
        detail, ok = f"{type(e).__name__}: {e}", False
    results.append((ok, name, detail, time.time() - t0))


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)


def get_json(url, timeout=30):
    with get(url, timeout) as r:
        return json.load(r)


def c_healthz():
    d = get_json(f"{API}/healthz", 15)
    assert d.get("status") == "ok", f"statut inattendu : {d}"
    return d.get("api_version", "?")


def c_tiles():
    """Les tuiles 3D doivent venir de NOTRE cache, avec un Cache-Control long.
    Sans cela, le navigateur du visiteur tape api.bdnb.io (120 req/min et
    10 000/mois par IP) et la carte se vide au bout de quelques rechargements."""
    with get(f"{API}/tiles/batiment_groupe/{REF_TILE}.pbf", 60) as r:
        blob = r.read()
        cc = r.headers.get("Cache-Control", "")
    assert len(blob) > 10_000, f"tuile suspecte : {len(blob)} octets"
    assert "max-age" in cc, f"Cache-Control absent ou trop court : {cc!r}"
    return f"{len(blob) // 1024} Ko, {cc}"


def c_stream_and_single_load():
    """Le bâtiment doit s'afficher tout de suite, et la fiche PDF ne doit RIEN
    recollecter ensuite (elle lit le même agrégat en cache)."""
    url = f"{API}/lookup/stream?q=" + urllib.parse.quote(REF_ADDRESS)
    t0 = time.time()
    first = None
    bid = lon = lat = None
    prices_seen = None
    with get(url, 120) as r:
        for line in r:
            ev = json.loads(line)
            if ev["type"] == "core":
                first = time.time() - t0
                b = (ev["buildings"] or [{}])[0]
                bid = b.get("bdnb_id")
                lon, lat = ev["query"].get("lon"), ev["query"].get("lat")
            elif ev["type"] == "block" and ev["name"] == "prices":
                prices_seen = ev["value"]
    assert first is not None, "aucun événement « core » : le flux est cassé"
    assert first < 3.0, f"bâtiment affiché en {first:.1f} s (attendu < 3 s)"
    assert bid, "aucun bâtiment renvoyé pour l'adresse de référence"

    t1 = time.time()
    get_json(f"{API}/buildings/{bid}?lon={lon}&lat={lat}", 120)
    again = time.time() - t1
    assert again < 2.0, (f"la fiche PDF rejoue l'orchestration ({again:.1f} s) "
                         "au lieu de lire le cache")
    c_stream_and_single_load.prices = prices_seen
    return f"bâtiment en {first:.2f} s, relecture en {again:.2f} s"


def c_prices():
    """Le bloc « Prix de vente » (DVF) doit remonter des données : il a été
    invisible pendant des mois, la RPC dépassant le timeout de l'API."""
    p = getattr(c_stream_and_single_load, "prices", None)
    assert p is not None, "aucun bloc prix dans le flux"
    assert p.get("available") is True, f"DVF indisponible sur ce bâtiment : {p}"
    med = p.get("commune_eur_m2") or {}
    assert med, "médianes communales vides — la RPC a probablement expiré"
    return ", ".join(f"{k} {v['median']} €/m²" for k, v in med.items())


def c_auth_consistency():
    """L'app doit viser l'URL ABSOLUE du Keycloak de son environnement. En
    relatif, staging posait le cookie sur son domaine puis postait le formulaire
    vers celui de production : « Cookie introuvable », connexion impossible."""
    with get(f"{APP}/env.js", 20) as r:
        env = r.read().decode()
    auth = realm = None
    for line in env.splitlines():
        if "ECO_AUTH_URL" in line and "=" in line:
            auth = line.split("=", 1)[1].strip().strip(';').strip().strip('"')
        if "ECO_REALM" in line and "=" in line:
            realm = line.split("=", 1)[1].strip().strip(';').strip().strip('"')
    assert auth, "ECO_AUTH_URL absent de env.js : l'app appellerait /auth en relatif"
    assert realm, "ECO_REALM absent de env.js"
    disco = get_json(f"{auth}/realms/{realm}/.well-known/openid-configuration", 20)
    issuer = disco["issuer"]
    assert issuer.startswith(auth), (
        f"incohérence : l'app vise {auth} mais Keycloak s'annonce en {issuer}")
    return f"{realm} @ {auth}"


def c_mobile_contract():
    """Contrat d'API dont dépend l'app iPhone INSTALLÉE.

    Une app publiée ne se met pas à jour en même temps que le serveur : ses
    utilisateurs gardent leur version des semaines. Le 2026-08-21, un promote a
    basculé la production sur une image antérieure au travail mobile — l'app
    s'est retrouvée traitée comme un visiteur web anonyme, plafonnée à 3 fiches
    par mois, et plus rien ne fonctionnait. Rien ne l'avait vu. Ce contrôle
    échoue désormais avant qu'un utilisateur ne le découvre."""
    cfg = get_json(f"{API}/config", 20)
    m = cfg.get("mobile")
    assert m, "l'offre mobile a disparu de /v1/config : l'app ne sait plus quoi proposer"
    assert isinstance(m.get("free_reports"), int), "fiches offertes absentes"
    assert m.get("unit_eur"), "prix à l'unité absent"
    assert set(m.get("tiers") or {}), "aucun palier mobile"

    # L'autocomplétion lit la clé « suggestions » : la renommer casserait la
    # recherche de toutes les versions déjà installées.
    sug = get_json(f"{API}/suggest?q=" + urllib.parse.quote("7 rue Foch Montpellier"), 30)
    assert isinstance(sug.get("suggestions"), list) and sug["suggestions"], \
        "/v1/suggest ne renvoie plus de « suggestions »"
    first = sug["suggestions"][0]
    for k in ("label", "lon", "lat"):
        assert k in first, f"champ « {k} » absent des suggestions"

    # Le quota mobile doit être compté par installation, pas par IP.
    req = urllib.request.Request(f"{API}/quota", headers=dict(UA, **{"X-Install-Id": "smoke-" + "0" * 12}))
    try:
        urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as e:
        assert e.code != 500, "la porte de quota mobile est cassée"
    return (f"{m['free_reports']} offertes · {m['unit_eur']} € l'unité · "
            f"paliers {', '.join(sorted(m['tiers']))}")


def c_payment_rule():
    """Règle 7 : la production ne porte aucune configuration de paiement."""
    cfg = get_json(f"{API}/config", 20)
    mode = cfg.get("payment_mode")
    if APP == "https://ecobuilding.confinia.io":
        assert not cfg.get("payment_enabled"), "paiement ACTIF en production (règle 7)"
        return "désactivé, conforme"
    return f"mode {mode}"


CHECKS = [
    ("API en vie", c_healthz),
    ("tuiles 3D servies et mises en cache", c_tiles),
    ("affichage au fil de l'eau + chargement unique", c_stream_and_single_load),
    ("bloc prix DVF", c_prices),
    ("cohérence d'authentification", c_auth_consistency),
    ("contrat d'API de l'app mobile", c_mobile_contract),
    ("règle de paiement", c_payment_rule),
]

print(f"== contrôle de {APP}\n")
for name, fn in CHECKS:
    check(name, fn)
    ok, n, detail, dt = results[-1]
    print(f"[{'OK ' if ok else 'KO '}] {n:46} {dt:5.2f}s  {detail}")

failed = [r for r in results if not r[0]]
print()
if failed:
    print(f"{len(failed)} contrôle(s) en échec sur {len(results)}.")
    sys.exit(1)
print(f"{len(results)} contrôles passés.")
