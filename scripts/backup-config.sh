#!/bin/sh
# Gera ~/homelab/homelab-config.tar.gz: composes, .env e configs (sem dados pesados).
# Roda o tar como root dentro de um container pra incluir arquivos criados como root.
set -e
docker run --rm -v "$HOME":/g -w /g alpine sh -c "tar czf /g/homelab/homelab-config.tar.gz --numeric-owner \
  --exclude=homelab/scripts/archive \
  --exclude=*/immich/library --exclude=*/immich/postgres --exclude=*/immich/model-cache \
  --exclude=*/nextcloud/html --exclude=*/nextcloud/db \
  --exclude=*/jellyfin/cache --exclude=*/jellyfin/config/metadata --exclude=*/jellyfin/config/data/subtitles --exclude=*/jellyfin/config/transcodes \
  --exclude=*/scrutiny/influxdb --exclude=*/seerr/cache \
  --exclude=*/bazarr/cache --exclude=*/bazarr/backup --exclude=*/bazarr/log \
  --exclude=*/radarr/MediaCover --exclude=*/sonarr/MediaCover \
  --exclude=*/radarr/logs --exclude=*/sonarr/logs --exclude=*/prowlarr/logs \
  --exclude=*/radarr/Backups --exclude=*/sonarr/Backups --exclude=*/prowlarr/Backups \
  --exclude=*.db-wal --exclude=*.db-shm \
  homelab/stacks homelab/up-all.sh homelab/scripts homelab/README.md dockge 2>&1 | grep -v 'socket ignored' || true; \
  chown $(id -u):$(id -g) /g/homelab/homelab-config.tar.gz"
echo "Backup de configuração: $(du -h "$HOME/homelab/homelab-config.tar.gz" | cut -f1) em ~/homelab/homelab-config.tar.gz"
