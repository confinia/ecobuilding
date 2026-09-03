"""Normalized per-building PDF fiche (weasyprint).

Target user: diagnostiqueurs / pre-sale professionals — a consistent one-page
document to prepare a visit or a dossier. Usage measured
via the ecobuilding_reports metric.

Bilingual (#370): every user-visible template string goes through `T()`. The
French original IS the key — rendering in French returns it untouched
(byte-identical output), rendering in English looks it up in `_EN` at the end
of this module. Data values (addresses, materials, dataset names) are never
translated.
"""

from contextvars import ContextVar
from datetime import datetime, timezone
from urllib.parse import quote

from weasyprint import HTML

_LANGUE: ContextVar[str] = ContextVar("langue", default="fr")


def T(fr: str) -> str:
    """The French template string itself, or its English translation when the
    report is being rendered in English. Unknown keys fall back to French."""
    if _LANGUE.get() == "en":
        return _EN.get(fr, fr)
    return fr


# Dataset versions surfaced in the traceability annex (#93). Update on refresh.
BDNB_MILLESIME = "2026_02 (open data)"
DVF_WINDOW = "2021-2025"

DPE_COLORS = {"A": "#009036", "B": "#52b153", "C": "#a5cc74", "D": "#f4e70f",
              "E": "#f0b40f", "F": "#eb8235", "G": "#d7221f"}
GES_COLORS = {"A": "#f2eefb", "B": "#dfd3f3", "C": "#c7b2e9", "D": "#a98ddb",
              "E": "#8a68cb", "F": "#6b46b8", "G": "#4a2a94"}
# Ad-style class thresholds (kWh/m²/an and kgCO2/m²/an) to derive the GES
# class when only the value is known.
GES_BOUNDS = [(6, "A"), (11, "B"), (30, "C"), (50, "D"), (70, "E"), (100, "F")]


def _ges_class(value):
    if value is None:
        return None
    for bound, cls in GES_BOUNDS:
        if value <= bound:
            return cls
    return "G"


def _scale(active_cls, colors, value_text, dark_text_classes=("A", "B", "C", "D"),
           counts=None):
    """Ad-style A→G arrow scale with the active class highlighted.

    `counts` — {classe: nombre de logements} quand l'adresse porte plusieurs
    diagnostics (#307). L'échelle est l'image que tout le monde reconnaît du
    DPE : marquer une seule classe sous des blocs qui en montrent trois
    faisait mentir l'élément le plus officiel de la page. Chaque classe
    présente est marquée avec son compte ; la valeur chiffrée reste sur la
    classe du logement représentatif.
    """
    rows = []
    for i, cls in enumerate("ABCDEFG"):
        width = 30 + i * 10
        active = cls == active_cls or bool(counts and counts.get(cls))
        text_col = "#333" if (colors is GES_COLORS and cls in dark_text_classes) or cls == "D" else "#fff"
        extra = ""
        if cls == active_cls and value_text:
            extra = f'<span class="val">{value_text}</span>'
        elif counts and counts.get(cls):
            extra = f'<span class="val">×{counts[cls]}</span>'
        rows.append(
            f'<div class="bar{" active" if active else ""}" '
            f'style="width:{width}%;background:{colors[cls]};color:{text_col}">'
            f'<strong>{cls}</strong>{extra}</div>'
        )
    return '<div class="scale">' + "".join(rows) + "</div>"


def _row(label, value, unit=""):
    if value in (None, "", []):
        return ""
    return f'<tr><td class="k">{label}</td><td>{value}{unit}</td></tr>'


def _eur(n) -> str:
    return f"{round(n):,}".replace(",", " ") if n not in (None, "") else "—"


def _dia_html(m):
    """Bloc « Dynamique du marché (DIA) » — uniquement sur le territoire de
    Montpellier Méditerranée Métropole. Le libellé dit explicitement qu'il
    s'agit de montants DEMANDÉS (mise en vente), pas de prix finaux."""
    if not m:
        return ""
    vol = f"{m['listings_12m']}"
    if m.get("listings_3m"):
        vol += T(" — dont {n} au dernier trimestre").format(n=m['listings_3m'])
    price = ""
    if m.get("median_asking_eur"):
        price = f"{m['median_asking_eur']:,} €".replace(",", " ")
        if m.get("median_asking_eur_m2"):
            price += f" ({m['median_asking_eur_m2']:,} €/m²)".replace(",", " ")
    note = T("Données {d} —\nMontpellier Méditerranée Métropole (Open Data).").format(d=m['updated'])
    return f"""
<h2>{T("Dynamique du marché (DIA)")}</h2>
<table>
  {_row(T("Zone"), f"{m['zone']} ({m['scope']})")}
  {_row(T("Mises en vente sur 12 mois"), vol)}
  {_row(T("Prix médian demandé"), price or None)}
</table>
<p class="note">{m['note']} {note}</p>
"""


def _prices_html(p: dict | None, fiche_logement: bool = False) -> str:
    """DVF home-price section (recent parcelle sales + commune median €/m²).
    Honest about the DVF coverage gap (Alsace-Moselle, Mayotte)."""
    if not p:
        return ""
    if not p.get("available"):
        return ('<h2>' + T("Prix de vente (DVF)") + '</h2><p class="meta">'
                + T("Données de prix indisponibles pour ce secteur : la base DVF "
                    "ne couvre pas l'Alsace-Moselle ni Mayotte.") + '</p>')
    med = {t: v for t, v in (p.get("commune_eur_m2") or {}).items() if v.get("median")}
    med_txt = " · ".join(f"{t} {_eur(v['median'])} €/m² (n={v['n']})" for t, v in med.items()) or "—"
    # Une MUTATION groupée (appartement + cave + parking vendus ensemble)
    # répète sa valeur foncière sur CHAQUE ligne de lot : affiché tel quel,
    # « 4 565 000 € » apparaissait deux fois et se lisait comme le prix de
    # chaque lot (#323). On regroupe par (date, valeur) et on nomme la chose.
    groupes = {}
    for s in (p.get("sales") or []):
        groupes.setdefault(((s.get("date") or "")[:10], s.get("valeur_fonciere")),
                           []).append(s)
    rows = ""
    for (date, valeur), lots in list(groupes.items())[:6]:
        if len(lots) == 1:
            s = lots[0]
            surf = f"{round(s['surface_m2'])} m²" if s.get("surface_m2") else "—"
            em = f"{_eur(s['eur_m2'])} €/m²" if s.get("eur_m2") else "—"
            rows += (f'<tr><td>{date}</td><td>{s.get("type_local") or "—"}</td>'
                     f'<td>{surf}</td><td>{_eur(valeur)} €</td><td>{em}</td></tr>')
        else:
            desc = " + ".join(
                (s.get("type_local") or "lot").lower()
                + (f" {round(s['surface_m2'])} m²" if s.get("surface_m2") else "")
                for s in lots)
            rows += (f'<tr><td>{date}</td><td>'
                     + T("Vente groupée : {desc}").format(desc=desc)
                     + f'</td><td>—</td><td>{_eur(valeur)} € <span class="meta">'
                     + T("(prix de l'ensemble)") + '</span></td><td>—</td></tr>')
    sales_tbl = (f'<table class="sales"><tr><td class="k">{T("Date")}</td><td class="k">{T("Type")}</td><td class="k">{T("Surface")}</td>'
                 f'<td class="k">{T("Montant")}</td><td class="k">€/m²</td></tr>{rows}</table>'
                 if rows else '<p class="meta">' + T("Aucune vente récente enregistrée sur la parcelle.") + '</p>')
    note_logement = ('<p class="meta">'
                     + T("Ventes enregistrées sur la PARCELLE — pas "
                         "nécessairement celles du logement de cette fiche.")
                     + '</p>'
                     if fiche_logement else "")
    return ('<h2>' + T("Prix de vente (DVF)")
            + (T(" — parcelle") if fiche_logement else "") + '</h2>'
            + note_logement
            + '<p>' + T("Prix médian dans la commune : <strong>{med}</strong>").format(med=med_txt)
            + f'</p>{sales_tbl}'
            + '<p class="meta">'
            + T("€/m² indicatif, calculé sur les ventes d'un seul local. "
                "Transactions réelles enregistrées par la DGFiP.") + '</p>')


def _prov(source, version, key, date, link_url) -> str:
    """One provenance card. Empty rows are omitted; the verify link is real
    (never fabricated) — a URL only when we actually have a reproducible one."""
    link = f'<a href="{link_url}">{link_url}</a>' if link_url and link_url != "—" else "—"
    rows = "".join(_row(k, v) for k, v in [
        (T("Source"), source), (T("Version / licence"), version),
        (T("Clé de recherche"), key), (T("Date de référence"), date),
        (T("Vérifier à la source"), link)])
    return f'<table class="prov">{rows}</table>' if rows else ""


