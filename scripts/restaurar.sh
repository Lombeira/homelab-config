#!/bin/bash
# Restaura o homelab inteiro num Ubuntu recém-instalado, a partir do kit criptografado ao lado deste script.
# Uso: sudo bash restaurar.sh                 (restauração de verdade)
#      sudo bash restaurar.sh --ensaio        (teste: sobe só o que não tem efeito fora da máquina)
#      opções: --ip <IP desta máquina>        (sem a opção, pergunta; padrão = IP detectado)
#              --pular-kit                    (reaproveita um kit já aberto; só serve para repetir ensaio)
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
IP_ANTIGO=192.168.1.173
ENSAIO=0; PULAR_KIT=0; IP_NOVO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --ensaio) ENSAIO=1 ;;
    --pular-kit) PULAR_KIT=1 ;;
    --ip) IP_NOVO="$2"; shift ;;
    *) echo "opção desconhecida: $1"; exit 1 ;;
  esac
  shift
done
[ $ENSAIO = 1 ] && echo "######## MODO ENSAIO ########"
[ "$(id -u)" = 0 ] || { echo "Rode com sudo: sudo bash $0"; exit 1; }
KIT="$(cd "$(dirname "$0")" && pwd)"
id glauco >/dev/null 2>&1 || { echo "Crie o usuário glauco (UID 1000) na instalação do Ubuntu antes."; exit 1; }
[ "$(id -u glauco)" = 1000 ] || echo "!! glauco não tem UID 1000; os donos dos arquivos podem ficar errados."

IP_DETECTADO=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
if [ -z "$IP_NOVO" ]; then
  echo "O servidor antigo usava o IP $IP_ANTIGO. O ideal é reservar esse mesmo IP no roteador para esta máquina."
  read -r -p "IP desta máquina [${IP_DETECTADO:-$IP_ANTIGO}]: " IP_NOVO
  IP_NOVO=${IP_NOVO:-${IP_DETECTADO:-$IP_ANTIGO}}
fi
echo "IP que os serviços vão usar: $IP_NOVO"

if [ $PULAR_KIT = 0 ]; then
  ls "$KIT"/homelab-*.part* >/dev/null 2>&1 || { echo "Não achei as partes do kit em $KIT"; exit 1; }
  echo "== 1/8 Conferindo o kit"
  ( cd "$KIT" && sha256sum -c --quiet SHA256SUMS )

  echo "== 2/8 Pacotes"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl gnupg git rsync zstd tmux ttyd python3 pciutils zsh >/dev/null
  command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh >/dev/null
  systemctl disable --now ttyd 2>/dev/null || true

  echo "== 3/8 Usuários (mesmos UIDs do servidor antigo)"
  getent group hermes >/dev/null || groupadd -g 1001 hermes
  getent group leme >/dev/null || groupadd -g 1002 leme
  id hermes >/dev/null 2>&1 || useradd -u 1001 -g 1001 -m -s /bin/bash hermes
  id leme >/dev/null 2>&1 || useradd -u 1002 -g 1002 -m -s /bin/bash leme
  usermod -aG docker glauco; usermod -aG docker hermes
  chsh -s /usr/bin/zsh glauco || true

  echo "== 4/8 Abrindo o kit (digite a senha do kit)"
  cat "$KIT"/homelab-*.part* | gpg --pinentry-mode loopback -d | zstd -dq | tar --numeric-owner -xpf - -C /
  chmod 750 /home/leme /home/glauco
fi

echo "== 5/8 IP"
if [ "$IP_NOVO" != "$IP_ANTIGO" ]; then
  n=0
  while IFS= read -r f; do
    sed -i "s/$(echo "$IP_ANTIGO" | sed 's/\./\\./g')/$IP_NOVO/g" "$f"; n=$((n+1))
  done < <(grep -rIl --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=repos -F "$IP_ANTIGO" \
             /home/glauco/homelab /home/glauco/dockge /home/leme/workspace/esteira /home/leme/.config /home/hermes/.hermes/config* 2>/dev/null \
             | grep -v -E '\.(db|sqlite|log)$')
  echo "  $IP_ANTIGO -> $IP_NOVO em $n arquivo(s)"
else
  echo "  mesmo IP do servidor antigo, nada a trocar"
fi

echo "== 6/8 Serviços e agendamentos"
if [ -f /home/glauco/.crontab-glauco ]; then
  if [ $ENSAIO = 1 ]; then echo "  (ensaio) crontab NÃO instalado:"; sed 's/^/    /' /home/glauco/.crontab-glauco; else crontab -u glauco /home/glauco/.crontab-glauco; fi
  rm /home/glauco/.crontab-glauco
