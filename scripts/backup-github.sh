#!/bin/bash
# Backup de configuração do homelab e do escritório da Leme para dois repos privados do GitHub.
# Só configuração: nenhum segredo, nenhum dado pesado. Segredos viram placeholder <PREENCHER>.
# Uso: backup-github.sh [--sem-push]
set -euo pipefail

HOME_G=/home/glauco
STAGE="$HOME_G/backup-git"
REPO_H="$STAGE/homelab-config"
REPO_L="$STAGE/leme-escritorio-config"
PUSH=1
[ "${1:-}" = "--sem-push" ] && PUSH=0
LOG="$STAGE/backup.log"
mkdir -p "$REPO_H" "$REPO_L"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# Lê /home/leme e arquivos de root via container (glauco está no grupo docker), e devolve tudo como glauco.
UIDG=$(id -u); GIDG=$(id -g)
docker run --rm -i -v /home:/h:ro -v "$STAGE":/out alpine:3 sh -s "$UIDG" "$GIDG" <<'CONTAINER'
set -e
U=$1; G=$2
apk add --no-cache rsync >/dev/null 2>&1
H=/out/homelab-config; L=/out/leme-escritorio-config
for d in "$H" "$L"; do find "$d" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +; done

# ---------- homelab ----------
S=/h/glauco/homelab
mkdir -p "$H/stacks" "$H/dockge"
cp "$S/README.md" "$S/up-all.sh" "$H/" 2>/dev/null || true
rsync -a --exclude archive --exclude '__pycache__' "$S/scripts/" "$H/scripts/"
cd "$S/stacks"
find . -maxdepth 2 \( -name docker-compose.yml -o -name compose.yaml -o -name compose.yml -o -name Dockerfile \) -exec cp --parents {} "$H/stacks/" \;
cp --parents caddy/Caddyfile "$H/stacks/" 2>/dev/null || true
rsync -a --include '*/' --include '*.yaml' --include '*.yml' --include '*.css' --include '*.js' --exclude '*' homepage/config/ "$H/stacks/homepage/config/" 2>/dev/null || true
rsync -a --exclude 'node_modules' --exclude '__pycache__' escritorio-leme/ "$H/stacks/escritorio-leme/" 2>/dev/null || true
for f in homeassistant/config/configuration.yaml homeassistant/config/automations.yaml homeassistant/config/scripts.yaml homeassistant/config/scenes.yaml nodered/data/flows.json nodered/data/package.json adguard/conf/AdGuardHome.yaml nodered/data/settings.js; do
  [ -f "$f" ] && cp --parents "$f" "$H/stacks/"
done
for x in media/radarr/config.xml media/sonarr/config.xml media/prowlarr/config.xml media/bazarr/config/config.yaml; do
  [ -f "$x" ] && cp --parents "$x" "$H/stacks/"
done
find . -maxdepth 3 -name .env | while read -r e; do
  mkdir -p "$H/stacks/$(dirname "$e")"
  sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)=.*/\1=<PREENCHER>/' "$e" > "$H/stacks/$(dirname "$e")/.env.example"
done
[ -f /h/glauco/dockge/docker-compose.yml ] && cp /h/glauco/dockge/docker-compose.yml "$H/dockge/"
if [ -f /h/glauco/homelab/stacks/homeassistant/config/secrets.yaml ]; then
  sed -E 's/^([A-Za-z_][A-Za-z0-9_]*):.*/\1: <PREENCHER>/' /h/glauco/homelab/stacks/homeassistant/config/secrets.yaml > "$H/stacks/homeassistant/config/secrets.yaml.example"