def _traceability_annex(data: dict, photos: list | None) -> str:
    """Annex page (#93): for each datum, its source, version, the exact key used
    to fetch it, a reference date and a verifiable upstream link — so the reader
    checks against the origin instead of trusting EcoBuilding. Only categories
    actually present are listed; no empty rows, no fake links."""
    b = (data.get("buildings") or [{}])[0]
    q = data.get("query", {})
    e = b.get("energy") or {}
    risks = data.get("area_risks") or {}
    prices = data.get("prices") or {}
    photos = [p for p in (photos or []) if p.get("id")]
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    bdnb_id = b.get("bdnb_id") or q.get("bdnb_id")
    lon, lat = q.get("lon"), q.get("lat")
    commune = risks.get("commune") or prices.get("commune_code")
    addr = q.get("address") or b.get("address")

    cards = []
    if addr:
        key = addr + (f" · id BAN {q['ban_id']}" if q.get("ban_id") else "")
        cards.append((T("Adresse"), _prov(
            "Base Adresse Nationale (BAN)", "Licence Ouverte",
            key, T("Référentiel courant"),
            f"https://api-adresse.data.gouv.fr/search/?q={quote(addr)}")))
    if bdnb_id:
        cards.append((T("Bâtiment, énergie (DPE), solaire"), _prov(
            "BDNB — Base de Données Nationale des Bâtiments (CSTB)",
            T("Millésime {v} · Licence Ouverte 2.0").format(v=BDNB_MILLESIME),
            f"batiment_groupe_id = {bdnb_id}",
            T("{d} (date du DPE)").format(d=(e.get("dpe_date") or "")[:10])
            if e.get("dpe_date") else T("Millésime {v}").format(v=BDNB_MILLESIME),
            "https://api.bdnb.io/v1/bdnb/donnees/batiment_groupe_complet"
            f"?batiment_groupe_id=eq.{bdnb_id}")))
    if risks.get("report_url") or lon is not None:
        key = ((f"lat/lon = {lat}, {lon}" if lon is not None else "")
               + (T(" · commune INSEE {c}").format(c=commune) if commune else "")) or "—"
        cards.append((T("Risques"), _prov(
            T("Géorisques (BRGM / Ministère de la Transition écologique)"),
            "Licence Ouverte", key, T("Consultation du {now}").format(now=now),
            risks.get("report_url") or "https://www.georisques.gouv.fr")))
    if prices:
        # Deep-link straight to the property on the official DVF explorer (#98):
        # verified that explore.data.gouv.fr/immobilier reads lat/lng/zoom and
        # centres the map there. Fall back to the app home if we lack coords.
        dvf_url = (f"https://explore.data.gouv.fr/fr/immobilier?onglet=carte&lat={lat}&lng={lon}&zoom=18"
                   if (lon is not None and lat is not None) else "https://app.dvf.etalab.gouv.fr")
        if prices.get("available"):
            yrs = sorted(s["date"][:4] for s in (prices.get("sales") or []) if s.get("date"))
            dref = (T("ventes {a}–{b}").format(a=yrs[0], b=yrs[-1]) if yrs
                    else T("fenêtre {w}").format(w=DVF_WINDOW))
            cards.append((T("Prix (DVF)"), _prov(
                T("DVF géolocalisé — Demandes de Valeurs Foncières (DGFiP / Etalab)"),
                T("Fenêtre {w} · Licence Ouverte 2.0").format(w=DVF_WINDOW),
                T("parcelle cadastrale du bâtiment · commune INSEE {c}").format(
                    c=prices.get('commune_code') or '—'),
                dref, dvf_url)))
        else:
            cards.append((T("Prix (DVF)"), _prov(
                "DVF (DGFiP / Etalab)",
                T("Fenêtre {w} · Licence Ouverte 2.0").format(w=DVF_WINDOW),
                T("indisponible : l'Alsace-Moselle et Mayotte ne sont pas couvertes par la DVF"),
                "—", dvf_url)))
    # Fiche CIBLÉE (#329) : l'annexe trace le diagnostic CHOISI, pas le
    # représentatif — la provenance doit désigner ce que le document montre.
    cible = data.get("dpe_cible") or {}
    od = data.get("official_dpe") or {}
    num_dpe = cible.get("numero_dpe") or od.get("dpe_number")
    if num_dpe:
        cards.append((T("DPE officiel"), _prov(
            T("Observatoire DPE (ADEME)"), "Licence Ouverte",
            f"numero_dpe = {num_dpe} "
            + (T("(logement choisi)") if cible else T("(logement représentatif BDNB)")),
            (cible.get("etabli_le") if cible else od.get("established_on")) or "—",
            "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"
            f"?qs=numero_dpe:%22{num_dpe}%22")))
    lt = data.get("local_taxes") or {}
    if lt.get("property_tax_built_pct") is not None:
        cards.append((T("Fiscalité locale"), _prov(
            T("DGFiP — Fiscalité directe locale (data.economie.gouv.fr)"),
            "Licence Ouverte",
            T("insee_com = {c} · exercice {y}").format(c=commune or '—', y=lt.get('year') or '—'),
            T("exercice {y}").format(y=lt.get('year') or '—'),
            "https://data.economie.gouv.fr/explore/dataset/fiscalite-locale-des-particuliers-geo/")))
    sc = data.get("schools") or {}
    if sc.get("within_2km"):
        cards.append((T("Écoles"), _prov(
            T("Annuaire de l'éducation (MENJ)"), "Licence Ouverte",
            T("within_distance 2 km de {lat}, {lon}").format(lat=lat, lon=lon),
            T("annuaire courant"),
            "https://data.education.gouv.fr/explore/dataset/fr-en-annuaire-education/")))
    gw = data.get("groundwater") or {}
    if gw.get("available"):
        cards.append((T("Eau souterraine (nappe)"), _prov(
            "Hub'Eau piézométrie — ADES (BRGM / OFB)", "Licence Ouverte",
            T("code BSS {c} · station à {d} m du bâtiment").format(
                c=gw.get('station_code_bss'), d=gw.get('station_distance_m')),
            T("{d} (dernière mesure)").format(d=(gw.get("measured_on") or "—")[:10]),
            "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/chroniques"
            f"?code_bss={quote(gw.get('station_code_bss') or '')}&size=1&sort=desc")))
    wn = data.get("water_network") or {}
    if wn.get("efficiency_pct") is not None:
        cards.append((T("Eau potable (rendement du réseau)"), _prov(
            T("SISPEA — Observatoire des services publics d'eau (OFB)"),
            "Licence Ouverte",
            T("commune INSEE {c} · indicateur P104.3").format(c=wn.get('commune_insee') or '—'),
            T("année {y} (dernière publiée)").format(y=wn.get('year') or '—'),
            "https://hubeau.eaufrance.fr/api/v0/indicateurs_services/communes"
            f"?code_commune={wn.get('commune_insee') or ''}&type_service=AEP")))
    pv = data.get("solar_pv") or {}
    if pv and lon is not None:
        cards.append((T("Solaire photovoltaïque"), _prov(
            T("PVGIS v5.2 (Joint Research Centre, Commission européenne)"),
            T("© Union européenne"), f"lat/lon = {lat}, {lon} · {pv.get('assumptions') or ''}",
            T("base climatique PVGIS-SARAH2"),
            f"https://re.jrc.ec.europa.eu/api/v5_2/PVcalc?lat={lat}&lon={lon}"
            "&peakpower=1&loss=14&optimalinclination=1&outputformat=json")))
    if photos:
        ids = ", ".join(str(p["id"])[:8] for p in photos[:3])
        dref = next((str(p["date"])[:10] for p in photos if p.get("date")), T("voir la visionneuse"))
        srcs = sorted({p.get("source", "Panoramax") for p in photos[:4]})
        cards.append((T("Photos (contexte)"), _prov(
            T(" et ").join(srcs), T("CC-BY-SA / licences libres, voir chaque image"),
            T("photo id(s) : {ids}").format(ids=ids), dref,
            photos[0].get("viewer") or "https://panoramax.xyz")))

    sections = "".join(f"<h2>{t}</h2>{c}" for t, c in cards if c)
    if not sections:
        return ""
    intro = T("Ce rapport agrège des données ouvertes. Pour chaque donnée : la source,\n"
              "la version, la clé de recherche exacte et un lien pour vérifier directement à la source,\n"
              "sans avoir à faire confiance à EcoBuilding. Généré le {now}.").format(now=now)
    footer_txt = T("Sources publiques (Licence Ouverte, CC-BY-SA, ODbL). Les identifiants ci-dessus\n"
                   "  permettent de retrouver la donnée d'origine. Document informatif, non contractuel.")
    return f"""
<style>
  table.prov {{ table-layout: fixed; }}
  table.prov td {{ overflow-wrap: anywhere; word-break: break-word; }}
  table.prov td.k {{ width: 26%; }}
  table.prov a {{ word-break: break-all; }}
</style>
<div style="page-break-before: always;"></div>
<header>
  <div class="brand">EcoBuilding</div>
  <div class="doctitle">{T("Annexe — traçabilité des données")}</div>
</header>
<h1>{T("D'où vient chaque donnée")}</h1>
<p class="meta">{intro}</p>
{sections}
<footer>
  {footer_txt}
</footer>
"""


def _principal_address_note(shown_address: str, b: dict) -> str:
    """When the fiche is titled with the searched address but the BDNB
    'bâtiment groupe' has a different principal address (a group can span
    several streets, #146), say so instead of silently looking wrong."""
    principal = b.get("address")
    if not principal or principal == shown_address:
        return ""
    n = T(" ({n} logements)").format(n=b['dwellings']) if b.get("dwellings") else ""
    return ('<p class="meta">'
            + T("Bâtiment groupe BDNB{n} — adresse principale : {p}").format(n=n, p=principal)
            + '</p>')