fi
if [ $ENSAIO = 1 ]; then
  echo "  (ensaio) linger e serviços de usuário NÃO ligados. Conferindo que estão no lugar:"
  for u in leme hermes; do echo "    $u: $(ls /home/$u/.config/systemd/user/ 2>/dev/null | grep -E '\.(service|timer)$' | tr '\n' ' ')"; done
else
  loginctl enable-linger leme hermes 2>/dev/null || echo "!! linger falhou (systemd-logind indisponível?)"
  for u in leme hermes; do
    uid=$(id -u $u); systemctl start "user@$uid.service"
    for unit in /home/$u/.config/systemd/user/*.service /home/$u/.config/systemd/user/*.timer; do
      [ -f "$unit" ] || continue
      sudo -u $u XDG_RUNTIME_DIR=/run/user/$uid systemctl --user daemon-reload
      sudo -u $u XDG_RUNTIME_DIR=/run/user/$uid systemctl --user enable "$(basename "$unit")" >/dev/null 2>&1 || true
    done
  done
fi
if [ -x /home/leme/.local/bin/fnm ] && [ $PULAR_KIT = 0 ]; then
  sudo -u leme bash -lc 'export PATH=$HOME/.local/bin:$PATH; eval "$(fnm env)"; fnm install 24.22.1 && fnm default 24.22.1' >/dev/null || echo "!! instale o Node 24.22.1 do leme depois (fnm)"
fi

echo "== 7/8 GPU NVIDIA"
if lspci | grep -qi nvidia && ! command -v nvidia-smi >/dev/null; then
  echo "  !! GPU NVIDIA sem driver: rode 'sudo ubuntu-drivers install', reinicie e depois 'bash ~/homelab/scripts/install_nvidia_toolkit.sh'."
  echo "     Enquanto isso o Jellyfin não sobe (ele pede a GPU no compose)."
elif lspci | grep -qi nvidia; then bash /home/glauco/homelab/scripts/install_nvidia_toolkit.sh >/dev/null || true
else echo "  sem GPU NVIDIA: tire o bloco 'deploy:' de stacks/jellyfin/docker-compose.yml para o Jellyfin subir"
fi

echo "== 8/8 Containers"
IMGDIR="$KIT/../imagens"
if ls "$IMGDIR"/imagens.tar.zst.part* >/dev/null 2>&1; then
  echo "  carregando as imagens do pendrive (sem internet; alguns minutos)..."
  cat "$IMGDIR"/imagens.tar.zst.part* | zstd -dq | docker load -q | sed 's/^/    /' | tail -3
else
  echo "  sem imagens no pendrive: vai baixar tudo da internet (demora)"
fi
COM_EFEITO_FORA="homeassistant nodered media uptime-kuma autokuma scrutiny"
for d in /home/glauco/homelab/stacks/*/ /home/glauco/dockge/; do
  [ -f "$d/docker-compose.yml" ] || [ -f "$d/compose.yaml" ] || continue
  n=$(basename "$d")
  if [ $ENSAIO = 1 ] && [[ " $COM_EFEITO_FORA " == *" $n "* ]]; then
    if (cd "$d" && docker compose create --quiet-pull) >/dev/null 2>&1; then echo "  --   $n: imagens ok, NÃO iniciado no ensaio (mexe fora da máquina)"
    else echo "  !!   $n: config ou imagens com problema"; fi
    continue
  fi
  if (cd "$d" && docker compose up -d --quiet-pull) >/tmp/up-$n.log 2>&1; then echo "  up   $n"
  else echo "  !!   $n: $(grep -i -E 'error|denied|failed' /tmp/up-$n.log | tail -1 | cut -c1-140)"; fi
done
if [ $ENSAIO = 0 ]; then
  for u in leme hermes; do uid=$(id -u $u); sudo -u $u XDG_RUNTIME_DIR=/run/user/$uid systemctl --user restart default.target >/dev/null 2>&1 || true; done
fi

echo
echo "== Conferência"
sleep 15
for host in nossa.casa escritorio.casa; do
  printf "  %-16s %s\n" "$host" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' -H "Host: $host" http://127.0.0.1/ || echo falhou)"
done
docker ps --format '{{.Names}}\t{{.Status}}' | sort | sed 's/^/  /'

cat <<TXT

==================== QUASE LÁ ====================
- Reserve no roteador o IP $IP_NOVO para esta máquina e reinicie (o DNS da casa aponta para o AdGuard nesse IP).
- Abra http://escritorio.casa e http://nossa.casa para conferir.
- Immich e Nextcloud voltam sem fotos/arquivos (fora do kit, por escolha).
- O Claude do leme já volta logado; se pedir login, rode 'claude' como leme.
==================================================
TXT
