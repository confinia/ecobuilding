#!/usr/bin/env python3
"""Rapport e2e depuis la PLATEFORME DE PAIEMENT (Creem test mode, ou Polar
sandbox en héritage).

Le scénario Selenium prouve ce que voit l'utilisateur ; ce script prouve ce que
voit Polar. Les deux sont nécessaires : l'app peut afficher « Pro » alors que
rien n'a été encaissé, et Polar peut facturer un montant que l'app n'annonce
nulle part — c'est exactement ce qui était en place avant ce rapport (produit
resté en v2 : socle 9 €/mois + 0,01 €/crédit, alors que PRICING.md v3 annonce
0,49 € la fiche sans socle).

Sortie : un rapport Markdown + un JSON dans le répertoire de résultats, et un
code de retour non nul si la grille tarifaire de Polar contredit la nôtre.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CREEM_KEY = os.environ.get("CREEM_API_KEY", "")
CREEM_BASE = (os.environ.get("CREEM_API_BASE")
              or ("https://test-api.creem.io/v1" if CREEM_KEY.startswith("creem_test_")
                  else "https://api.creem.io/v1")).rstrip("/")
CREEM_PRODUCTS = json.loads(os.environ.get("CREEM_PRODUCTS_JSON", "") or "{}")
PROVIDER = "creem" if CREEM_KEY else "polar"
BASE = os.environ.get("POLAR_BASE_URL", "https://sandbox-api.polar.sh").rstrip("/")
TOKEN = os.environ.get("POLAR_ACCESS_TOKEN", "")
PRODUCT_ID = os.environ.get("POLAR_PRODUCT_ID", "")


def get(url, params=None, token=TOKEN, timeout=25):
    """GET JSON. Renvoie (données, erreur) — jamais d'exception : un rapport
    partiel vaut mieux qu'un rapport absent quand une étape a déjà échoué."""
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    # Cloudflare protège sandbox-api.polar.sh et rejette l'agent par défaut
    # d'urllib avec un 403 « error code: 1010 » — un blocage d'agent, pas un
    # problème d'authentification : sans cet en-tête le rapport paraît dire que
    # le produit n'existe pas.
    req.add_header("User-Agent", "ecobuilding-e2e/1.0 (+https://ecobuilding.confinia.io)")
    req.add_header("Accept", "application/json")
    if token:
        if PROVIDER == "creem":
            req.add_header("x-api-key", token)
        else:
            req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.read()[:200].decode(errors='replace')}"
    except Exception as e:                                    # réseau, DNS, TLS
        return None, str(e)