def _dpe_spread_html(e: dict, dpe_representatif: str | None = None,
                     dpe_cible: str | None = None) -> str:
    """L'éventail des DPE connus à l'adresse (#287).

    Une classe unique par bâtiment se trompe pour presque tous les logements
    dès qu'un immeuble en compte plusieurs — mesuré : deux fois sur trois les
    classes diffèrent. La fiche remise à un acheteur ne peut pas porter cette
    approximation sans la nommer.

    Vide s'il n'y a qu'un diagnostic : la fiche a déjà raison dans ce cas.
    """
    if not e or not e.get("diagnostics"):
        return ""
    parts = " · ".join(f"{c} : {n}" for c, n in (e.get("repartition") or {}).items())
    titre = (T("{n} diagnostics connus à cette adresse, tous en {c}.").format(
                 n=e['diagnostics'], c=e['classe_min'])
             if e.get("identiques") else
             T("{n} diagnostics connus à cette adresse : de {a} à {b}.").format(
                 n=e['diagnostics'], a=e['classe_min'], b=e['classe_max']))
    couv = (T(" L'immeuble compte {n} logements.").format(n=e['logements_batiment'])
            if e.get("logements_batiment") else "")
    # La liste des logements, pour que le lecteur RECONNAISSE le sien.
    #
    # On ne prétend pas désigner son lot — le DPE ne porte ni numéro de lot ni
    # étage fiable. On lui donne les deux clés qu'il possède : sa surface, lue
    # sur l'annonce, et le numéro de DPE que le vendeur lui remet
    # obligatoirement. Et on dit, LIGNE PAR LIGNE, quand la surface ne tranche
    # pas — ce qui n'arrive que dans un cas sur cinq.
    # UN BLOC PAR DPE.
    #
    # Un tableau suivi des caractéristiques détaillées d'un seul logement se
    # lisait comme « trois diagnostics, une seule date ». Chaque diagnostic a
    # sa date, sa consommation, son coût et son isolation : il lui faut son
    # bloc.
    blocs = []
    # Fiche d'un LOGEMENT (#322) : n'imprimer QUE son bloc. La marque verte au
    # milieu de vingt blocs ne suffisait pas — l'opérateur a lu « la fiche de
    # tout l'immeuble ». Les autres diagnostics deviennent une ligne.
    rangs = e.get("logements") or []
    autres = 0
    if dpe_cible:
        gardes = [l for l in rangs if l.get("numero_dpe") == dpe_cible]
        autres = len(rangs) - len(gardes)
        rangs = gardes
    for l in rangs:
        m2 = l.get("surface_m2")
        # Fiche CIBLÉE (#311) : le logement choisi prend la marque verte, et le
        # représentatif redevient une ligne comme les autres — deux mises en
        # avant se liraient comme deux vérités.
        if dpe_cible:
            est_repr = l.get("numero_dpe") == dpe_cible
        else:
            est_repr = bool(dpe_representatif and l.get("numero_dpe") == dpe_representatif)
        isolation = " · ".join(x for x in (
            T("enveloppe {v}").format(v=l['isolation_enveloppe']) if l.get("isolation_enveloppe") else "",
            T("menuiseries {v}").format(v=l['isolation_menuiseries']) if l.get("isolation_menuiseries") else "",
        ) if x)
        marque = (T("seul logement de cette surface") if l.get("identifiable")
                  else T("{n} logements de cette surface — indiscernables").format(
                      n=l.get('memes_surfaces')))
        # Nom distinct de `titre` : celui-ci porte la phrase d'introduction de
        # la section, et la réutiliser dans la boucle l'écrasait — la fiche
        # rendue affichait « 7.6 m² La classe ci-dessus est... » au lieu de
        # « 3 diagnostics connus à cette adresse : de D à G. »
        entete = (f"{m2} m²" if m2 is not None else T("Logement"))
        blocs.append(
            f'<div class="logement{" repr" if est_repr else ""}">'
            f'<div class="logement-t"><strong>{T("{e} — classe {c}").format(e=entete, c=l.get("classe"))}</strong>'
            f'{(T(" · le logement de cette fiche") if dpe_cible else T(" · classe affichée ci-dessus")) if est_repr else ""}</div>'
            "<table>"
            + _row(T("Établi le"), l.get("etabli_le"))
            + _row(T("Consommation"), l.get("conso_kwh_m2y") and round(l["conso_kwh_m2y"]), T(" kWh/m²/an"))
            + _row(T("GES"), l.get("ges_kgco2_m2y") and round(l["ges_kgco2_m2y"]), T(" kgCO₂/m²/an"))
            + _row(T("Coût annuel"), _eur(l["cout_annuel_eur"]) + T(" €/an") if l.get("cout_annuel_eur") else None)
            + _row(T("Isolation"), isolation or None)
            + _row(T("N° DPE"), l.get("numero_dpe"))
            + "</table>"
            + f'<p class="meta">{marque}</p></div>')
    table = ""
    if blocs:
        renvoi = ((T('<p class="meta">Les {n} autres diagnostics de '
                     "l'immeuble figurent sur la fiche bâtiment.</p>").format(n=autres)
                   if autres > 1
                   else T('<p class="meta">L\'autre diagnostic de l\'immeuble '
                          "figure sur la fiche bâtiment.</p>"))
                  if autres else T("""
<p class="meta">Retrouvez le logement concerné par sa surface, ou par le numéro
de DPE que le vendeur remet obligatoirement — il est vérifiable sur
l'observatoire de l'ADEME.</p>"""))
        table = "".join(blocs) + renvoi
    phrase_classe = (T("La classe ci-dessus est celle du logement choisi pour "
                       "cette fiche.") if dpe_cible else
                     T("La classe ci-dessus est celle du logement représentatif "
                       "du bâtiment, pas celle de tous."))
    repartition = T("Répartition — {parts}. Source : ADEME, observatoire DPE.\n"
                    "Seuls les logements diagnostiqués figurent : c'est un minimum observé, pas un\n"
                    "inventaire de l'immeuble.").format(parts=parts)
    return f"""
<div class="ban">{titre} {phrase_classe}{couv}</div>
<p class="meta">{repartition}</p>{table}"""


def _local_taxes_html(t: dict) -> str:
    """Recurring local taxes (#193) — the other cost sheet buyers budget."""
    if not t:
        return ""
    yr = f" ({t['year']})" if t.get("year") else ""
    note = T("Taux globaux (commune + intercommunalité + syndicats), dernier exercice\n"
             "publié (DGFiP). La taxe due dépend de la valeur locative cadastrale du bien.")
    return f"""
<h2>{T("Fiscalité locale")}{yr}</h2>
<table>
  {_row(T("Taxe foncière (bâti), taux global"), t.get("property_tax_built_pct"), " %")}
  {_row(T("Taxe ordures ménagères (TEOM)"), t.get("waste_tax_pct"), " %")}
  {_row(T("Taxe foncière (non bâti)"), t.get("property_tax_unbuilt_pct"), " %")}
  {_row(T("Intercommunalité"), t.get("intercommunalite"))}
</table>
<p class="meta">{note}</p>"""


def _commune_html(c: dict) -> str:
    """La commune au sens civil, et le nom qu'elle portait avant (#275).

    Un acte ancien nomme parfois une commune qui n'existe plus. Et quand rien
    n'a bougé, le dire — daté et sourcé — vaut aussi la peine.

    Les réserves de la source sont reprises telles quelles : reprendre ses
    chiffres sans ses réserves affirmerait plus qu'elle ne le fait.
    """
    if not c or not c.get("nom"):
        return ""
    avant = (_row(T("Auparavant"),
                  T("{nom}, jusqu'au {date}").format(nom=c['precedent']['nom'],
                                                     date=c['precedent']['jusqu_au_fr']))
             if c.get("precedent") else "")
    reserves = list(c.get("limites") or []) + [
        d.get("texte") for d in (c.get("non_etablis") or []) if d.get("texte")]
    credits = " ; ".join(
        f"{a.get('attribution')} ({a.get('license')})"
        for a in (c.get("attribution") or []) if a.get("attribution"))
    credits_html = ('<p class="meta">' + T("Source : {credits}.").format(credits=credits)
                    + '</p>') if credits else ""
    return f"""
<h2>{T("Commune")}</h2>
<table>
  {_row(T("Commune"), f"{c['nom']} ({c['code']})")}
  {_row(T("Nom et limites inchangés depuis"), c.get("depuis_fr"))
    if c.get("existe_encore") else
    _row(T("A cessé d'exister le"), c.get("jusqu_au_fr"))}
  {avant}
  {_row(T("Données arrêtées au"), c.get("arret_des_donnees_fr"))}
</table>
{f'<p class="meta">{" ".join(reserves)}</p>' if reserves else ""}
{credits_html}"""


def _schools_html(sc: dict) -> str:
    """Nearest schools (#194) — proximity, NOT the carte scolaire."""
    if not sc:
        return ""
    rows = "".join(
        _row(f"{s.get('type') or T('Établissement')} · {s.get('statut') or ''}".strip(" ·"),
             f"{s.get('name')} ({s.get('distance_m')} m)")
        for s in (sc.get("nearest") or []))
    if not rows:
        return ('<h2>' + T("Écoles à proximité") + '</h2><p class="meta">'
                + T("Aucun établissement recensé à moins de 2 km (annuaire de l'éducation).")
                + '</p>')
    note = T("Distances à vol d'oiseau (annuaire de l'éducation). La proximité ne vaut\n"
             "pas sectorisation: la carte scolaire dépend de la commune.")
    return f"""
<h2>{T("Écoles à proximité ({n} à moins de 2 km)").format(n=sc.get('within_2km'))}</h2>
<table>{rows}</table>
<p class="meta">{note}</p>"""


def _official_dpe_html(od: dict) -> str:
    """Official-DPE substance (#189): the fiche carries what the legal document
    carries — number, validity, surface, ANNUAL € COSTS, insulation quality,
    systems — honestly framed as the group's representative dwelling."""
    if not od or not od.get("dpe_number"):
        return ""
    ins = od.get("insulation") or {}
    cost = od.get("annual_cost_eur")
    cost_txt = (_eur(cost) + T(" €/an")) if cost else None
    note = T("Données du DPE officiel du logement représentatif du bâtiment (Observatoire\n"
             "DPE, ADEME). Dans un immeuble, les autres logements peuvent différer. Coûts estimés\n"
             "aux prix de l'énergie en vigueur à la date du diagnostic.")
    return f"""
<h2>{T("DPE officiel (logement représentatif)")}</h2>
<table>
  {_row(T("N° DPE (ADEME)"), od.get("dpe_number"))}
  {_row(T("Établi le"), od.get("established_on"))}
  {_row(T("Valable jusqu'au"), od.get("valid_until"), T(" (validité légale: 10 ans)"))}
  {_row(T("Surface habitable"), od.get("surface_habitable_m2"), " m²")}
  {_row(T("Coût annuel d'énergie estimé"), cost_txt)}
  {_row(T("Chauffage"), od.get("heating"))}
  {_row(T("Eau chaude sanitaire"), od.get("hot_water"))}
  {_row(T("Énergies"), " + ".join(od.get("energies") or []) or None)}
  {_row(T("Isolation: enveloppe"), ins.get("enveloppe"))}
  {_row(T("Isolation: menuiseries"), ins.get("menuiseries"))}
  {_row(T("Isolation: plancher bas"), ins.get("plancher_bas"))}
  {_row(T("Isolation: plancher haut"), ins.get("plancher_haut"))}
</table>
<p class="meta">{note}</p>"""


def _water_network_html(wn: dict) -> str:
    """Commune drinking-water rows (#171): rendement du réseau + prix."""
    if not wn:
        return ""
    yr = f" ({wn['year']})" if wn.get("year") else ""
    note = T("Indicateurs du service public d'eau potable de la commune (SISPEA / OFB),\n"
             "dernière année publiée. Un rendement de 70 % signifie que 30 % de l'eau potable\n"
             "produite est perdue avant d'arriver au robinet.")
    return f"""
<h2>{T("Eau potable (commune)")}</h2>
<table>
  {_row(T("Rendement du réseau") + yr, wn.get("efficiency_pct"), " %")}
  {_row(T("Part perdue en fuites"), wn.get("losses_pct"), " %")}
  {_row(T("Prix de l'eau (120 m³)"), wn.get("price_eur_m3"), " €/m³")}
</table>
<p class="meta">{note}</p>"""


def _groundwater_html(gw: dict) -> str:
    """Water-table section (#119). Honest-data: measurement is at the nearest
    piezometer, never presented as on-parcel; absent block -> no section."""
    if not gw:
        return ""
    if not gw.get("available"):
        return ('<h2>' + T("Eau souterraine") + '</h2><p class="meta">'
                + (gw.get("note") or T("Donnée indisponible.")) + '</p>')
    station = gw.get("station_code_bss") or "—"
    if gw.get("station_commune"):
        station += f" ({gw['station_commune']})"
    dist = gw.get("station_distance_m")
    return f"""
<h2>{T("Eau souterraine")}</h2>
<table>
  {_row(T("Profondeur de la nappe"), gw.get("water_table_depth_m"), T(" m sous le sol"))}
  {_row(T("Niveau piézométrique"), gw.get("level_masl"), " m NGF")}
  {_row(T("Mesuré le"), (gw.get("measured_on") or "")[:10] or None)}
  {_row(T("Piézomètre le plus proche"), station)}
  {_row(T("Distance du bâtiment"), dist, " m")}
</table>
<p class="meta">{gw.get("note") or ""} {gw.get("well_regulation") or ""}</p>"""


_TYPEZONE_LABELS = {
    "U": "Zone urbaine", "AU": "Zone à urbaniser",
    "A": "Zone agricole", "N": "Zone naturelle",
}