fi
# redações nos arquivos copiados
find "$H/stacks" -name 'AdGuardHome.yaml' -exec sed -i -E 's/^(\s*password:).*/\1 <PREENCHER>/' {} +
find "$H/stacks" -name 'config.xml' -exec sed -i -E 's#<(ApiKey|PostgresPassword|Password)>[^<]*</#<\1><PREENCHER></#g' {} +
find "$H/stacks" -path '*bazarr*' -name 'config.yaml' -exec sed -i -E 's/^(\s*(apikey|password|api_key|token)\s*:).*/\1 <PREENCHER>/I' {} +
find "$H/stacks" -name settings.js -exec sed -i -E 's/(credentialSecret\s*:\s*)["'"'"'][^"'"'"']*["'"'"']/\1"<PREENCHER>"/; s/(password\s*:\s*)["'"'"'][^"'"'"']*["'"'"']/\1"<PREENCHER>"/g' {} +

# ---------- leme ----------
LH=/h/leme
mkdir -p "$L/workspace" "$L/home"
rsync -a --exclude '/repos/' --exclude '.git/' --exclude 'node_modules' --exclude '__pycache__' \
  --exclude '.obsidian/workspace*.json' --exclude '/.escritorio/permissoes/' --exclude '/.escritorio/respostas/' \
  "$LH/workspace/" "$L/workspace/"
mkdir -p "$L/home/.claude" "$L/home/.config/systemd/user" "$L/home/.local/bin" "$L/home/.ssh" "$L/home/git"
for f in settings.json CLAUDE.md; do [ -f "$LH/.claude/$f" ] && cp "$LH/.claude/$f" "$L/home/.claude/"; done
for d in agents commands skills hooks; do [ -d "$LH/.claude/$d" ] && rsync -a --exclude synced "$LH/.claude/$d/" "$L/home/.claude/$d/"; done
rsync -a --include '*.service' --include '*.timer' --include '*/' --exclude '*' "$LH/.config/systemd/user/" "$L/home/.config/systemd/user/"
find "$LH/.local/bin" -maxdepth 1 -type f -size -200k | while read -r f; do
  head -c 2 "$f" | grep -q '#!' && cp "$f" "$L/home/.local/bin/"
done
[ -f "$LH/.ssh/config" ] && cp "$LH/.ssh/config" "$L/home/.ssh/config"
[ -f "$LH/.gitconfig" ] && cp "$LH/.gitconfig" "$L/home/.gitconfig"
[ -d "$LH/git" ] && ls "$LH/git" > "$L/home/git/REPOS-CENTRAIS.txt"
mkdir -p "$L/home/.config/leme-escritorio"
for e in "$LH"/.config/leme-escritorio/*; do
  [ -f "$e" ] || continue
  sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)=.*/\1=<PREENCHER>/' "$e" > "$L/home/.config/leme-escritorio/$(basename "$e").example"
done
{
  echo "# Segredos que NÃO estão no backup (recriar à mão no PC novo)"
  echo
  echo "## Usuário leme"
  for f in .claude/.credentials.json .config/gh/hosts.yml .config/leme-escritorio/atlassian.env .config/leme-escritorio/qa.env; do
    [ -e "$LH/$f" ] && echo "- \`~/$f\`"
  done
  for k in "$LH"/.ssh/id_*; do case "$k" in *.pub) ;; *) [ -f "$k" ] && echo "- \`~/.ssh/$(basename "$k")\` (pública: $(cat "$k.pub" 2>/dev/null | cut -d' ' -f1-2 | cut -c1-40)…)";; esac; done
} > "$L/SEGREDOS.md"

chown -R "$U:$G" /out
CONTAINER

