#!/bin/sh
# Sobe todos os stacks do homelab de uma vez
for d in "$HOME"/homelab/stacks/*/; do
  if [ -f "$d/docker-compose.yml" ] || [ -f "$d/compose.yaml" ]; then
    echo ">> subindo $(basename "$d")"
    ( cd "$d" && docker compose up -d )
  fi
done
[ -d "$HOME/dockge" ] && ( echo ">> dockge"; cd "$HOME/dockge" && docker compose up -d )
echo "FEITO - tudo no ar"