def euros(cents):
    return None if cents is None else round(cents / 100, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--env", default="sandbox")
    ap.add_argument("--app-url", default="")
    ap.add_argument("--api-url", default="")
    ap.add_argument("--email", default="")
    ap.add_argument("--signup-rc", type=int, default=0)
    ap.add_argument("--payment-rc", type=int, default=0)
    a = ap.parse_args()

    report, problems = {}, []

    # 1. Ce que NOUS annonçons, lu sur l'API publique (jamais recopié ici : une
    #    constante dupliquée dans un test finit toujours par mentir).
    pricing, err = get(f"{a.api_url}/v1/pricing", token=None)
    if err:
        problems.append(f"grille tarifaire de l'API illisible ({a.api_url}/v1/pricing) : {err}")
        pricing = {}
    ours = {
        "prix_par_fiche_eur": pricing.get("price_per_fiche_eur"),
        "plafond_mensuel_eur": pricing.get("cap_eur") or pricing.get("monthly_cap_eur"),
        "fiches_incluses": pricing.get("included_fiches"),
    }
    report["annonce_ecobuilding"] = ours

    if PROVIDER == "creem":
        # 2. Ce que Creem facture réellement : chaque palier annoncé par
        #    /v1/config doit exister comme produit récurrent au même prix.
        cfg, err = get(f"{a.api_url}/v1/config", token=None)
        tiers = (cfg or {}).get("pro_tiers") or {}
        report["paliers_annoncés"] = tiers
        if err:
            problems.append(f"/v1/config illisible : {err}")
        for t, pid in CREEM_PRODUCTS.items():
            prod, perr = get(f"{CREEM_BASE}/products", {"product_id": pid}, token=CREEM_KEY)
            if perr:
                problems.append(f"produit Creem {t} ({pid}) illisible : {perr}")
                continue
            cents = int(prod.get("price") or 0)
            want = tiers.get(t, {}).get("eur")
            report.setdefault("produits_creem", {})[t] = {
                "id": pid, "nom": prod.get("name"), "prix_eur": cents / 100,
                "récurrence": prod.get("billing_period")}
            if want is not None and cents != int(want) * 100:
                problems.append(f"palier {t} : Creem facture {cents/100:.2f} € "
                                f"≠ {want} € annoncés (PRICING.md v4)")
        if a.email and CREEM_KEY:
            cust, cerr = get(f"{CREEM_BASE}/customers", {"email": a.email}, token=CREEM_KEY)
            found = bool(cust and (cust.get("id") or (cust.get("items") or [])))
            report["client_creem"] = {"trouvé": found, "erreur": cerr}
            if not found:
                problems.append(f"aucun client Creem pour {a.email} : le checkout n'a pas abouti")
        # le bloc Polar ci-dessous ne joue pas en mode creem
        problems_len_before = len(problems)

    # 2bis. Ce que Polar facture réellement (héritage).
    if PROVIDER == "polar" and not TOKEN:
        problems.append("POLAR_ACCESS_TOKEN absent de e2e/.env — aucune vérification côté paiement")
    product, err = (get(f"{BASE}/v1/products/{PRODUCT_ID}")
                    if (PROVIDER == "polar" and TOKEN and PRODUCT_ID)
                    else (None, None if PROVIDER == "creem" else "POLAR_PRODUCT_ID absent"))
    if err:
        problems.append(f"produit Polar illisible : {err}")
    if product:
        fixed = [p for p in product.get("prices", []) if p.get("amount_type") == "fixed"]
        metered = [p for p in product.get("prices", []) if p.get("amount_type") == "metered_unit"]
        report["produit_polar"] = {
            "id": product.get("id"),
            "nom": product.get("name"),
            "archivé": product.get("is_archived"),
            "socle_fixe_eur": [euros(p.get("price_amount")) for p in fixed],
            "prix_unitaire_eur": [round(float(p["unit_amount"]) / 100, 4) for p in metered
                                  if p.get("unit_amount") is not None],
            "plafond_eur": [euros(p.get("cap_amount")) for p in metered],
        }
        # --- les trois contradictions qui coûtent de l'argent ou de la confiance
        if fixed:
            problems.append(
                f"Polar facture un socle fixe de {euros(fixed[0].get('price_amount'))} €/mois, "
                "alors que la grille v3 est sans socle (« 10 premières fiches offertes, "
                "puis 0,49 € la fiche »). Le client paierait un abonnement qu'on n'annonce pas.")
        for p in metered:
            unit = round(float(p["unit_amount"]) / 100, 4) if p.get("unit_amount") is not None else None
            if ours["prix_par_fiche_eur"] is not None and unit is not None \
                    and abs(unit - ours["prix_par_fiche_eur"]) > 1e-6:
                problems.append(
                    f"prix unitaire Polar {unit} € ≠ prix annoncé {ours['prix_par_fiche_eur']} € "
                    "la fiche (PRICING.md §4)")
            cap = euros(p.get("cap_amount"))
            if ours["plafond_mensuel_eur"] is not None and cap is not None \
                    and abs(cap - ours["plafond_mensuel_eur"]) > 1e-6:
                problems.append(f"plafond Polar {cap} € ≠ plafond annoncé {ours['plafond_mensuel_eur']} €")

    # 3. Le compte du scénario, vu par Polar : client, abonnement, encaissement.
    if PROVIDER == "polar" and TOKEN and a.email:
        customers, err = get(f"{BASE}/v1/customers/", {"email": a.email, "limit": 5})
        items = (customers or {}).get("items", [])
        report["client_polar"] = {"trouvé": bool(items), "erreur": err,
                                  "id": items[0]["id"] if items else None}
        if not items:
            problems.append(f"aucun client Polar pour {a.email} : le checkout n'a pas abouti")
        else:
            cid = items[0]["id"]
            subs, _ = get(f"{BASE}/v1/subscriptions/", {"customer_id": cid, "limit": 5})
            sitems = (subs or {}).get("items", [])
            report["abonnement"] = [{"statut": s.get("status"),
                                     "produit": (s.get("product") or {}).get("name"),
                                     "montant_eur": euros(s.get("amount")),
                                     "début": s.get("current_period_start")} for s in sitems]
            if not any(s.get("status") == "active" for s in sitems):
                problems.append("aucun abonnement ACTIF côté Polar : l'app peut afficher « Pro » "
                                "sans qu'un paiement ait été accepté")
            orders, _ = get(f"{BASE}/v1/orders/", {"customer_id": cid, "limit": 5})
            report["commandes"] = [{"montant_eur": euros(o.get("total_amount")),
                                    "statut": o.get("status"),
                                    "date": o.get("created_at")}
                                   for o in (orders or {}).get("items", [])]

    def verdict(rc):
        # -1 = suite jamais lancée. La distinguer d'un succès est essentiel :
        # un rapport qui affiche « paiement : ok » pour une suite sautée est pire
        # que pas de rapport du tout.
        return "non jouée" if rc < 0 else ("ok" if rc == 0 else f"échec ({rc})")
    report["selenium"] = {"inscription": verdict(a.signup_rc), "paiement": verdict(a.payment_rc)}
    if a.payment_rc < 0:
        problems.append("suite paiement non jouée (l'inscription a échoué) : "
                        "rien n'est prouvé sur le paiement")
    report["problèmes"] = problems

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "polar-report.json"), "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    lines = [f"# Rapport e2e — inscription & paiement ({a.env})", "",
             f"- App : {a.app_url}", f"- API : {a.api_url}",
             f"- Plateforme de paiement : {BASE}", f"- Compte de test : {a.email}", "",
             "## Parcours navigateur (Selenium IDE)", "",
             f"- inscription : **{report['selenium']['inscription']}**",
             f"- paiement : **{report['selenium']['paiement']}**", "",
             "> L'étape « clic sur le lien de vérification e-mail » est **simulée** via",
             "> l'API admin Keycloak : la boîte de réception est un mailbox externe réel,",
             "> que la CI ne peut pas ouvrir. Tout le reste est joué dans le navigateur.", "",
             "## Vu par la plateforme de paiement", "",
             "```json", json.dumps({k: v for k, v in report.items() if k != "problèmes"},
                                   indent=2, ensure_ascii=False), "```", ""]
    if problems:
        lines += ["## Contradictions détectées", ""] + [f"- {p}" for p in problems]
    else:
        lines += ["## Contradictions détectées", "",
                 "Aucune : l'app et la plateforme de paiement annoncent la même grille."]
    with open(os.path.join(a.out, "report.md"), "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines[-(len(problems) + 3):]) if problems else "== Polar : grille cohérente")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
