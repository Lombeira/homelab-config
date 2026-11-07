#!/usr/bin/env -S python3 -I
"""Exporta a configuração da pipe de mídia (Radarr, Sonarr, Prowlarr, Bazarr, Seerr, qBittorrent, Jellyfin)
para JSON/arquivos sem segredos. Campos sensíveis viram "<PREENCHER>".
Uso: exportar-media.py <pasta-destino>
"""
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

MEDIA = Path.home() / "homelab" / "stacks" / "media"
JELLY = Path.home() / "homelab" / "stacks" / "jellyfin" / "config"
OUT = Path(sys.argv[1])
P = "<PREENCHER>"
SENS = re.compile(r"(api[_-]?key|apikey|password|passwd|pass$|secret|token|cookie|username|user_?name|^user$|login|auth|hash|session|salt|key$)", re.I)
NAO_SENS = re.compile(r"(^(enable|use|privacy|keys|hotkeys?|keyword|keywords|authmethod|authenticationmethod|authenticationrequired|authrequired)$)", re.I)
resultado = []


def limpa(o, k=None):
    if isinstance(o, dict):
        if "privacy" in o and "value" in o and o.get("privacy") not in (None, "normal"):
            o = dict(o)
            if o.get("value") not in (None, "", [], 0, False):
                o["value"] = P
            return o
        return {kk: limpa(v, kk) for kk, v in o.items()}
    if isinstance(o, list):
        return [limpa(v, k) for v in o]
    if isinstance(o, str) and k and SENS.search(k) and not NAO_SENS.search(k) and o.strip():
        return P
    return o


def get(url, headers):
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read() or b"null")


def xml_key(path):
    m = re.search(r"<ApiKey>([^<]+)</ApiKey>", path.read_text(encoding="utf-8", errors="replace"))
    return m.group(1) if m else None


def salva(nome, dados):
    f = OUT / f"{nome}.json"
    f.write_text(json.dumps(limpa(dados), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def exporta_arr(nome, porta, versao, endpoints):
    cfg = MEDIA / nome / "config.xml"
    if not cfg.exists():
        resultado.append(f"{nome}: sem config.xml")
        return
    key = xml_key(cfg)
    base = f"http://127.0.0.1:{porta}/api/{versao}/"
    dump, falhas = {}, []
    for ep in endpoints:
        try:
            dump[ep] = get(base + ep, {"X-Api-Key": key})
        except Exception as e:
            falhas.append(f"{ep} ({getattr(e, 'code', type(e).__name__)})")
    salva(nome, dump)
    resultado.append(f"{nome}: {len(dump)} seções" + (f", falharam: {', '.join(falhas)}" if falhas else ""))


OUT.mkdir(parents=True, exist_ok=True)
for f in OUT.iterdir():
    f.unlink() if f.is_file() else shutil.rmtree(f)

COMUM = ["qualityprofile", "qualitydefinition", "customformat", "rootfolder", "downloadclient", "indexer",
         "notification", "importlist", "importlistexclusion", "delayprofile", "tag", "metadata", "remotepathmapping",
         "autotagging", "config/naming", "config/mediamanagement", "config/indexer", "config/downloadclient",
         "config/importlist", "config/ui", "config/host"]
exporta_arr("radarr", 7878, "v3", COMUM)
exporta_arr("sonarr", 8989, "v3", COMUM + ["releaseprofile", "languageprofile"])
exporta_arr("prowlarr", 9696, "v1", ["indexer", "applications", "appprofile", "downloadclient", "notification",
                                     "indexerproxy", "tag", "config/host", "config/ui", "config/downloadclient"])

bz = MEDIA / "bazarr" / "config" / "config.yaml"
if bz.exists():
    m = re.search(r"^auth:\s*\n(?:\s+.*\n)*?\s+apikey:\s*([^\s]+)", bz.read_text(encoding="utf-8", errors="replace"), re.M)
    key = m.group(1).strip("'\"") if m else None
    try:
        dump = {"settings": get("http://127.0.0.1:6767/api/system/settings", {"X-API-KEY": key or ""})}
        for ep in ("system/languages/profiles", "providers"):
            try:
                dump[ep] = get(f"http://127.0.0.1:6767/api/{ep}", {"X-API-KEY": key or ""})
            except Exception:
                pass
        salva("bazarr", dump)
        resultado.append(f"bazarr: {len(dump)} seções")
    except Exception as e:
        resultado.append(f"bazarr: falhou pela API ({getattr(e, 'code', type(e).__name__)}); config.yaml redigido já vai no backup")

for cand in (MEDIA / "seerr" / "settings.json", MEDIA / "jellyseerr" / "settings.json"):
    if cand.exists():
        salva(f"{cand.parent.name}-settings", json.loads(cand.read_text(encoding="utf-8")))
        resultado.append(f"{cand.parent.name}: settings.json")

qb = MEDIA / "qbittorrent" / "qBittorrent"
if qb.exists():
    (OUT / "qbittorrent").mkdir(exist_ok=True)
    conf = qb / "qBittorrent.conf"
    if conf.exists():
        txt = conf.read_text(encoding="utf-8", errors="replace")
        txt = re.sub(r"^((?:[\w\\]*)(?:Password|Password_PBKDF2|Username|ApiKey|Secret|Token|Cookie)[\w]*)=.*$", rf"\1={P}", txt, flags=re.M | re.I)
        (OUT / "qbittorrent" / "qBittorrent.conf").write_text(txt, encoding="utf-8")
    for extra in ("categories.json", "watched_folders.json"):
        if (qb / extra).exists():
            shutil.copy(qb / extra, OUT / "qbittorrent" / extra)
    resultado.append("qbittorrent: qBittorrent.conf (redigido) + categorias")

if JELLY.exists():
    jd = OUT / "jellyfin"
    n = 0
    for src in list(JELLY.glob("config/*.xml")) + list(JELLY.glob("root/default/*/options.xml")) + list(JELLY.glob("root/default/*/*.mblink")):
        rel = src.relative_to(JELLY)
        (jd / rel.parent).mkdir(parents=True, exist_ok=True)
        txt = src.read_text(encoding="utf-8", errors="replace")
        txt = re.sub(r"<(\w*(?:Password|ApiKey|Token|Secret|Key))>[^<]+</", rf"<\1>{P}</", txt)
        (jd / rel).write_text(txt, encoding="utf-8")
        n += 1
    resultado.append(f"jellyfin: {n} arquivos de config e bibliotecas")

(OUT / "LEIA-ME.md").write_text(
    "# Exportação da pipe de mídia\n\n"
    "Gerada toda noite pelo backup a partir das APIs locais. Segredos viram `<PREENCHER>`.\n\n"
    "Para restaurar: subir os containers, pegar a API key nova de cada app (Settings > General) e reenviar cada seção\n"
    "pela mesma API (POST para listas como indexer/downloadclient/qualityprofile; PUT para config/*), preenchendo os\n"
    "`<PREENCHER>` com os valores do gerenciador de senhas. Ordem sugerida: qBittorrent > Prowlarr (indexadores) >\n"
    "Radarr/Sonarr (pastas, perfis, cliente) > Prowlarr applications > Bazarr > Seerr > Jellyfin.\n\n"
    + "\n".join(f"- {r}" for r in resultado) + "\n", encoding="utf-8")
print("\n".join(resultado))
