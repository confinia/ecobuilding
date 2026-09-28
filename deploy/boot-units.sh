#!/bin/bash
# EcoBuilding — installe et active les unités de démarrage des piles (#484).
#
# Sans elles, un redémarrage de la VM laissait les 24 conteneurs éteints
# jusqu'à ce que quelqu'un relance chaque pile à la main : rien d'autre que le
# runner GitHub n'était câblé au boot, `unless-stopped` n'agit pas au boot, et
# les étiquettes PODMAN_SYSTEMD_UNIT posées par podman-compose désignent des
# unités qui n'ont jamais été installées.
#
# Idempotent. `enable --now` sur une pile qui tourne : `podman pod start` ne
# touche pas un conteneur déjà démarré ; l'unité devient simplement « active »,
# ce qui permet aussi l'arrêt PROPRE (60 s de grâce) à l'extinction.
# Lancé sur la VM par stack-up.sh, à la fin, une fois toutes les piles debout.
set -eu
cd "$(dirname "$0")/.."
U="$HOME/.config/systemd/user"
mkdir -p "$U"
install -m 644 deploy/systemd/ecobuilding-stack@.service "$U/"

# L'identité, le miroir BDNB et le rendu démarrent AVANT ce qui les appelle.
# (Sans cet ordre, les politiques de redémarrage rattrapent quand même un
# service parti trop tôt ; l'ordre évite juste une série d'échecs au boot.)
for app in blue green edge sandbox; do
  mkdir -p "$U/ecobuilding-stack@$app.service.d"
  printf '[Unit]\nAfter=ecobuilding-stack@auth.service ecobuilding-stack@bdnb.service ecobuilding-stack@render.service\n' \
    > "$U/ecobuilding-stack@$app.service.d/ordre.conf"
done
systemctl --user daemon-reload

actives=0
for pile in auth bdnb render monitoring edge blue green sandbox; do
  if podman pod exists "pod_ecobuilding-$pile"; then
    systemctl --user enable --now "ecobuilding-stack@$pile.service" >/dev/null 2>&1 \
      && actives=$((actives + 1)) \
      || echo "::warning::boot-units: ecobuilding-stack@$pile non activée"
  else
    echo "boot-units: pod_ecobuilding-$pile absent — pas d'unité pour cette pile"
  fi
done
echo "boot-units: $actives piles redémarreront avec la VM"
