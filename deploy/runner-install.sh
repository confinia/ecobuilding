#!/bin/bash
# EcoBuilding — one-time GitHub Actions self-hosted runner install (#112).
# Run ON the VM as the ecobuilding user (never debian — one runner ↔ one repo
# ↔ one Unix user, see STACK_template.md):
#   REG_TOKEN=<token> ./deploy/runner-install.sh
# The registration token comes from repo Settings → Actions → Runners → New
# self-hosted runner (or `gh api -X POST .../actions/runners/registration-token`).
# Idempotent: re-running re-registers (--replace) and rewrites the unit.
set -eu
: "${REG_TOKEN:?export REG_TOKEN=<registration token>}"

V=$(curl -fsS https://api.github.com/repos/actions/runner/releases/latest \
    | grep -oE '"tag_name": *"v[0-9.]+"' | grep -oE '[0-9.]+')
mkdir -p ~/actions-runner && cd ~/actions-runner
if [ ! -f config.sh ]; then
  echo "== downloading actions-runner v$V"
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${V}/actions-runner-linux-x64-${V}.tar.gz"
  tar xzf runner.tar.gz && rm runner.tar.gz
fi

./config.sh --unattended --replace \
  --url https://github.com/confinia/ecobuilding \
  --token "$REG_TOKEN" \
  --name ecobuilding-vm \
  --labels vm,ecobuilding

# Lingering user service, same pattern as the rootless podman socket (svc.sh
# would install a root-owned system unit — not for this VM).
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/github-runner.service <<'UNIT'
[Unit]
Description=GitHub Actions runner (confinia/ecobuilding)
After=network.target

[Service]
ExecStart=%h/actions-runner/run.sh
Restart=always
RestartSec=10
KillMode=process

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now github-runner
loginctl enable-linger "$USER" 2>/dev/null || true

# Loopback ssh key: workflows run the deploy scripts via `ssh localhost` so
# podman helpers live in a logind session (not the job cgroup, not a transient
# unit — both get reaped, #144).
if [ ! -f ~/.ssh/id_ed25519 ]; then ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519; fi
grep -qf ~/.ssh/id_ed25519.pub ~/.ssh/authorized_keys 2>/dev/null || cat ~/.ssh/id_ed25519.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes localhost true && echo "loopback ssh OK"
echo "== runner service:"
systemctl --user --no-pager --lines=0 status github-runner | head -4
