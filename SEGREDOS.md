# Segredos que NÃO estão no backup (recriar à mão no PC novo)

## Homelab
- `~/homelab/stacks/immich/.env` (chaves em .env.example)
- `~/homelab/stacks/nextcloud/.env` (chaves em .env.example)
- `~/homelab/stacks/autokuma/.env` (chaves em .env.example)
- `~/homelab/stacks/adguard/.env` (chaves em .env.example)
- `~/homelab/stacks/nodered/data/settings.js` (campos <PREENCHER>)
- `~/homelab/stacks/media/bazarr/config/config.yaml` (campos <PREENCHER>)
- `~/homelab/stacks/media/radarr/config.xml` (campos <PREENCHER>)
- `~/homelab/stacks/media/sonarr/config.xml` (campos <PREENCHER>)
- `~/homelab/stacks/media/prowlarr/config.xml` (campos <PREENCHER>)
- `~/homelab/stacks/adguard/conf/AdGuardHome.yaml` (campos <PREENCHER>)
- `~/homelab/stacks/homeassistant/config/secrets.yaml.example` (campos <PREENCHER>)

## Configuração que vive em banco (não está no backup; reconfigurar pela UI)
- Radarr, Sonarr, Prowlarr, Bazarr: indexadores, perfis, conexões (config.xml está aqui, sem ApiKey)
- Jellyfin: usuários, bibliotecas, plugins
- Home Assistant: integrações e dispositivos (.storage); YAMLs estão aqui
- Uptime Kuma (o AutoKuma recria os monitores das labels), Scrutiny, AdGuard (estatísticas)
- Immich e Nextcloud: contas e dados (fora do escopo deste backup)
- Usuário hermes (Hermes Agent): fora deste backup