def _urbanisme_html(data: dict) -> str:
    """Urbanisme section (#376): the parcel's PLU zone (Géoportail de l'Urbanisme),
    and — as an interim flood pointer (#377) — a note when Géorisques reports an
    inondation risk. Both parts reuse data already in the record, no re-fetch.

    Coverage honesty: the PLU part renders ONLY when a digitised zone is present;
    a parcel without one shows nothing, never a "no constraint" statement."""
    plu = data.get("urbanisme") or {}
    risks = data.get("area_risks") or {}
    parts = []
    if plu.get("libelle") or plu.get("typezone"):
        cat = _TYPEZONE_LABELS.get(plu.get("typezone"))
        cat_txt = T(cat) if cat else None
        libelle = plu.get("libelle")
        zone_val = f"<strong>{libelle}</strong>" if libelle else None
        note = T("Zonage issu du plan local d'urbanisme (Géoportail de l'Urbanisme, GPU). "
                 "Document de référence : {ref}. À recouper avec le règlement écrit de la zone.").format(
                     ref=plu.get("partition") or "—")
        verify = T("Vérifier sur le Géoportail de l'Urbanisme")
        parts.append(f"""
<h2>{T("Urbanisme (PLU)")}</h2>
<table>
  {_row(plu.get('libelong') or T("Zone du PLU"), zone_val)}
  {_row(T("Catégorie"), cat_txt)}
</table>
<p class="meta">{note} <a href="https://www.geoportail-urbanisme.gouv.fr/">{verify}</a></p>""")
    # Zone réglementaire PPRI (#377) : la couche nationale Géorisques porte la
    # couleur — on l'affiche quand elle est là ; sinon repli honnête sur la
    # simple présence d'un risque inondation, sans inventer de couleur.
    ppri = data.get("ppri") or {}
    couleur = ppri.get("couleur")  # "bleue" / "rouge" / None
    if ppri.get("code"):
        if couleur == "bleue":
            phrase = T("Parcelle en zone BLEUE du PPRI inondation : risque modéré, "
                       "constructible sous conditions (zone {code}).")
        elif couleur == "rouge":
            phrase = T("Parcelle en zone ROUGE du PPRI inondation : risque fort, "
                       "secteur très contraint (zone {code}).")
        else:
            phrase = T("Parcelle dans une zone réglementée du PPRI inondation "
                       "(zone {code}).")
        etat_raw = (ppri.get("etat") or "").lower()
        detail = T("{nom}, {etat}{date}.").format(
            nom=ppri.get("nom_ppr") or "—",
            etat=T(etat_raw) if etat_raw else T("statut inconnu"),
            date=(T(" le {d}").format(d=ppri["date_approbation"])
                  if ppri.get("date_approbation") else ""))
        lien = ppri.get("url_reglement")
        verif = (f' <a href="{lien}">{T("Consulter le règlement de la zone")}</a>'
                 if lien else "")
        parts.append(
            f'<p class="meta">{phrase.format(code=ppri.get("code"))} {detail}'
            f' ({T("source")} Géorisques){verif}</p>')
    elif any("inondation" in str(r).lower()
             for r in (risks.get("risques_naturels") or [])):
        line = T("Parcelle en zone inondable (source Géorisques). La couleur réglementaire "
                 "du PPRI (zone bleue / rouge) n'est pas cartographiée à ce point : consulter "
                 "le PPRI de la commune.")
        parts.append(f'<p class="meta">{line} '
                     f'<a href="https://www.georisques.gouv.fr/">{T("Géorisques")}</a></p>')
    return "".join(parts)


def _cover_html(data: dict, aerial_img: str | None = None,
                map_img: str | None = None) -> str:
    """Cover page (#PDF restyle): a full-width hero image, the building address
    as a large title, a big DPE badge and an EcoBuilding brand line.

    Content only — no datum is invented here, everything already sits in
    `data`, and every visible string goes through `T()`. Renders correctly with
    no images (solid EcoBuilding-green banner, no broken <img>) and with no DPE
    (badge simply omitted). The DPE class / range logic mirrors the body badge
    so the cover never contradicts the page that follows."""
    b = (data.get("buildings") or [{}])[0] or {}
    e = b.get("energy") or {}
    cible = data.get("dpe_cible") or None
    spread = data.get("dpe_spread") or {}
    cls = (e.get("dpe_class") or "?").upper()
    if cible:
        cls = (cible.get("classe") or "?").upper()
    color = DPE_COLORS.get(cls, "#999")
    eventail = bool(not cible and not spread.get("identiques")
                    and spread.get("classe_min") and spread.get("classe_max"))
    badge = ""
    if e.get("dpe_class") or cible:
        if eventail:
            c1 = DPE_COLORS.get(spread["classe_min"], "#999")
            c2 = DPE_COLORS.get(spread["classe_max"], "#999")
            badge = ('<span class="dpe cover-dpe" style="background:linear-gradient('
                     '100deg,' + c1 + ' 0%,' + c2 + ' 100%)">'
                     + spread["classe_min"] + '&nbsp;-&nbsp;' + spread["classe_max"]
                     + '</span>')
        else:
            dark = ';color:#333' if cls == "D" else ""
            badge = ('<span class="dpe cover-dpe" style="background:' + color + dark
                     + '">' + cls + '</span>')
        badge = '<div class="cover-badge">' + badge + '</div>'
    address = (data.get("query", {}).get("address")
               or b.get("address") or T("Adresse inconnue"))
    commune = (data.get("area_risks") or {}).get("commune")
    commune_html = f'<div class="cover-commune">{commune}</div>' if commune else ""
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    if aerial_img:
        hero = f'<div class="cover-hero"><img src="{aerial_img}"/></div>'
    elif map_img:
        hero = f'<div class="cover-hero"><img src="{map_img}"/></div>'
    else:
        hero = '<div class="cover-hero cover-hero-fallback"></div>'
    return f"""
<style>
  .cover {{ page-break-after: always; break-after: page; }}
  .cover-hero {{ width: 100%; height: 90mm; border-radius: 8pt; overflow: hidden;
                 line-height: 0; background: #2b7a4b; }}
  .cover-hero img {{ width: 100%; height: 90mm; object-fit: cover; }}
  .cover-hero-fallback {{ background: linear-gradient(135deg, #2b7a4b 0%, #1f5c38 100%); }}
  .cover-body {{ padding: 16mm 2mm 0; }}
  .cover-commune {{ font-size: 12pt; color: #2b7a4b; font-weight: bold;
                    letter-spacing: .04em; text-transform: uppercase; }}
  .cover-title {{ font-size: 28pt; line-height: 1.15; font-weight: bold;
                  color: #1a1a1a; margin: 4pt 0 14pt; }}
  .cover-badge {{ margin: 8pt 0 0; }}
  .cover-dpe {{ font-size: 42pt; min-width: 60pt; padding: 8pt 18pt;
                border-radius: 8pt; }}
  .cover-brand {{ margin-top: 22mm; border-top: 2pt solid #2b7a4b;
                  padding-top: 8pt; }}
  .cover-brand .n {{ font-size: 15pt; font-weight: bold; color: #2b7a4b; }}
  .cover-brand .s {{ font-size: 10.5pt; color: #666; }}
  .cover-brand .d {{ font-size: 8.5pt; color: #999; margin-top: 2pt; }}
</style>
<div class="cover">
  {hero}
  <div class="cover-body">
    {commune_html}
    <div class="cover-title">{address}</div>
    {badge}
    <div class="cover-brand">
      <span class="n">EcoBuilding</span> <span class="s">· {T("fiche bâtiment")}</span>
      <div class="d">{now}</div>
    </div>
  </div>
</div>
"""


def build_report_pdf(data: dict, photos: list | None = None, map_img: str | None = None,
                     aerial_img: str | None = None, aerial_parcels: str | None = None,
                     aerial_outline: str | None = None,
                     quartier_img: str | None = None, lang: str = "fr") -> bytes:
    _LANGUE.set("en" if lang == "en" else "fr")
    return HTML(string=_report_html(data, photos, map_img, aerial_img,
                                    aerial_parcels, aerial_outline,
                                    quartier_img, lang=lang)).write_pdf()


