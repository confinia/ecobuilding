#!/usr/bin/env python3
"""Rapport quotidien d'activité end-user (#393).

Interroge la télémétrie visite-scopée (vues.vue_batiment), rend une carte des
consultations des dernières 24 h, compose un courriel HTML et l'envoie.

Conçu pour tourner SUR LA VM (accès podman) via une tâche planifiée. Respecte
le modèle de vie privée : familles OS/navigateur grossières, IP tronquées en
amont, identifiant de visite éphémère — aucune donnée personnelle ne sort d'ici.

Env attendu (deploy/secrets.env) : SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM. Optionnel : DIGEST_TO (défaut clement@igonet.fr).
"""
import base64
import json
import os
import smtplib
import subprocess
import sys
import urllib.parse
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid

BDNB_DB = os.environ.get("DIGEST_DB_CONTAINER", "ecobuilding-bdnb_bdnb-db_1")
RENDER = os.environ.get("DIGEST_RENDER_CONTAINER", "ecobuilding-render_render_1")
TO = os.environ.get("DIGEST_TO", "clement@igonet.fr")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
TILES = os.environ.get(
    "DIGEST_TILES",
    "https://ecobuilding.confinia.io/api/v1/tiles/batiment_groupe/{z}/{x}/{y}.pbf")
# Journée COMPLÈTE de la veille (Europe/Paris), pas une fenêtre glissante : un
# rapport du matin qui parle d'« hier » se recoupe exactement avec la ligne
# « 7 jours » et ne mélange jamais deux journées (#393).
WIN = ("(ts at time zone 'Europe/Paris')::date "
       "= ((now() at time zone 'Europe/Paris')::date - 1)")


def psql(sql):
    """Exécute une requête et renvoie une liste de lignes (colonnes tabulées)."""
    r = subprocess.run(
        ["podman", "exec", BDNB_DB, "psql", "-U", "bdnb", "-d", "bdnb",
         "-tAF", "\t", "-c", sql],
        capture_output=True, text=True, timeout=30)   # jamais bloqué (règle timeout)
    if r.returncode != 0:
        raise RuntimeError(f"psql: {r.stderr[:400]}")
    return [ln.split("\t") for ln in r.stdout.strip().splitlines() if ln]


def scalar_row(sql):
    rows = psql(sql)
    return rows[0] if rows else []


