# Exportação da pipe de mídia

Gerada toda noite pelo backup a partir das APIs locais. Segredos viram `<PREENCHER>`.

Para restaurar: subir os containers, pegar a API key nova de cada app (Settings > General) e reenviar cada seção
pela mesma API (POST para listas como indexer/downloadclient/qualityprofile; PUT para config/*), preenchendo os
`<PREENCHER>` com os valores do gerenciador de senhas. Ordem sugerida: qBittorrent > Prowlarr (indexadores) >
Radarr/Sonarr (pastas, perfis, cliente) > Prowlarr applications > Bazarr > Seerr > Jellyfin.

- radarr: 20 seções, falharam: importlistexclusion (404)
- sonarr: 23 seções
- prowlarr: 10 seções
- bazarr: 3 seções
- seerr: settings.json
- jellyseerr: settings.json
- qbittorrent: qBittorrent.conf (redigido) + categorias
- jellyfin: 7 arquivos de config e bibliotecas