def _report_html(data: dict, photos: list | None = None, map_img: str | None = None,
                 aerial_img: str | None = None, aerial_parcels: str | None = None,
                 aerial_outline: str | None = None,
                 quartier_img: str | None = None, lang: str = "fr") -> str:
    _LANGUE.set("en" if lang == "en" else "fr")
    b = (data.get("buildings") or [{}])[0]
    e = b.get("energy") or {}
    ban = e.get("rental_ban") or {}
    risks = data.get("area_risks") or {}
    solar = b.get("solar") or {}
    gw = data.get("groundwater") or {}
    pv = data.get("solar_pv") or {}
    cls = (e.get("dpe_class") or "?").upper()
    color = DPE_COLORS.get(cls, "#999")
    # Le badge dit l'EVENTAIL quand les logements de l'immeuble different
    # (#287). Une lettre unique est l'element le plus visible du document, et
    # elle a l'air categorique : mesure, elle est fausse deux fois sur trois
    # des qu'un immeuble porte plusieurs diagnostics. Le degrade va de la
    # couleur de la meilleure classe a celle de la pire.
    spread = data.get("dpe_spread") or {}
    # Fiche CIBLÉE (#311) : un logement précis a été choisi dans le panneau.
    # Le document parle alors de LUI — badge, échelles, interdiction de
    # location — et le bâtiment devient le contexte, plus l'inverse.
    cible = data.get("dpe_cible") or None
    eventail = bool(not cible and not spread.get("identiques")
                    and spread.get("classe_min") and spread.get("classe_max"))
    if cible:
        cls = (cible.get("classe") or "?").upper()
        color = DPE_COLORS.get(cls, "#999")
    # Les échelles marquent CHAQUE classe présente à l'adresse (#307), pas
    # seulement celle du logement représentatif — sinon l'élément le plus
    # officiel de la page dément les blocs affichés juste au-dessus.
    comptes_energie = dict(spread.get("repartition") or {}) if eventail else None
    comptes_ges = None
    if eventail:
        comptes_ges = {}
        for l in spread.get("logements") or []:
            g = l.get("ges_kgco2_m2y")
            if g is not None:
                k = _ges_class(g)
                comptes_ges[k] = comptes_ges.get(k, 0) + 1
        comptes_ges = comptes_ges or None
    if cible:
        badge = '<span class="dpe">' + cls + '</span>'
    elif eventail:
        c1 = DPE_COLORS.get(spread["classe_min"], "#999")
        c2 = DPE_COLORS.get(spread["classe_max"], "#999")
        badge = ('<span class="dpe" style="background:linear-gradient(100deg,'
                 + c1 + ' 0%,' + c2 + ' 100%);padding-left:10px;'
                 'padding-right:10px">'
                 + spread["classe_min"] + '&nbsp;-&nbsp;' + spread["classe_max"]
                 + '</span>')
    else:
        badge = '<span class="dpe">' + cls + '</span>'
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    address = data.get("query", {}).get("address") or b.get("address") or T("Adresse inconnue")

    ban_html = ""
    if e.get("dpe_class"):
        if ban.get("rental_ban_date"):
            ban_html = ('<div class="ban warn">'
                        + T('⚠ Location interdite à partir de '
                            '<strong>{y}</strong> (loi Climat &amp; Résilience)').format(
                                y=ban["rental_ban_date"][:4])
                        + '</div>')
        else:
            ban_html = ('<div class="ban ok">'
                        + T('Aucune interdiction de location prévue pour cette classe')
                        + '</div>')

    zone_risks = ", ".join((risks.get("risques_naturels") or []) + (risks.get("risques_technologiques") or [])) or None
    conso = e.get("consumption_kwh_m2y")
    ges = e.get("ghg_kgco2_m2y")
    if cible:
        conso = cible.get("conso_kwh_m2y")
        ges = cible.get("ges_kgco2_m2y")
        # L'interdiction de location se recalcule pour SA classe (loi Climat &
        # Résilience) : un G dans un immeuble « sans interdiction » est
        # exactement l'écart qui intéresse un acheteur.
        seuils = {"G": "2025", "F": "2028", "E": "2034"}
        if cls in seuils:
            ban_html = ('<div class="ban warn">'
                        + T('⚠ Location interdite à partir de '
                            '<strong>{y}</strong> (loi Climat &amp; Résilience) '
                            'pour ce logement').format(y=seuils[cls])
                        + '</div>')
        else:
            ban_html = ('<div class="ban ok">'
                        + T('Aucune interdiction de location '
                            'prévue pour la classe de ce logement')
                        + '</div>')

    cible_banner = ""
    if cible:
        cible_banner = ('<div class="ban" style="background:#e8f5e9;color:#2b7a4b">'
                        + T("<strong>Fiche d'un logement</strong> : "
                            "{m2} m² · classe {c} · N° DPE {n}. "
                            "Les autres logements de l'immeuble ne sont pas l'objet de ce document.")
                        .format(m2=cible.get("surface_m2"), c=cls, n=cible.get("numero_dpe"))
                        + '</div>')

    labels_html = ""
    if e.get("dpe_class") or cible:
        if eventail:
            # « diagnostics », pas « logements » : un logement est re-diagnostiqué à
            # chaque vente, l'adresse de #312 en porte 23 pour 14 logements.
            note_classes = ('<p class="meta">'
                            + T('Classes marquées : celles des {n} diagnostics connus à '
                                'cette adresse. La valeur chiffrée est celle '
                                'du logement représentatif.').format(n=spread.get("diagnostics"))
                            + '</p>')
        elif cible:
            note_classes = ('<p class="meta">'
                            + T('Classe marquée : celle du logement choisi '
                                '(N° DPE {n}).').format(n=cible.get("numero_dpe"))
                            + '</p>')
        else:
            note_classes = ""
        labels_html = ('<table class="labels"><tr>'
                       '<td><div class="lbl-title">'
                       + T('Étiquette énergie <span>(kWh/m²/an, énergie primaire)</span>')
                       + '</div>'
                       + _scale(cls, DPE_COLORS, f"{round(conso)}" if conso else "",
                                counts=comptes_energie)
                       + '</td><td><div class="lbl-title">'
                       + T('Étiquette climat <span>(kgCO₂/m²/an)</span>') + '</div>'
                       + _scale(_ges_class(ges), GES_COLORS, f"{round(ges)}" if ges else "",
                                counts=comptes_ges)
                       + '</td></tr></table>' + note_classes)

    quartier_html = ""
    if quartier_img:
        quartier_html = (f'<img src="{quartier_img}" style="width:100%;border-radius:4pt;margin:4pt 0"\n'
                         '     alt="' + T("Carte du quartier : le bâtiment et les écoles") + '" />\n'
                         '<p class="meta">'
                         + T("Le bâtiment épinglé en vert, les écoles nommées sur la carte.\n"
                             "La liste disait combien ; la carte dit lesquelles, et où — proximité,\n"
                             "jamais sectorisation (#324).")
                         + '</p>')

    footer_txt = T("Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.\n"
                   "  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un\n"
                   "  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)\n"
                   "  réglementaire. Une question sur cette fiche : contact@confinia.io")

    html = f"""
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  body {{ font-family: 'DejaVu Sans', sans-serif; font-size: 10.5pt; color: #222;
         line-height: 1.45; }}
  header {{ border-bottom: 2px solid #2b7a4b; padding-bottom: 6px; margin-bottom: 14px; }}
  .brand {{ font-size: 14pt; font-weight: bold; color: #2b7a4b; }}
  .doctitle {{ font-size: 11pt; color: #555; }}
  h1 {{ font-size: 15pt; margin: 12px 0 3px; }}
  .meta {{ font-size: 8.5pt; color: #777; }}
  .dpe {{ display: inline-block; min-width: 26pt; text-align: center; font-weight: bold;
         color: #fff; background: {color}; border-radius: 4pt; padding: 4pt 8pt; font-size: 15pt; }}
  {'.dpe { color: #333; }' if cls == 'D' else ''}
    .logement {{ border: 1pt solid #e0e0e0; border-radius: 5pt; padding: 5pt 7pt;
    margin: 5pt 0; break-inside: avoid; }}
  .logement.repr {{ border-color: #2b7a4b; background: #f5faf7; }}
  .logement-t {{ font-size: 9.5pt; margin-bottom: 2pt; }}
  .logement table {{ margin: 0; }}
.ban {{ margin: 6pt 0; padding: 6pt 8pt; border-radius: 4pt; font-size: 10pt; }}
  .ban.warn {{ background: #fdecea; color: #b3261e; }}
  .ban.ok {{ background: #e8f5e9; color: #2b7a4b; }}
  h2 {{ font-size: 11.5pt; text-transform: uppercase; letter-spacing: .04em; color: #2b7a4b;
       background: #eef6f1; border-left: 3pt solid #2b7a4b;
       padding: 5pt 9pt; margin: 22pt 0 9pt;
       /* Un titre ne reste JAMAIS seul en bas de page. « Photos du lieu »
          s'affichait suivi d'un grand blanc, son contenu rejeté à la page
          suivante : le lecteur en concluait que la fiche était incomplète,
          alors que les photos étaient là, une page plus loin. */
       break-after: avoid; page-break-after: avoid; }}
  table {{ width: 100%; border-collapse: collapse; table-layout: fixed;
          margin: 4pt 0 10pt; }}
  td {{ padding: 3pt 4pt; border-bottom: 0.5pt dashed #eee; vertical-align: top;
       overflow-wrap: anywhere; word-break: break-word; }}
  td.k {{ color: #666; width: 45%; }}
  /* Multi-column tables: the 45% key width is per-cell and would overflow a
     fixed layout — let the auto algorithm size them. */
  table.sales {{ table-layout: auto; }}
  table.sales td.k {{ width: auto; }}
  footer {{ margin-top: 18pt; font-size: 7.5pt; color: #888; border-top: 0.5pt solid #ccc; padding-top: 6pt; }}
  .labels {{ margin: 8pt 0 2pt; }}
  .labels td {{ width: 50%; border: none; padding: 0 8pt 0 0; }}
  .lbl-title {{ font-size: 8.5pt; font-weight: bold; margin-bottom: 3pt; }}
  .lbl-title span {{ font-weight: normal; color: #777; }}
  .scale .bar {{ padding: 2.2pt 5pt; margin: 1.2pt 0; border-radius: 0 3pt 3pt 0; font-size: 8.5pt; }}
  .scale .bar strong {{ font-size: 9.5pt; }}
  .scale .bar.active {{ outline: 1.5pt solid #333; font-size: 10pt; }}
  .scale .bar .val {{ float: right; font-weight: bold; }}
</style>
{_cover_html(data, aerial_img, map_img)}
<header>
  <div class="brand">EcoBuilding</div>
  <!-- « normalisée » promettait une norme qui n'existe pas : ce document est
       assemblé à partir de données ouvertes, il ne se conforme à aucun
       référentiel. Dire ce qu'il EST — formaté par nous, sourcé chez l'État —
       vaut mieux que d'emprunter l'autorité d'une norme. -->
  <div class="doctitle">{T("Fiche LOGEMENT formatée et sourcée — données ouvertes") if cible else T("Fiche bâtiment formatée et sourcée — données ouvertes")}</div>
</header>
<h1>{address}</h1>
{cible_banner}
{_principal_address_note(address, b)}
<p class="meta">{T("Identifiant BDNB : {id} · Générée le {now} · ecobuilding.confinia.io").format(id=b.get("bdnb_id") or "—", now=now)}</p>

<h2>{T("Énergie (DPE)")}{T(" — logement {m2} m², classe {c}").format(m2=cible.get("surface_m2"), c=cls) if cible else ""}</h2>
<p>{badge}&nbsp;&nbsp;{T("{v} kWh/m²/an").format(v=round(conso)) if conso else T("Aucun DPE enregistré dans la BDNB pour ce bâtiment")}</p>
{ban_html}
{_dpe_spread_html(data.get("dpe_spread") or {}, (data.get("official_dpe") or {}).get("dpe_number"),
                  dpe_cible=(cible or {}).get("numero_dpe"))}
{labels_html}
<table>
  {_row(T("Date du DPE"), (e.get("dpe_date") or "")[:10] or None)}
  {_row(T("Émissions GES"), round(ges) if ges else None, T(" kgCO₂/m²/an"))}
</table>
{"" if cible else _official_dpe_html(data.get("official_dpe") or {})}

<h2>{T("Bâtiment")}</h2>
<table>
  {_row(T("ID-RNB (référentiel national)"), b.get("rnb_id"))}
  {_row(T("Année de construction"), b.get("construction_year"))}
  {_row(T("Hauteur moyenne"), b.get("height_m"), " m")}
  {_row(T("Logements"), b.get("dwellings"))}
  {_row(T("Matériaux des murs"), b.get("wall_material"))}
  {_row(T("Matériaux du toit"), b.get("roof_material"))}
</table>
{_dia_html(data.get("market_dia"))}

<h2>{T("Risques")}</h2>
<table>
  {_row(T("Retrait-gonflement des argiles"), (b.get("risks") or {}).get("clay_shrink_swell"))}
  {_row(T("Risques recensés dans la zone"), zone_risks)}
  {_row(T("Rapport Géorisques"), risks.get("report_url"))}
</table>

{_urbanisme_html(data)}
{_groundwater_html(gw)}
{_water_network_html(data.get("water_network") or {})}

<h2>{T("Solaire")}</h2>
<table>
  {_row(T("Favorable au solaire thermique"), {True: T("oui"), False: T("non")}.get(solar.get("thermal_favourable")))}
  {_row(T("Potentiel annuel estimé"), solar.get("thermal_potential_kwh_y"), T(" kWh/an"))}
  {_row(T("Productible photovoltaïque (PVGIS)"), round(pv["yield_kwh_per_kwc_y"]) if pv.get("yield_kwh_per_kwc_y") else None, T(" kWh/an par kWc installé"))}
  {_row(T("Irradiation (inclinaison optimale)"), round(pv["irradiation_kwh_m2_y"]) if pv.get("irradiation_kwh_m2_y") else None, T(" kWh/m²/an"))}
</table>
{f'<p class="meta">{pv["assumptions"]}</p>' if pv.get("assumptions") else ""}

{_prices_html(data.get("prices"), fiche_logement=bool(cible))}
{_local_taxes_html(data.get("local_taxes") or {})}
{_schools_html(data.get("schools") or {})}
{quartier_html}
{_commune_html(data.get("commune") or {})}

<footer>
  {footer_txt}
</footer>
{_context_page(data, photos, map_img, aerial_img, aerial_parcels, aerial_outline)}
{_traceability_annex(data, photos)}
"""
    return html