# ---------- sistema (como glauco) ----------
SYS="$REPO_H/sistema"; mkdir -p "$SYS"
apt-mark showmanual 2>/dev/null | sort > "$SYS/pacotes-apt.txt" || true
getent passwd | awk -F: '$3>=1000 && $3<65000 {print $1":"$3":"$4":"$6":"$7}' > "$SYS/usuarios.txt"
getent group | awk -F: '$3>=1000 && $3<65000 || $1=="docker" || $1=="sudo" {print}' > "$SYS/grupos.txt"
loginctl list-users --no-legend 2>/dev/null > "$SYS/loginctl.txt" || true
for u in $(awk -F: '{print $1}' "$SYS/usuarios.txt"); do echo "$u linger=$(loginctl show-user "$u" -p Linger --value 2>/dev/null || echo ?)"; done > "$SYS/linger.txt"
crontab -l > "$SYS/crontab-glauco.txt" 2>/dev/null || true
docker ps --format '{{.Names}}\t{{.Image}}' | sort > "$SYS/containers.txt"
lsb_release -ds > "$SYS/os.txt" 2>/dev/null || true
{
  echo "# Segredos que NÃO estão no backup (recriar à mão no PC novo)"
  echo
  echo "## Homelab"
  ( cd "$REPO_H/stacks" && find . -name '.env.example' | sed 's#^\./#- `~/homelab/stacks/#; s#\.example$#` (chaves em .env.example)#' )
  grep -rl '<PREENCHER>' "$REPO_H/stacks" --exclude='.env.example' | sed "s#$REPO_H/stacks/#- \`~/homelab/stacks/#; s#\$#\` (campos <PREENCHER>)#"
  echo
  echo "## Configuração que vive em banco (não está no backup; reconfigurar pela UI)"
  echo "- Radarr, Sonarr, Prowlarr, Bazarr: indexadores, perfis, conexões (config.xml está aqui, sem ApiKey)"
  echo "- Jellyfin: usuários, bibliotecas, plugins"
  echo "- Home Assistant: integrações e dispositivos (.storage); YAMLs estão aqui"
  echo "- Uptime Kuma (o AutoKuma recria os monitores das labels), Scrutiny, AdGuard (estatísticas)"
  echo "- Immich e Nextcloud: contas e dados (fora do escopo deste backup)"
  echo "- Usuário hermes (Hermes Agent): fora deste backup"
} > "$REPO_H/SEGREDOS.md"

# ---------- pipe de mídia: configuração pelas APIs, sem segredos ----------
python3 -I "$HOME_G/homelab/scripts/exportar-media.py" "$REPO_H/stacks/media/export" >>"$LOG" 2>&1 || log "exportar-media falhou (segue o backup sem a exportação)"

# ---------- trava: nada com cara de segredo vai para o GitHub ----------
PAT='(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|ATATT[A-Za-z0-9_-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|"accessToken"\s*:\s*"[^"]{20,}|"refreshToken"\s*:\s*"[^"]{20,})'
ACHOU=$( { grep -rIlE "$PAT" "$REPO_H" "$REPO_L" --exclude-dir=.git; grep -rIliE '"(api[_-]?key|password|passwd|token|secret)"[[:space:]]*:[[:space:]]*"[^"<]{6,}"' "$REPO_H" "$REPO_L" --exclude-dir=.git; } 2>/dev/null | sort -u || true)
if [ -n "$ACHOU" ]; then
  log "ABORTADO: possível segredo em:"; echo "$ACHOU" | tee -a "$LOG"; exit 2
fi

commit_push() {
  local dir=$1 name=$2
  cd "$dir"
  [ -d .git ] || { git init -q -b main; git config user.name "homelab-backup"; git config user.email "84851621+Lombeira@users.noreply.github.com"; }
  git add -A
  if git diff --cached --quiet; then log "$name: sem mudanças"; else git commit -qm "backup $(date '+%F %H:%M')"; log "$name: commit $(git rev-parse --short HEAD) ($(git show --stat --oneline HEAD | tail -1))"; fi
  if [ "$PUSH" = 1 ] && git remote get-url origin >/dev/null 2>&1; then
    git push -q origin main 2>>"$LOG" && log "$name: push ok" || log "$name: push FALHOU"
  fi
}
commit_push "$REPO_H" homelab-config
commit_push "$REPO_L" leme-escritorio-config
log "tamanho: homelab $(du -sh --exclude=.git "$REPO_H" | cut -f1), leme $(du -sh --exclude=.git "$REPO_L" | cut -f1)"
