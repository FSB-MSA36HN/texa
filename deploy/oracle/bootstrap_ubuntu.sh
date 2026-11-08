#!/usr/bin/env bash
set -euo pipefail

# Run this once on a fresh Ubuntu 22.04/24.04 Oracle VM as the ubuntu user.
# It installs Docker Engine + Compose from Docker's official apt repository.
if [[ "$(uname -m)" != "aarch64" && "$(uname -m)" != "x86_64" ]]; then
  echo "Unsupported architecture: $(uname -m)" >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

arch="$(dpkg --print-architecture)"
codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOT
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${codename}
Components: stable
Architectures: ${arch}
Signed-By: /etc/apt/keyrings/docker.asc
EOT

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"

# Host firewall. OCI's VCN/security list must also allow 22 and 80.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw --force enable

cat <<'EOT'
Docker is installed. Log out and reconnect once so the docker group applies:
  exit
  ssh -i <private-key> ubuntu@<vm-public-ip>
Then verify:
  docker run --rm hello-world
  docker compose version
EOT