def _target_overlay(outline: str | None) -> str:
    """Le tracé posé sur la photo.

    DEUX traits superposés : un large et sombre en dessous, un fin et clair
    au-dessus. Un trait d'une seule couleur disparaît — le clair sur une toiture
    en tuiles claires, le sombre sur des arbres. Le liseré garantit le contraste
    quel que soit ce qu'il y a dessous.
    """
    if outline:
        shape = (f'<polygon points="{outline}" fill="rgba(0,224,255,0.12)" '
                 'stroke="#00303a" stroke-width="1.4" stroke-linejoin="round"/>'
                 f'<polygon points="{outline}" fill="none" '
                 'stroke="#00E0FF" stroke-width="0.7" stroke-linejoin="round"/>')
    else:
        # Sans géométrie, la photo est de toute façon centrée sur le point :
        # un réticule au centre vaut mieux qu'aucune indication.
        shape = ('<circle cx="50" cy="50" r="7" fill="none" stroke="#00303a" '
                 'stroke-width="1.6"/>'
                 '<circle cx="50" cy="50" r="7" fill="none" stroke="#00E0FF" '
                 'stroke-width="0.8"/>')
    return (f'<svg viewBox="0 0 100 100" preserveAspectRatio="none">{shape}</svg>')


def _context_page(data: dict, photos: list | None, map_img: str | None = None,
                  aerial_img: str | None = None, aerial_parcels: str | None = None,
                  aerial_outline: str | None = None) -> str:
    """Second PDF page: third-party context — a rendered DPE-3D map of the
    building (#88) + Panoramax imagery. Falls back to an OSM link when the map
    render is unavailable."""
    q = data.get("query", {})
    lon, lat = q.get("lon"), q.get("lat")
    address = q.get("address") or T("ce bâtiment")
    photos = photos or []
    def _pic(p):
        src = p.get("sd") or p.get("thumb")
        # 360° photospheres are equirectangular and warp on flat paper: crop to
        # a forward-facing central window (~90°x45°) instead of the full strip.
        # Non-360 photos are shown as-is. (True rectilinear reprojection = #81.)
        if p.get("is_360"):
            inner = f'<div class="crop"><img src="{src}"/></div>'
        else:
            inner = f'<img class="flat" src="{src}"/>'
        # Auteur et licence sous CHAQUE image : l'attribution est une obligation
        # des licences libres, pas une politesse — et elle dit au lecteur d'où
        # vient ce qu'il regarde.
        credit = " · ".join(x for x in (p.get("source", "Panoramax"),
                                        p.get("author"), p.get("licence", "CC-BY-SA")) if x)
        title = p.get("title")
        caption = f"{title} — {credit}" if title else credit
        return f'<div class="pic">{inner}<div class="cap">{caption}</div></div>'

    pics = "".join(_pic(p) for p in photos[:4] if p.get("sd") or p.get("thumb"))
    if not pics and lon is None:
        return ""
    osm = (f'<a href="https://www.openstreetmap.org/#map=19/{lat}/{lon}">'
           f'openstreetmap.org (19/{lat}/{lon})</a>' if lon is not None else "—")
    aerial_html = ""
    if aerial_img:
        cap = ((T("Photo aérienne IGN (BD ORTHO) et limites de parcelles (Parcellaire Express)")
                if aerial_parcels else T("Photo aérienne IGN (BD ORTHO)"))
               + T(" — Licence Ouverte. ")
               + (T("Le bâtiment concerné est entouré en cyan. ") if aerial_outline
                  else T("Le bâtiment concerné est au centre du repère. "))
               + T("Le terrain, les arbres, les annexes et les accès, que nulle donnée "
                   "structurée ne décrit."))
        aerial_html = (f'<h2>{T("Vue aérienne")}</h2><div class="aerial"><img class="map3d" src="{aerial_img}"/>'
                       + (f'<img class="parcels" src="{aerial_parcels}"/>' if aerial_parcels else '')
                       + _target_overlay(aerial_outline) + '</div>'
                       + f'<div class="cap">{cap}</div>')
    if map_img:
        map_html = (f'<img class="map3d" src="{map_img}"/>'
                    '<div class="cap">'
                    + T('Bâtiment ciblé en pleine opacité (voisins atténués), coloré par classe DPE. '
                        'Limites de parcelles en orange. '
                        'Zoom 18, inclinaison 60°. Fond : OpenStreetMap et contributeurs (ODbL) · Bâtiments &amp; DPE : BDNB (CSTB) '
                        '· Parcelles : IGN Parcellaire Express (Licence Ouverte).')
                    + '</div>')
    else:
        map_html = (f'<table><tr><td class="k" style="width:30%">{T("Voir la zone sur OSM")}</td>'
                    f'<td>{osm}</td></tr></table>')
    footer_txt = T("Imagerie : Panoramax (CC-BY-SA 4.0) et Wikimedia Commons, auteur et licence indiqués\n"
                   "  sous chaque photo. Cartographie : OpenStreetMap et contributeurs (ODbL).\n"
                   "  Informations de contexte, non contractuelles.")
    return f"""
<div style="page-break-before: always;"></div>
<header>
  <div class="brand">EcoBuilding</div>
  <div class="doctitle">{T("Contexte — sources tierces")}</div>
</header>
<h1>{address}</h1>
{aerial_html}
{(f'<section class="bloc"><h2>{T("Photos du lieu")}</h2>'
   f'<div class="pics">{pics}</div></section>') if pics else ''}
<h2>{T("Localisation — carte 3D (DPE)") if map_img else "OpenStreetMap"}</h2>
{map_html}
<footer>
  {footer_txt}
</footer>
<style>
  .map3d {{ width: 100%; border-radius: 4pt; margin-bottom: 3pt; }}
  /* Le contour est POSÉ sur la photo : sans lui, cinq pavillons d'un
     lotissement se ressemblent et le lecteur ne sait pas lequel est le sien. */
  .aerial {{ position: relative; line-height: 0; }}
  .aerial svg {{ position: absolute; top: 0; left: 0; width: 100%; height: 100%; }}
  /* Les limites de parcelles, posées sur la photo : « où s'arrête le terrain »
     est une des premières questions d'un acheteur. Sur le document, le numéro
     de parcelle a du sens — c'est la référence cadastrale, celle qu'un notaire
     emploie. À l'écran il ne servait à rien et masquait le reste. */
  .aerial .parcels {{ position: absolute; top: 0; left: 0; width: 100%;
                      height: 100%; border-radius: 4pt; opacity: 0.85; }}
  .map3d + .cap {{ font-size: 7.5pt; color: #888; margin-bottom: 4pt; }}
  .pics {{ display: flex; gap: 8pt; flex-wrap: wrap; }}
  /* Titre et photos SOLIDAIRES. `.pics` est un conteneur flex, que WeasyPrint
     traite comme insécable : il basculait donc en entier à la page suivante en
     laissant son titre derrière, suivi d'un grand blanc. `break-after: avoid`
     sur le titre n'y change rien — le moteur ne repousse pas la boîte qui
     précède. Les enfermer dans un même bloc les fait voyager ensemble.
     Si le bloc dépassait une page entière, la règle serait ignorée et l'on
     retomberait sur l'ancien comportement : quatre photos tiennent largement. */
  .bloc {{ break-inside: avoid; page-break-inside: avoid; }}
  .pic img.flat {{ width: 240pt; border-radius: 4pt; }}
  /* Central forward crop of an equirectangular 360 (2:1 image): box shows the
     central 1/4 width (90 deg) x 1/4 height (45 deg). */
  .pic .crop {{ width: 240pt; height: 120pt; overflow: hidden; border-radius: 4pt; }}
  .pic .crop img {{ width: 960pt; margin-left: -360pt; margin-top: -180pt; }}
  .pic .cap {{ font-size: 7pt; color: #888; }}
</style>"""


