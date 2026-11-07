#!/bin/bash
# Prepara um Ubuntu novo para rodar o homelab.
# Uso:  sudo ~/homelab/scripts/bootstrap.sh
set -e
USER_NAME="${SUDO_USER:-glauco}"
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== Pacotes básicos"
apt-get update
apt-get install -y ca-certificates curl gnupg git rsync pciutils

echo "== Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
usermod -aG docker "$USER_NAME"

echo "== GPU NVIDIA (opcional)"
if lspci | grep -qi nvidia; then
  if command -v nvidia-smi >/dev/null; then
    bash "$HERE/install_nvidia_toolkit.sh"
  else
    echo "!! GPU NVIDIA encontrada, mas sem driver."
    echo "   Rode: sudo ubuntu-drivers install  -> reinicie -> rode este script de novo."
  fi
else
  echo "Sem GPU NVIDIA: remova o bloco 'deploy:' de stacks/jellyfin/docker-compose.yml antes do up-all."
fi

echo
echo "Pronto. Saia e entre de novo na sessão (pra valer o grupo docker)."
echo "Depois: ~/homelab/up-all.sh"
