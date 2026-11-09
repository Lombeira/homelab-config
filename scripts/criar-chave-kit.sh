#!/bin/bash
# Cria o par de chaves do kit: a pública fica no servidor (tranca o kit sem senha, permite agendar)
# e a privada, protegida pela senha do kit, vai para o pendrive. Nenhuma cópia da privada fica no servidor.
# Uso: sudo bash ~/homelab/scripts/criar-chave-kit.sh   (com o pendrive do kit plugado)
{
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "Rode com sudo: sudo bash $0"; exit 1; }
SCRIPTS="$(cd "$(dirname "$0")" && pwd)"
PUB="$SCRIPTS/kit-chave-publica.asc"
[ -f "$PUB" ] && { echo "Já existe uma chave em $PUB. Apague-a antes se quiser criar outra."; exit 1; }

DEV=$(lsblk -rpno NAME,TRAN,TYPE | awk '$2=="usb"{d=$1} END{print d}')
PART=$(lsblk -rpno NAME,FSTYPE "$DEV" 2>/dev/null | awk '$2!=""{print $1; exit}')
[ -n "${PART:-}" ] || { echo "Nenhum pendrive USB encontrado."; exit 1; }
for velho in $(findmnt -rn -o TARGET -S "$PART"); do umount "$velho"; done
MNT=$(mktemp -d); GH=$(mktemp -d); chmod 700 "$GH"
trap 'sync; GNUPGHOME="$GH" gpgconf --kill all 2>/dev/null; pkill -f "gpg-agent --homedir $GH" 2>/dev/null; sleep 1; umount "$MNT" 2>/dev/null || true; rmdir "$MNT" 2>/dev/null || true; rm -rf "$GH"' EXIT
mount -o rw "$PART" "$MNT"
[ -d "$MNT/kit-homelab" ] || { echo "Esse pendrive não tem a pasta kit-homelab. Rode o atualizar-kit.sh uma vez antes."; exit 1; }

echo "Use a MESMA senha do kit (gerenciador de senhas: \"kit homelab\")."
read -r -s -p "Senha do kit: " S1; echo
read -r -s -p "Repita: " S2; echo
[ "$S1" = "$S2" ] || { echo "As senhas não batem."; exit 1; }
[ ${#S1} -ge 12 ] || echo "Aviso: senha curta. A chave privada fica no pendrive, então a senha é o que protege o kit."

export GNUPGHOME="$GH"
printf '%s' "$S1" | gpg --batch -q --pinentry-mode loopback --passphrase-fd 0 \
  --quick-gen-key "Kit homelab <kit@nossa.casa>" rsa4096 encrypt never
FPR=$(gpg --batch --with-colons --list-secret-keys | awk -F: '$1=="fpr"{print $10; exit}')
gpg --batch --armor --export "$FPR" > "$PUB.novo"
printf '%s' "$S1" | gpg --batch --pinentry-mode loopback --passphrase-fd 0 --armor --export-secret-keys "$FPR" > "$MNT/kit-homelab/chave-privada.asc"

echo "== Testando: tranca com a pública e abre com a privada + senha"
TESTE=$(mktemp)
echo "teste-ok" | gpg --batch --trust-model always --recipient-file "$PUB.novo" --encrypt > "$TESTE"
gpgconf --kill all; rm -rf "${GH:?}"/*
gpg --batch -q --import "$MNT/kit-homelab/chave-privada.asc"
R=$(printf '%s' "$S1" | gpg --batch -q --pinentry-mode loopback --passphrase-fd 0 -d "$TESTE" 2>/dev/null || true)
rm -f "$TESTE"; gpgconf --kill all
unset S1 S2
case "$R" in teste-ok) ;; *) echo "!! O teste falhou; nada foi trocado."; rm -f "$PUB.novo" "$MNT/kit-homelab/chave-privada.asc"; exit 2;; esac
mv "$PUB.novo" "$PUB"; chown glauco:glauco "$PUB"
echo
echo "Pronto. Chave pública: $PUB"
echo "Chave privada (protegida pela senha): kit-homelab/chave-privada.asc no pendrive."
echo "Guarde mais uma cópia da chave privada fora daqui (Google Drive, e-mail...): sem a senha ela não abre nada."
echo "Agora rode 'sudo bash $SCRIPTS/atualizar-kit.sh' para gravar o primeiro kit com a chave."
exit
}