# English translations (#370). The FRENCH template string is the key, byte for
# byte (including embedded newlines and HTML tags); the value is the English
# rendering. Placeholders {x} and HTML tags are identical on both sides.
# Register: professional real-estate / property report. "DPE" is kept as the
# French certificate's proper name, glossed "(energy performance certificate)"
# where a section first needs it. Untranslated on purpose: dataset and licence
# proper names (BDNB, "Licence Ouverte", "Base Adresse Nationale"...), URLs,
# and every DATA value coming from upstream sources.
_EN = {
    # — Market activity (DIA)
    " — dont {n} au dernier trimestre": " — including {n} in the last quarter",
    "Dynamique du marché (DIA)": "Market activity (DIA pre-emption filings)",
    "Zone": "Area",
    "Mises en vente sur 12 mois": "Properties put up for sale over 12 months",
    "Prix médian demandé": "Median asking price",
    "Données {d} —\nMontpellier Méditerranée Métropole (Open Data).":
        "Data {d} —\nMontpellier Méditerranée Métropole (open data).",
    # — Sale prices (DVF)
    "Prix de vente (DVF)": "Sale prices (DVF)",
    "Données de prix indisponibles pour ce secteur : la base DVF ne couvre pas l'Alsace-Moselle ni Mayotte.":
        "Price data unavailable for this area: the DVF register does not cover Alsace-Moselle or Mayotte.",
    "Vente groupée : {desc}": "Bundled sale: {desc}",
    "(prix de l'ensemble)": "(price for the whole lot)",
    "Surface": "Floor area",
    "Montant": "Price",
    "Aucune vente récente enregistrée sur la parcelle.": "No recent sale recorded on this parcel.",
    "Ventes enregistrées sur la PARCELLE — pas nécessairement celles du logement de cette fiche.":
        "Sales recorded on the PARCEL — not necessarily those of the dwelling covered by this report.",
    " — parcelle": " — parcel",
    "Prix médian dans la commune : <strong>{med}</strong>":
        "Median price in the municipality: <strong>{med}</strong>",
    "€/m² indicatif, calculé sur les ventes d'un seul local. Transactions réelles enregistrées par la DGFiP.":
        "Indicative €/m², computed on single-unit sales. Actual transactions recorded by the DGFiP (French tax administration).",
    # — Provenance cards (traceability annex)
    "Clé de recherche": "Lookup key",
    "Date de référence": "Reference date",
    "Vérifier à la source": "Verify at the source",
    "Adresse": "Address",
    "Référentiel courant": "Current reference dataset",
    "Bâtiment, énergie (DPE), solaire": "Building, energy (DPE), solar",
    "Millésime {v} · Licence Ouverte 2.0": "Release {v} · Licence Ouverte 2.0 (French open licence)",
    "{d} (date du DPE)": "{d} (DPE date)",
    "Millésime {v}": "Release {v}",
    " · commune INSEE {c}": " · INSEE municipality code {c}",
    "Risques": "Risks",
    "Géorisques (BRGM / Ministère de la Transition écologique)":
        "Géorisques (BRGM / French Ministry of Ecological Transition)",
    "Consultation du {now}": "Looked up on {now}",
    "ventes {a}–{b}": "sales {a}–{b}",
    "fenêtre {w}": "window {w}",
    "Prix (DVF)": "Prices (DVF)",
    "DVF géolocalisé — Demandes de Valeurs Foncières (DGFiP / Etalab)":
        "Geolocated DVF — French property transaction register (DGFiP / Etalab)",
    "Fenêtre {w} · Licence Ouverte 2.0": "Window {w} · Licence Ouverte 2.0 (French open licence)",
    "parcelle cadastrale du bâtiment · commune INSEE {c}":
        "cadastral parcel of the building · INSEE municipality code {c}",
    "indisponible : l'Alsace-Moselle et Mayotte ne sont pas couvertes par la DVF":
        "unavailable: Alsace-Moselle and Mayotte are not covered by the DVF register",
    "DPE officiel": "Official DPE (energy performance certificate)",
    "Observatoire DPE (ADEME)": "DPE observatory (ADEME)",
    "(logement choisi)": "(selected dwelling)",
    "(logement représentatif BDNB)": "(BDNB representative dwelling)",
    "Fiscalité locale": "Local property taxes",
    "DGFiP — Fiscalité directe locale (data.economie.gouv.fr)":
        "DGFiP — Local direct taxation (data.economie.gouv.fr)",
    "insee_com = {c} · exercice {y}": "insee_com = {c} · tax year {y}",
    "exercice {y}": "tax year {y}",
    "Écoles": "Schools",
    "Annuaire de l'éducation (MENJ)": "French national school directory (MENJ)",
    "within_distance 2 km de {lat}, {lon}": "within_distance 2 km of {lat}, {lon}",
    "annuaire courant": "current directory",
    "Eau souterraine (nappe)": "Groundwater (water table)",
    "code BSS {c} · station à {d} m du bâtiment": "BSS code {c} · station {d} m from the building",
    "{d} (dernière mesure)": "{d} (latest reading)",
    "Eau potable (rendement du réseau)": "Drinking water (network efficiency)",
    "SISPEA — Observatoire des services publics d'eau (OFB)":
        "SISPEA — French water utilities observatory (OFB)",
    "commune INSEE {c} · indicateur P104.3": "INSEE municipality code {c} · indicator P104.3",
    "année {y} (dernière publiée)": "year {y} (latest published)",
    "Solaire photovoltaïque": "Solar photovoltaics",
    "PVGIS v5.2 (Joint Research Centre, Commission européenne)":
        "PVGIS v5.2 (Joint Research Centre, European Commission)",
    "© Union européenne": "© European Union",
    "base climatique PVGIS-SARAH2": "PVGIS-SARAH2 climate database",
    "Photos (contexte)": "Photos (context)",
    " et ": " and ",
    "CC-BY-SA / licences libres, voir chaque image": "CC-BY-SA / free licences, see each image",
    "photo id(s) : {ids}": "photo id(s): {ids}",
    "voir la visionneuse": "see the viewer",
    "Annexe — traçabilité des données": "Annex — data traceability",
    "D'où vient chaque donnée": "Where each piece of data comes from",
    "Ce rapport agrège des données ouvertes. Pour chaque donnée : la source,\n"
    "la version, la clé de recherche exacte et un lien pour vérifier directement à la source,\n"
    "sans avoir à faire confiance à EcoBuilding. Généré le {now}.":
        "This report aggregates open data. For each piece of data: the source, the version, "
        "the exact lookup key and a link to verify it directly at the source, without having "
        "to trust EcoBuilding. Generated on {now}.",
    "Sources publiques (Licence Ouverte, CC-BY-SA, ODbL). Les identifiants ci-dessus\n"
    "  permettent de retrouver la donnée d'origine. Document informatif, non contractuel.":
        "Public sources (Licence Ouverte, CC-BY-SA, ODbL). The identifiers above make it "
        "possible to retrieve the original data. Informational document, not contractually binding.",
    # — Principal address note
    " ({n} logements)": " ({n} dwellings)",
    "Bâtiment groupe BDNB{n} — adresse principale : {p}":
        "BDNB building group{n} — main address: {p}",
    # — DPE spread (per-dwelling certificates)
    "{n} diagnostics connus à cette adresse, tous en {c}.":
        "{n} energy performance certificates (DPE) known at this address, all rated {c}.",
    "{n} diagnostics connus à cette adresse : de {a} à {b}.":
        "{n} energy performance certificates (DPE) known at this address: from {a} to {b}.",
    " L'immeuble compte {n} logements.": " The building has {n} dwellings.",
    "enveloppe {v}": "envelope {v}",
    "menuiseries {v}": "windows and doors {v}",
    "seul logement de cette surface": "the only dwelling with this floor area",
    "{n} logements de cette surface — indiscernables":
        "{n} dwellings with this floor area — indistinguishable",
    "Logement": "Dwelling",
    "{e} — classe {c}": "{e} — class {c}",
    " · le logement de cette fiche": " · the dwelling covered by this report",
    " · classe affichée ci-dessus": " · class shown above",
    "Établi le": "Issued on",
    "Consommation": "Energy use",
    " kWh/m²/an": " kWh/m²/yr",
    "GES": "GHG",
    " kgCO₂/m²/an": " kgCO₂/m²/yr",
    "Coût annuel": "Annual cost",
    " €/an": " €/yr",
    "Isolation": "Insulation",
    "N° DPE": "DPE no.",
    '<p class="meta">Les {n} autres diagnostics de l\'immeuble figurent sur la fiche bâtiment.</p>':
        '<p class="meta">The building\'s {n} other certificates appear on the building report.</p>',
    '<p class="meta">L\'autre diagnostic de l\'immeuble figure sur la fiche bâtiment.</p>':
        '<p class="meta">The building\'s other certificate appears on the building report.</p>',
    '\n<p class="meta">Retrouvez le logement concerné par sa surface, ou par le numéro\n'
    "de DPE que le vendeur remet obligatoirement — il est vérifiable sur\n"
    "l'observatoire de l'ADEME.</p>":
        '\n<p class="meta">Identify the dwelling by its floor area, or by the DPE number the '
        "seller must hand over — it can be verified on the ADEME observatory.</p>",
    "La classe ci-dessus est celle du logement choisi pour cette fiche.":
        "The class above is that of the dwelling selected for this report.",
    "La classe ci-dessus est celle du logement représentatif du bâtiment, pas celle de tous.":
        "The class above is that of the building's representative dwelling, not of every dwelling.",
    "Répartition — {parts}. Source : ADEME, observatoire DPE.\n"
    "Seuls les logements diagnostiqués figurent : c'est un minimum observé, pas un\n"
    "inventaire de l'immeuble.":
        "Breakdown — {parts}. Source: ADEME, DPE observatory. Only dwellings with a certificate "
        "are listed: this is an observed minimum, not a full inventory of the building.",
    # — Local taxes
    "Taxe foncière (bâti), taux global": "Property tax (built land), combined rate",
    "Taxe ordures ménagères (TEOM)": "Household waste tax (TEOM)",
    "Taxe foncière (non bâti)": "Property tax (unbuilt land)",
    "Intercommunalité": "Inter-municipal body",
    "Taux globaux (commune + intercommunalité + syndicats), dernier exercice\n"
    "publié (DGFiP). La taxe due dépend de la valeur locative cadastrale du bien.":
        "Combined rates (municipality + inter-municipal body + syndicates), latest published "
        "tax year (DGFiP). The tax due depends on the property's cadastral rental value.",
    # — Municipality
    "Commune": "Municipality",
    "Auparavant": "Formerly",
    "{nom}, jusqu'au {date}": "{nom}, until {date}",
    "Nom et limites inchangés depuis": "Name and boundaries unchanged since",
    "A cessé d'exister le": "Ceased to exist on",
    "Données arrêtées au": "Data as of",
    "Source : {credits}.": "Source: {credits}.",
    # — Schools
    "Établissement": "School",
    "Écoles à proximité": "Schools nearby",
    "Aucun établissement recensé à moins de 2 km (annuaire de l'éducation).":
        "No school listed within 2 km (national school directory).",
    "Écoles à proximité ({n} à moins de 2 km)": "Schools nearby ({n} within 2 km)",
    "Distances à vol d'oiseau (annuaire de l'éducation). La proximité ne vaut\n"
    "pas sectorisation: la carte scolaire dépend de la commune.":
        "Straight-line distances (national school directory). Proximity does not imply "
        "catchment: school assignment depends on the municipality.",
    # — Official DPE
    "DPE officiel (logement représentatif)":
        "Official DPE (energy performance certificate) — representative dwelling",
    "N° DPE (ADEME)": "DPE no. (ADEME)",
    "Valable jusqu'au": "Valid until",
    " (validité légale: 10 ans)": " (legal validity: 10 years)",
    "Surface habitable": "Living area",
    "Coût annuel d'énergie estimé": "Estimated annual energy cost",
    "Chauffage": "Heating",
    "Eau chaude sanitaire": "Domestic hot water",
    "Énergies": "Energy sources",
    "Isolation: enveloppe": "Insulation: envelope",
    "Isolation: menuiseries": "Insulation: windows and doors",
    "Isolation: plancher bas": "Insulation: lower floor",
    "Isolation: plancher haut": "Insulation: upper floor",
    "Données du DPE officiel du logement représentatif du bâtiment (Observatoire\n"
    "DPE, ADEME). Dans un immeuble, les autres logements peuvent différer. Coûts estimés\n"
    "aux prix de l'énergie en vigueur à la date du diagnostic.":
        "Data from the official DPE of the building's representative dwelling (DPE observatory, "
        "ADEME). In an apartment building, other dwellings may differ. Costs estimated at the "
        "energy prices in force on the certificate date.",
    # — Drinking water
    "Eau potable (commune)": "Drinking water (municipality)",
    "Rendement du réseau": "Network efficiency",
    "Part perdue en fuites": "Share lost to leaks",
    "Prix de l'eau (120 m³)": "Water price (120 m³)",
    "Indicateurs du service public d'eau potable de la commune (SISPEA / OFB),\n"
    "dernière année publiée. Un rendement de 70 % signifie que 30 % de l'eau potable\n"
    "produite est perdue avant d'arriver au robinet.":
        "Indicators of the municipality's public drinking-water service (SISPEA / OFB), latest "
        "published year. An efficiency of 70 % means 30 % of the drinking water produced is "
        "lost before reaching the tap.",
    # — Groundwater
    "Eau souterraine": "Groundwater",
    "Donnée indisponible.": "Data unavailable.",
    "Profondeur de la nappe": "Water-table depth",
    " m sous le sol": " m below ground level",
    "Niveau piézométrique": "Piezometric level",
    "Mesuré le": "Measured on",
    "Piézomètre le plus proche": "Nearest piezometer",
    "Distance du bâtiment": "Distance from the building",
    # — Cover page
    "fiche bâtiment": "building record",
    # — Main page
    "Adresse inconnue": "Address unknown",
    "⚠ Location interdite à partir de <strong>{y}</strong> (loi Climat &amp; Résilience)":
        "⚠ Rental banned from <strong>{y}</strong> (French Climate &amp; Resilience law)",
    "Aucune interdiction de location prévue pour cette classe":
        "No rental ban scheduled for this class",
    "⚠ Location interdite à partir de <strong>{y}</strong> (loi Climat &amp; Résilience) pour ce logement":
        "⚠ Rental banned from <strong>{y}</strong> (French Climate &amp; Resilience law) for this dwelling",
    "Aucune interdiction de location prévue pour la classe de ce logement":
        "No rental ban scheduled for this dwelling's class",
    "Fiche LOGEMENT formatée et sourcée — données ouvertes":
        "DWELLING report, formatted and sourced — open data",
    "Fiche bâtiment formatée et sourcée — données ouvertes":
        "Building report, formatted and sourced — open data",
    "<strong>Fiche d'un logement</strong> : {m2} m² · classe {c} · N° DPE {n}. "
    "Les autres logements de l'immeuble ne sont pas l'objet de ce document.":
        "<strong>Report for one dwelling</strong>: {m2} m² · class {c} · DPE no. {n}. "
        "The building's other dwellings are not covered by this document.",
    "Identifiant BDNB : {id} · Générée le {now} · ecobuilding.confinia.io":
        "BDNB identifier: {id} · Generated on {now} · ecobuilding.confinia.io",
    "Énergie (DPE)": "Energy — DPE (energy performance certificate)",
    " — logement {m2} m², classe {c}": " — dwelling {m2} m², class {c}",
    "{v} kWh/m²/an": "{v} kWh/m²/yr",
    "Aucun DPE enregistré dans la BDNB pour ce bâtiment":
        "No DPE recorded in the BDNB for this building",
    "Étiquette énergie <span>(kWh/m²/an, énergie primaire)</span>":
        "Energy label <span>(kWh/m²/yr, primary energy)</span>",
    "Étiquette climat <span>(kgCO₂/m²/an)</span>":
        "Climate label <span>(kgCO₂/m²/yr)</span>",
    "Classes marquées : celles des {n} diagnostics connus à cette adresse. "
    "La valeur chiffrée est celle du logement représentatif.":
        "Classes marked: those of the {n} certificates known at this address. "
        "The figure shown is that of the representative dwelling.",
    "Classe marquée : celle du logement choisi (N° DPE {n}).":
        "Class marked: that of the selected dwelling (DPE no. {n}).",
    "Date du DPE": "DPE date",
    "Émissions GES": "GHG emissions",
    "Bâtiment": "Building",
    "ID-RNB (référentiel national)": "RNB ID (national building registry)",
    "Année de construction": "Year built",
    "Hauteur moyenne": "Average height",
    "Logements": "Dwellings",
    "Matériaux des murs": "Wall materials",
    "Matériaux du toit": "Roof materials",
    "Retrait-gonflement des argiles": "Clay shrink-swell",
    "Risques recensés dans la zone": "Risks identified in the area",
    "Rapport Géorisques": "Géorisques report",
    # — Urbanisme (PLU), issue #376
    "Urbanisme (PLU)": "Zoning (local plan)",
    "Zone du PLU": "Local-plan zone",
    "Catégorie": "Category",
    "Zone urbaine": "Urban zone",
    "Zone à urbaniser": "Zone to be urbanised",
    "Zone agricole": "Agricultural zone",
    "Zone naturelle": "Natural zone",
    "Zonage issu du plan local d'urbanisme (Géoportail de l'Urbanisme, GPU). "
    "Document de référence : {ref}. À recouper avec le règlement écrit de la zone.":
        "Zoning taken from the local urban plan (Géoportail de l'Urbanisme, GPU). "
        "Reference document: {ref}. Cross-check against the written zone regulations.",
    "Vérifier sur le Géoportail de l'Urbanisme":
        "Check on the Géoportail de l'Urbanisme",
    "Parcelle en zone inondable (source Géorisques). La couleur réglementaire "
    "du PPRI (zone bleue / rouge) n'est pas cartographiée à ce point : consulter "
    "le PPRI de la commune.":
        "Parcel in a flood-prone area (source: Géorisques). The regulatory PPRI "
        "colour (blue / red zone) is not mapped at this point: consult the commune's PPRI.",
    "Parcelle en zone BLEUE du PPRI inondation : risque modéré, "
    "constructible sous conditions (zone {code}).":
        "Parcel in the BLUE zone of the flood PPRI: moderate risk, buildable under "
        "conditions (zone {code}).",
    "Parcelle en zone ROUGE du PPRI inondation : risque fort, "
    "secteur très contraint (zone {code}).":
        "Parcel in the RED zone of the flood PPRI: high risk, heavily constrained "
        "area (zone {code}).",
    "Parcelle dans une zone réglementée du PPRI inondation "
    "(zone {code}).":
        "Parcel within a regulated zone of the flood PPRI (zone {code}).",
    "{nom}, {etat}{date}.": "{nom}, {etat}{date}.",
    " le {d}": " on {d}",
    "statut inconnu": "status unknown",
    "approuvé": "approved",
    "prescrit": "prescribed",
    "appliqué par anticipation": "applied in anticipation",
    "Consulter le règlement de la zone": "See the zone's regulation",
    "source": "source",
    "Géorisques": "Géorisques",
    "Solaire": "Solar",
    "Favorable au solaire thermique": "Suitable for solar thermal",
    "oui": "yes",
    "non": "no",
    "Potentiel annuel estimé": "Estimated annual potential",
    " kWh/an": " kWh/yr",
    "Productible photovoltaïque (PVGIS)": "Photovoltaic yield (PVGIS)",
    " kWh/an par kWc installé": " kWh/yr per kWp installed",
    "Irradiation (inclinaison optimale)": "Irradiation (optimal tilt)",
    "Carte du quartier : le bâtiment et les écoles":
        "Neighbourhood map: the building and the schools",
    "Le bâtiment épinglé en vert, les écoles nommées sur la carte.\n"
    "La liste disait combien ; la carte dit lesquelles, et où — proximité,\n"
    "jamais sectorisation (#324).":
        "The building pinned in green, the schools named on the map. The list said how many; "
        "the map says which ones, and where — proximity, never catchment (#324).",
    "Sources : BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte, attributions requises.\n"
    "  Document informatif généré automatiquement à partir de données ouvertes : il ne remplace ni un\n"
    "  diagnostic de performance énergétique (DPE) officiel, ni un état des risques et pollutions (ERP)\n"
    "  réglementaire. Une question sur cette fiche : contact@confinia.io":
        "Sources: BDNB (CSTB), Base Adresse Nationale, Géorisques — Licence Ouverte (French open "
        "licence), attribution required. Informational document generated automatically from open "
        "data: it replaces neither an official energy performance certificate (DPE) nor a "
        "regulatory risk and pollution report (ERP). A question about this report: contact@confinia.io",
    # — Context page
    "ce bâtiment": "this building",
    "Contexte — sources tierces": "Context — third-party sources",
    "Vue aérienne": "Aerial view",
    "Photo aérienne IGN (BD ORTHO) et limites de parcelles (Parcellaire Express)":
        "IGN aerial photo (BD ORTHO) and parcel boundaries (Parcellaire Express)",
    "Photo aérienne IGN (BD ORTHO)": "IGN aerial photo (BD ORTHO)",
    " — Licence Ouverte. ": " — Licence Ouverte (French open licence). ",
    "Le bâtiment concerné est entouré en cyan. ": "The building concerned is outlined in cyan. ",
    "Le bâtiment concerné est au centre du repère. ":
        "The building concerned is at the centre of the marker. ",
    "Le terrain, les arbres, les annexes et les accès, que nulle donnée structurée ne décrit.":
        "The grounds, trees, outbuildings and access ways, which no structured dataset describes.",
    "Photos du lieu": "Photos of the site",
    "Localisation — carte 3D (DPE)": "Location — 3D map (DPE)",
    "Bâtiment ciblé en pleine opacité (voisins atténués), coloré par classe DPE. "
    "Limites de parcelles en orange. "
    "Zoom 18, inclinaison 60°. Fond : OpenStreetMap et contributeurs (ODbL) · Bâtiments &amp; DPE : BDNB (CSTB) "
    "· Parcelles : IGN Parcellaire Express (Licence Ouverte).":
        "Targeted building at full opacity (neighbours dimmed), coloured by DPE class. "
        "Parcel boundaries in orange. "
        "Zoom 18, tilt 60°. Basemap: OpenStreetMap and contributors (ODbL) · Buildings &amp; DPE: BDNB (CSTB) "
        "· Parcels: IGN Parcellaire Express (Licence Ouverte).",
    "Voir la zone sur OSM": "View the area on OSM",
    "Imagerie : Panoramax (CC-BY-SA 4.0) et Wikimedia Commons, auteur et licence indiqués\n"
    "  sous chaque photo. Cartographie : OpenStreetMap et contributeurs (ODbL).\n"
    "  Informations de contexte, non contractuelles.":
        "Imagery: Panoramax (CC-BY-SA 4.0) and Wikimedia Commons, author and licence shown "
        "under each photo. Cartography: OpenStreetMap and contributors (ODbL). "
        "Contextual information, not contractually binding.",
}
