/* Validité d'un DPE et interdiction de location : UNE formulation, partagée
   par la fiche (app.js) et la page « DPE perdu » (dpe.html) — deux rendus qui
   divergeraient donneraient deux vérités (#414).

   Les dates viennent de l'API (official_dpe.valid_until, energy.dpe_valid_until,
   règle de la réforme 2021, #399) ; rien n'est recalculé ici. */
(function () {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const frDate = (iso) => { if (!iso) return null; const [y, m, d] = iso.slice(0, 10).split("-"); return `${d}/${m}/${y}`; };

  /** @param {{cls?:string|null, od?:object|null, energy?:object|null, today?:string}} p */
  function validite(p) {
    const od = p.od || null, en = p.energy || {};
    const today = p.today || new Date().toISOString().slice(0, 10);
    const cls = p.cls || null;
    // Le DPE officiel du logement représentatif d'abord, sinon celui du groupe.
    const established = (od && od.established_on) || en.dpe_date || null;
    const validUntil = (od && od.valid_until) || en.dpe_valid_until || null;
    const expired = !!(validUntil && validUntil.slice(0, 10) < today);
    // Avant la réforme du 1er juillet 2021 : autre méthode de calcul, validité
    // écourtée par la loi (fin 2022 ou fin 2024), classe plus opposable — et
    // la BDNB ne reprend pas la classe de ces DPE-là.
    const preReform = !!(established && established.slice(0, 10) < "2021-07-01");

    let validHtml = "";
    if (validUntil && expired && preReform) {
      validHtml = `DPE de l'ancienne méthode (avant la réforme du 1<sup>er</sup> juillet 2021) :
        il n'est plus valable depuis le ${frDate(validUntil)}. La classe n'est plus opposable —
        un nouveau diagnostic est nécessaire pour vendre ou louer.`;
    } else if (validUntil && expired) {
      validHtml = `Ce DPE n'est plus valable depuis le ${frDate(validUntil)} — un nouveau diagnostic est nécessaire pour vendre ou louer.`;
    } else if (validUntil) {
      validHtml = `Valable jusqu'au ${frDate(validUntil)}.`;
    }

    // Interdiction de location (loi Climat & Résilience) : G depuis 2025,
    // F en 2028, E en 2034. Au passé une fois la date franchie ; et si le DPE
    // est périmé, la classe n'est qu'indicative — on le dit, sans taire l'alerte.
    const ban = en.rental_ban;
    let banHtml = "", banKind = "";
    if (cls && ban && ban.rental_ban_date) {
      const d = ban.rental_ban_date.slice(0, 10);
      const quand = d <= today ? `interdite depuis le <strong>${frDate(d)}</strong>` : `interdite à partir du <strong>${frDate(d)}</strong>`;
      banKind = "ko";
      banHtml = expired
        ? `⚠ Classe ${esc(cls)} : location ${quand} (loi Climat &amp; Résilience).
           Ce DPE étant périmé, seul un nouveau diagnostic fixera la classe opposable — s'il confirme la classe ${esc(cls)}, l'interdiction s'applique.`
        : `⚠ Location ${quand} (loi Climat &amp; Résilience).`;
    } else if (cls && "ABCDE".includes(cls)) {
      banKind = expired ? "stale" : "ok";
      banHtml = expired
        ? `Aucune interdiction de location prévue pour la classe ${esc(cls)} — sous réserve du nouveau DPE, celui-ci étant périmé.`
        : `✓ Aucune interdiction de location prévue pour la classe ${esc(cls)}.`;
    }

    return { established, validUntil, expired, preReform, validHtml, banHtml, banKind, frDate, esc };
  }

  // Notre fiche n'est PAS le DPE (#418) : une seule phrase, dite partout où
  // l'on propose le PDF, et le lien vers le document officiel, par son numéro
  // (l'observatoire ouvre directement /afficher-dpe/<numéro>).
  const NOT_THE_DPE = "La fiche EcoBuilding rassemble des données ouvertes sur le bâtiment. " +
    "Ce n'est pas le diagnostic de performance énergétique : celui-ci est établi par un " +
    "diagnostiqueur certifié et archivé par l'ADEME.";
  const ademeUrl = (num) => num
    ? `https://observatoire-dpe-audit.ademe.fr/afficher-dpe/${encodeURIComponent(String(num).trim())}`
    : "https://observatoire-dpe-audit.ademe.fr/";

  window.ecoDpe = { validite, frDate, esc, NOT_THE_DPE, ademeUrl };
})();