def render_map(points):
    """Carte France des consultations 24 h. Best-effort : None si échec."""
    if not points:
        return None
    pts = [{"lon": float(lo), "lat": float(la), "label": ""}
           for lo, la in points if lo and la][:60]
    if not pts:
        return None
    params = {"lon": "2.4", "lat": "46.6", "zoom": "5", "pitch": "0",
              "bearing": "0", "points": json.dumps(pts, separators=(",", ":")),
              "tiles": TILES}
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"http://127.0.0.1:8040/shot?{qs}"
    # Le rendu n'est pas publié sur l'hôte : on récupère l'image DEPUIS le
    # conteneur de rendu (même origine que /shot), encodée en base64.
    node = ("fetch(%s).then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);"
            "return r.arrayBuffer()}).then(b=>process.stdout.write("
            "Buffer.from(b).toString('base64'))).catch(e=>{"
            "process.stderr.write(String(e));process.exit(1)})") % json.dumps(url)
    r = subprocess.run(["podman", "exec", RENDER, "node", "-e", node],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not r.stdout.strip():
        sys.stderr.write(f"[carte] rendu indisponible: {r.stderr[:200]}\n")
        return None
    try:
        return base64.b64decode(r.stdout.strip())
    except Exception:
        return None


def collect():
    t = scalar_row(
        f"select count(*), count(distinct visite), count(distinct bdnb_id) "
        f"from vues.vue_batiment where {WIN}")
    vues, visites, batiments = (t + ["0", "0", "0"])[:3]
    data = {
        "vues": int(vues), "visites": int(visites), "batiments": int(batiments),
        "top_bat": psql(
            f"select bdnb_id, count(*) from vues.vue_batiment where {WIN} "
            "group by 1 order by 2 desc limit 8"),
        "sources": psql(
            f"select coalesce(nullif(source,''),'(direct)'), count(*) "
            f"from vues.vue_batiment where {WIN} group by 1 order by 2 desc limit 8"),
        "systemes": psql(
            f"select coalesce(nullif(systeme,''),'(inconnu)'), count(*) "
            f"from vues.vue_batiment where {WIN} group by 1 order by 2 desc"),
        "pays": psql(
            f"select coalesce(nullif(pays,''),'??'), count(*) "
            f"from vues.vue_batiment where {WIN} group by 1 order by 2 desc limit 8"),
        "semaine": psql(
            "select to_char(date_trunc('day',ts),'DD/MM'), count(*), "
            "count(distinct visite) from vues.vue_batiment "
            "where ts > now() - interval '7 days' group by date_trunc('day',ts) "
            "order by date_trunc('day',ts)"),
        "points": [(r[0], r[1]) for r in psql(
            f"select lon, lat from vues.vue_batiment where {WIN} "
            "and lon is not null and lat is not null limit 300")],
        "jour": (scalar_row(
            "select to_char((now() at time zone 'Europe/Paris')::date - 1, "
            "'DD/MM/YYYY')") or [""])[0],
    }
    return data


def _rows(pairs, unit=""):
    out = []
    for name, count in pairs:
        out.append(
            f'<tr><td style="padding:3px 12px 3px 0">{name}</td>'
            f'<td style="padding:3px 0;text-align:right;font-variant-numeric:tabular-nums">'
            f'{count}{unit}</td></tr>')
    return "\n".join(out) or '<tr><td style="color:#888">—</td><td></td></tr>'


def build_html(d, has_map, cid):
    jour = d.get("jour", "")
    carte = (f'<img src="cid:{cid}" alt="Carte des consultations (hier)" '
             'style="width:100%;max-width:600px;border-radius:8px;margin:8px 0" />'
             if has_map else
             '<p style="color:#888;font-style:italic">Carte indisponible aujourd\'hui.</p>')
    sem = "".join(
        f'<tr><td style="padding:2px 12px 2px 0">{j}</td>'
        f'<td style="padding:2px 12px 2px 0;text-align:right">{v} vues</td>'
        f'<td style="padding:2px 0;text-align:right;color:#2b7a4b">{vi} visites</td></tr>'
        for j, v, vi in d["semaine"])
    return f"""\
<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:640px;margin:0 auto">
  <h2 style="color:#2b7a4b;margin:0 0 2px">EcoBuilding — activité d'hier</h2>
  <div style="color:#666;font-size:13px;margin-bottom:16px">Journée du {jour}</div>

  <table style="width:100%;border-collapse:collapse;margin-bottom:8px">
    <tr>
      <td style="text-align:center;padding:10px;background:#f2f8f4;border-radius:8px">
        <div style="font-size:28px;font-weight:700;color:#2b7a4b">{d['vues']}</div>
        <div style="font-size:12px;color:#666">fiches vues</div></td>
      <td style="width:10px"></td>
      <td style="text-align:center;padding:10px;background:#f2f8f4;border-radius:8px">
        <div style="font-size:28px;font-weight:700;color:#2b7a4b">{d['visites']}</div>
        <div style="font-size:12px;color:#666">visites distinctes</div></td>
      <td style="width:10px"></td>
      <td style="text-align:center;padding:10px;background:#f2f8f4;border-radius:8px">
        <div style="font-size:28px;font-weight:700;color:#2b7a4b">{d['batiments']}</div>
        <div style="font-size:12px;color:#666">bâtiments</div></td>
    </tr>
  </table>

  {carte}

  <table style="width:100%;margin-top:12px"><tr style="vertical-align:top">
    <td style="width:50%;padding-right:16px">
      <h3 style="font-size:14px;margin:12px 0 4px">Provenance</h3>
      <table style="font-size:13px">{_rows(d['sources'])}</table>
      <h3 style="font-size:14px;margin:16px 0 4px">Pays</h3>
      <table style="font-size:13px">{_rows(d['pays'])}</table>
    </td>
    <td style="width:50%">
      <h3 style="font-size:14px;margin:12px 0 4px">Systèmes</h3>
      <table style="font-size:13px">{_rows(d['systemes'])}</table>
      <h3 style="font-size:14px;margin:16px 0 4px">Bâtiments les plus vus</h3>
      <table style="font-size:12px">{_rows(d['top_bat'])}</table>
    </td>
  </tr></table>

  <h3 style="font-size:14px;margin:16px 0 4px">7 derniers jours</h3>
  <table style="font-size:13px">{sem}</table>

  <p style="color:#999;font-size:11px;margin-top:20px;border-top:1px solid #eee;padding-top:8px">
    Données visite-scopées, sans donnée personnelle (familles OS/navigateur, IP tronquées,
    identifiant de visite éphémère). EcoBuilding · rapport automatique quotidien.</p>
</div>"""


def main():
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        if not os.environ.get(k):
            sys.exit(f"manque {k} dans l'environnement (source deploy/secrets.env)")
    d = collect()
    img = render_map(d["points"])
    cid = make_msgid(domain="ecobuilding.confinia.io")[1:-1]

    msg = EmailMessage()
    msg["Subject"] = (f"EcoBuilding · {d['vues']} fiches, {d['visites']} visites "
                      f"(hier {d['jour']})")
    msg["From"] = SMTP_FROM
    msg["To"] = TO
    msg.set_content(
        f"Activité EcoBuilding (hier {d['jour']}) : {d['vues']} fiches vues, "
        f"{d['visites']} visites, {d['batiments']} bâtiments. "
        "Version HTML requise pour le détail et la carte.")
    msg.add_alternative(build_html(d, img is not None, cid), subtype="html")
    if img is not None:
        # Rattache l'image au <img cid:...> de la partie HTML.
        html_part = msg.get_payload()[1]
        html_part.add_related(img, "image", "png", cid=f"<{cid}>")

    if SMTP_PORT == 465:
        s = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
    else:
        s = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
        s.starttls()
    with s:
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)
    print(f"digest envoyé à {TO} : {d['vues']} vues / {d['visites']} visites "
          f"/ carte={'oui' if img else 'non'}")


if __name__ == "__main__":
    main()
