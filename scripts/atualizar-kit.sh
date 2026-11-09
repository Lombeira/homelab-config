#!/bin/bash
# Grava no pendrive de instalação do Ubuntu o kit completo do homelab (com segredos, CRIPTOGRAFADO).
# Uso: sudo ~/homelab/scripts/atualizar-kit.sh          (pergunta qual pendrive)
#      sudo ~/homelab/scripts/atualizar-kit.sh --auto   (agendado: sem perguntas; só grava num pendrive que já tem kit-homelab)
# Com kit-chave-publica.asc (criar-chave-kit.sh), tranca com a chave pública e não pede senha.
# Sem ela, pede a senha do kit (gerenciador de senhas: "kit homelab"). Nada do instalador é alterado.
{
set -euo pipefail
AUTO=0; [ "${1:-}" = "--auto" ] && AUTO=1
[ "$(id -u)" = 0 ] || { echo "Rode com sudo: sudo $0"; exit 1; }
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
PUB="$SCRIPTS/kit-chave-publica.asc"
DATA=$(date +%Y%m%d-%H%M)
STATUS=/home/glauco/homelab/stacks/homepage/status/kit.json
GRAVOU=0; RESULTADO=""
escreve_status() {
  local rc=$1 res="$RESULTADO"
  [ -n "$res" ] || res="erro (código $rc)"
  mkdir -p "$(dirname "$STATUS")"
  python3 - "$STATUS" "$GRAVOU" "$res" <<'PY' || true
import json, sys, datetime, os
p, gravou, res = sys.argv[1], sys.argv[2] == "1", sys.argv[3]
try:
    old = json.load(open(p))
except Exception:
    old = {}
agora = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
novo = {"ultimo_ok": agora if gravou else old.get("ultimo_ok"), "tentativa": agora, "resultado": res}
tmp = p + ".tmp"
json.dump(novo, open(tmp, "w"), ensure_ascii=False)
os.chmod(tmp, 0o644); os.replace(tmp, p)
PY
}
trap 'escreve_status $?' EXIT
echo "== $(date '+%F %T') atualizar-kit$([ $AUTO = 1 ] && echo ' (automático)')"
[ $AUTO = 1 ] && [ ! -f "$PUB" ] && { echo "Sem kit-chave-publica.asc: o modo automático precisa da chave (rode criar-chave-kit.sh)."; exit 1; }

DEV=$(lsblk -rpno NAME,TRAN,TYPE | awk '$2=="usb"{d=$1} END{print d}')
PART=$(lsblk -rpno NAME,FSTYPE "$DEV" 2>/dev/null | awk '$2!=""{print $1; exit}')
if [ -z "${PART:-}" ]; then
  [ $AUTO = 1 ] && { echo "Pendrive não está plugado: nada a fazer."; RESULTADO="pendrive não plugado"; exit 0; }
  echo "Nenhum pendrive USB encontrado."; exit 1
fi
echo "Pendrive: $PART ($(lsblk -no LABEL,SIZE "$PART" | head -1))"
if [ $AUTO = 0 ]; then read -r -p "É esse? [s/N] " ok; [ "$ok" = s ] || { RESULTADO="cancelado"; exit 1; }; fi

for velho in $(findmnt -rn -o TARGET -S "$PART"); do echo "Desmontando montagem antiga em $velho"; umount "$velho" || { echo "Não consegui desmontar $velho"; exit 1; }; done
MNT=$(mktemp -d)
trap 'rc=$?; sync; umount "$MNT" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; escreve_status $rc' EXIT
mount -o rw "$PART" "$MNT"
findmnt -rn -o OPTIONS "$MNT" | grep -q '^rw' || { echo "O pendrive montou só leitura. Rode 'sudo fsck.vfat -a $PART' e tente de novo."; exit 1; }
[ -d "$MNT/casper" ] && echo "Instalador do Ubuntu encontrado: os arquivos dele não serão tocados."
KIT="$MNT/kit-homelab"
[ $AUTO = 1 ] && [ ! -d "$KIT" ] && { echo "Esse pendrive não tem kit-homelab/: no modo automático não gravo em pendrive desconhecido."; exit 1; }
if [ -f "$PUB" ]; then
  CRIPTO=(gpg --batch --trust-model always --recipient-file "$PUB" --encrypt -o -)
  [ -f "$KIT/chave-privada.asc" ] || echo "!! Atenção: não há kit-homelab/chave-privada.asc neste pendrive. Sem ela o kit não abre."
else
  CRIPTO=(gpg --symmetric --cipher-algo AES256 --pinentry-mode loopback -o -)
fi
rm -rf "$KIT/novo"; mkdir -p "$KIT/novo"

echo "== Gerando o arquivo (alguns minutos)..."
crontab -u glauco -l > /home/glauco/.crontab-glauco 2>/dev/null || true
apt-mark showmanual > /home/glauco/.pacotes-apt 2>/dev/null || true
cd /
rm -f /tmp/kit-zstd-rc
set +e
tar --numeric-owner -cpf - --warning=no-file-changed --warning=no-file-removed --exclude-from="$SCRIPTS/kit-excludes.txt" home/glauco home/leme home/hermes 2>/tmp/kit-tar.err \
  | zstd -T0 -10 -q \
  | tee >(zstd -tq 2>/dev/null; echo $? > /tmp/kit-zstd-rc) \
  | "${CRIPTO[@]}" \
  | split -b 3900M -d -a 2 - "$KIT/novo/homelab-$DATA.tar.zst.gpg.part"
RC=("${PIPESTATUS[@]}")
set -e
if [ "${RC[0]}" -gt 1 ] || [ "${RC[1]}" != 0 ] || [ "${RC[2]}" != 0 ] || [ "${RC[3]}" != 0 ] || [ "${RC[4]}" != 0 ]; then
  echo "!! Falhou ao gerar (tar=${RC[0]} zstd=${RC[1]} tee=${RC[2]} gpg=${RC[3]} split=${RC[4]}). Kit anterior mantido."
  tail -5 /tmp/kit-tar.err 2>/dev/null
  rm -rf "$KIT/novo"; exit 2
fi
[ "${RC[0]}" = 1 ] && echo "   (alguns arquivos mudaram durante a cópia: normal com o escritório rodando)"
rm -f /home/glauco/.crontab-glauco /home/glauco/.pacotes-apt

echo "== Conferindo..."
( cd "$KIT/novo" && sha256sum homelab-*.part* > SHA256SUMS )
if [ -f "$PUB" ]; then
  for _ in $(seq 120); do [ -s /tmp/kit-zstd-rc ] && break; sleep 1; done
  [ "$(cat /tmp/kit-zstd-rc 2>/dev/null)" = 0 ] || { echo "!! O arquivo compactado veio corrompido. Kit anterior mantido."; rm -rf "$KIT/novo"; exit 2; }
  PACOTES=$(head -c 65536 "$(ls "$KIT/novo"/homelab-*.part* | head -1)" | gpg --batch --list-packets 2>/dev/null || true)
  grep -q '^:pubkey enc packet' <<<"$PACOTES" \
    || { echo "!! O arquivo gerado não parece criptografado com a chave do kit. Kit anterior mantido."; rm -rf "$KIT/novo"; exit 2; }
else
  cat "$KIT/novo"/homelab-*.part* | gpg --pinentry-mode loopback -d 2>/dev/null | zstd -dq | tar -tf - >/dev/null \
    || { echo "!! O arquivo gerado não abriu. Kit anterior mantido."; rm -rf "$KIT/novo"; exit 2; }
fi
rm -f /tmp/kit-zstd-rc

cp "$SCRIPTS/restaurar.sh" "$KIT/novo/restaurar.sh"
cat > "$KIT/novo/LEIA-ME.txt" <<TXT
KIT DE RESTAURAÇÃO DO HOMELAB ($DATA)

1. Dê boot por este pendrive e instale o Ubuntu Server/Desktop.
   Crie o usuário "glauco" (é o primeiro usuário, UID 1000).
2. Depois de instalado, plugue este pendrive, abra um terminal e rode:
     sudo bash /media/glauco/*/kit-homelab/restaurar.sh
   (ou monte o pendrive e rode o restaurar.sh desta pasta)
3. Digite a senha do kit (gerenciador de senhas: "kit homelab").
   O kit é aberto pela chave-privada.asc (na pasta kit-homelab), que é protegida por essa senha.
   Se o pendrive perder a chave, use uma das cópias (Drive, e-mail) e ponha em kit-homelab/.

O que tem aqui: configurações e segredos de ~/homelab, ~/dockge, usuário leme (escritório + esteira)
e usuário hermes. NÃO tem: filmes, fotos do Immich, arquivos do Nextcloud.
TXT
rm -rf "$KIT/atual.old"; [ -d "$KIT/atual" ] && mv "$KIT/atual" "$KIT/atual.old"
mv "$KIT/novo" "$KIT/atual"; rm -rf "$KIT/atual.old"
GRAVOU=1
sync

echo "== Imagens Docker (só regrava se alguma mudou)"
IMGS=""; FORA=""
for i in $(docker ps -a --format '{{.Image}}' | grep -v -E '^(ensaio-ubuntu|alpine:3)$' | sort -u); do
  if docker image inspect "$i" >/dev/null 2>&1; then IMGS="$IMGS $i"; else FORA="$FORA $i"; fi
done
[ -n "$FORA" ] && echo "   fora do pendrive (fixadas por digest; baixam da internet na restauração):$FORA"
MAN_NOVO=$(for i in $IMGS; do echo "$i $(docker image inspect -f '{{.Id}}' "$i" 2>/dev/null)"; done)
if [ -f "$KIT/imagens/MANIFEST" ] && [ "$MAN_NOVO" = "$(cat "$KIT/imagens/MANIFEST")" ]; then
  echo "   nenhuma imagem mudou: mantidas as do pendrive ($(du -sh "$KIT/imagens" | cut -f1))"
else
  rm -rf "$KIT/imagens-novo"; mkdir -p "$KIT/imagens-novo"
  echo "   gravando $(echo $IMGS | wc -w) imagens (uns 15 min na primeira vez)..."
  set +e
  docker save $IMGS | zstd -T0 -3 -q | split -b 3900M -d -a 2 - "$KIT/imagens-novo/imagens.tar.zst.part"
  RCI=("${PIPESTATUS[@]}"); set -e
  if [ "${RCI[0]}" = 0 ] && [ "${RCI[1]}" = 0 ] && [ "${RCI[2]}" = 0 ] && cat "$KIT/imagens-novo"/imagens.tar.zst.part* | zstd -tq; then
    echo "$MAN_NOVO" > "$KIT/imagens-novo/MANIFEST"
    rm -rf "$KIT/imagens"; mv "$KIT/imagens-novo" "$KIT/imagens"
    echo "   imagens gravadas: $(du -sh "$KIT/imagens" | cut -f1)"
  else
    echo "!! falhou ao gravar as imagens (save=${RCI[0]} zstd=${RCI[1]} split=${RCI[2]}); o kit continua válido, só sem imagens novas"
    rm -rf "$KIT/imagens-novo"
  fi
  sync
fi
echo
echo "Kit gravado: $(du -sh "$KIT/atual" | cut -f1) em kit-homelab/atual/ ($(ls "$KIT/atual" | grep -c part) parte(s))"
RESULTADO="gravado"
echo "Livre no pendrive: $(df -h "$MNT" | awk 'NR==2{print $4}'). Pode tirar o pendrive."
exit
}
