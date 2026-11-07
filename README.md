# Homelab — como reconstruir ou migrar

Tudo roda em Docker. Cada serviço é uma pasta em `~/homelab/stacks/<nome>`
com `docker-compose.yml` (+ `.env` com as senhas). O Dockge fica em `~/dockge`.

## Antes de tudo
- **Usuário:** os caminhos assumem o usuário `glauco` (`/home/glauco`).
  Se for outro nome, troque `/home/glauco` nos composes.
- **IP:** os serviços apontam para `192.168.1.173`. O jeito mais fácil:
  no roteador (Archer), **reserve o 192.168.1.173 para o MAC do PC novo**.
  Assim nada precisa mudar. Pra ver onde o IP aparece:
  `grep -rl 192.168.1.173 ~/homelab/stacks ~/dockge`
- **DNS da casa:** o roteador entrega o AdGuard (`192.168.1.173`) como DNS.
  Durante a troca de PC a internet da casa pode cair; se precisar, volte o
  DNS do roteador pro automático temporariamente.

## Caminho A — migrar COM os dados (PC antigo e novo ligados)
1. PC novo: instale Ubuntu, crie o usuário `glauco`, copie a pasta
   `~/homelab/scripts` pra ele e rode: `sudo ~/homelab/scripts/bootstrap.sh`
2. PC antigo: pare tudo (evita banco corrompido):
   `for d in ~/homelab/stacks/*/ ~/dockge/; do (cd "$d" && docker compose down); done`
3. PC antigo: empacote tudo, preservando dono e hardlinks dos filmes:
   `sudo tar --numeric-owner -cpf /tmp/homelab-full.tar -C /home/glauco homelab dockge`
4. Copie pro PC novo (`scp /tmp/homelab-full.tar glauco@IP_DO_NOVO:/tmp/`) e extraia:
   `sudo tar --numeric-owner -xpf /tmp/homelab-full.tar -C /home/glauco`
5. Desligue o PC antigo, reserve o `.173` pro PC novo no roteador, reinicie o novo.
6. `~/homelab/up-all.sh`

## Caminho B — reconstruir SÓ a configuração (sem dados)
Usa o `homelab-config.tar.gz` (receitas + configurações, sem fotos/filmes/arquivos).
1. `sudo ~/homelab/scripts/bootstrap.sh` (depois saia e entre de novo)
2. `sudo tar --numeric-owner -xzpf homelab-config.tar.gz -C /home/glauco`
3. `~/homelab/up-all.sh`
Tudo volta configurado (API keys, conexões, dashboard, AdGuard, Home Assistant),
mas Immich, Nextcloud e as bibliotecas de mídia começam vazios.

## GPU
- `scripts/install_nvidia_toolkit.sh` libera a GPU NVIDIA pro Docker (o bootstrap chama).
- Sem GPU NVIDIA: apague o bloco `deploy:` de `stacks/jellyfin/docker-compose.yml`.
- Com GPU nova: no Jellyfin, Painel → Reprodução → Transcodificação → NVIDIA NVENC
  e marque os codecs que a placa suporta.

## Serviços
| Serviço | Endereço |
|---|---|
| Dashboard (Homepage) | http://nossa.casa (porta 80 via Caddy) / :3002 |
| Home Assistant | :8123 |
| AdGuard (DNS na :53) | :8081 |
| Uptime Kuma (+ AutoKuma) | :3001 |
| Scrutiny | :8087 |
| Dockge | :5001 |
| Immich | :2283 |
| Nextcloud | :8084 |
| Jellyfin | :8096 |
| Seerr | :5055 |
| Radarr / Sonarr / Prowlarr | :7878 / :8989 / :9696 |
| qBittorrent | :8088 |
| Bazarr | :6767 |
| FlareSolverr | :8191 |

## Convenções
- App novo ganha labels `homepage.*` (aparece no dashboard) e `kuma.*` (vira monitor).
- Pasta de mídia compartilhada: `~/homelab/media` = `/data` nos apps do stack de mídia
  e `/media` no Jellyfin.
- `scripts/archive/` e `archive/` guardam scripts e backups antigos (pode ignorar).

## Atualizar o pacote de configuração
Gere de novo sempre que mudar algo importante (roda como root via container,
senão arquivos de root, como o AdGuardHome.yaml e o login do HA, ficam de fora):
`~/homelab/scripts/backup-config.sh`

## Automações de luz (Home Assistant)
- **Alerta luminoso**: webhook `http://192.168.1.173:8123/api/webhook/slack-leme-e816fd8085ea`
  - cor opcional na URL: `?cor=hotpink` (padrão azul-celeste). Pisca abajour do escritório,
    spots e Sanca; termina em branco quente e restaura o estado anterior.
  - Disparado pelo **MacroDroid** no celular (não fica no servidor, recriar à mão):
    - Slack → POST na URL (restrição: seg–sex, horário comercial)
    - WhatsApp, título contém o contato → POST na URL com `?cor=...`
- **Modo cinema na sala**: webhook `jellyfin-cinema-2314175daf90`, chamado pelo plugin
  **Webhook** do Jellyfin (destino *Generic*, Send All Properties, cabeçalho
  `Content-Type: application/json`, eventos PlaybackStart/Progress/Stop).
  Usa o ajudante `input_boolean.cinema_pausado`.
  Play: apaga a casa toda menos a Sanca (1%). Pause e fim: "modo pipoca".
- Lâmpadas coloridas usam o perfil **rgbcw_lightbulb** do Tuya Local (o `rgbwc` inverte
  quente/frio nessas lâmpadas Elgin).
