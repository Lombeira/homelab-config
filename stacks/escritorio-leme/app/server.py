import json
import os
import re
import subprocess
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
STATIC = Path(__file__).resolve().parent / "static"
ACTIVE_SECS = int(os.environ.get("ACTIVE_SECS", "120"))
TOOL_MAX_SECS = int(os.environ.get("TOOL_MAX_SECS", "1200"))
RECENT_HOURS = float(os.environ.get("RECENT_HOURS", "12"))
PORT = int(os.environ.get("PORT", "8000"))
FILA_DIR = Path(os.environ.get("FILA_DIR", "/data/glauco/fila"))
RESP_DIR = Path(os.environ.get("RESP_DIR", "/data/glauco/respostas"))
PERM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,80}$")
PERM_TTL_S = int(os.environ.get("PERM_TTL_S", "900"))
NOVOS_DIR = Path(os.environ.get("NOVOS_DIR", "/data/glauco/novos"))
NOVO_ID_RE = re.compile(r"^n\d{10,16}[a-z0-9]{0,6}$")
IMG_NOME_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
MAX_IMGS, MAX_IMG_BYTES = 10, 8 * 1024 * 1024
KEY_RE = re.compile(r"^(?:[A-Z][A-Z0-9]+-\d+|PR-[A-Za-z0-9._-]+-\d+)$")
KEY_PAT = r"(?:[A-Z][A-Z0-9]+-\d+|PR-[A-Za-z0-9._-]+-\d+)"
ACOES = {"triagem", "aprovar", "devolver", "atualizar_pendencias", "retomar", "limpar", "faxina", "remover_anexo", "novo_card", "confirmar_card", "revisar_pr", "sugestao_aprovar", "sugestao_ignorar", "sugestao_duplicada", "sugestao_descartar"}
SUG_ID_RE = re.compile(r"^s[0-9A-Za-z_-]{6,60}$")
PR_URL_RE = re.compile(r"^https://github\.com/(leme-tech)/([A-Za-z0-9._-]+)/pull/(\d+)/?(?:[#?].*)?$")
PESSOAS = {"glauco", "feda"}
DOCS = {"triagem": "triagem.md", "implementacao": "implementacao.md", "review": "review.md", "qa": "qa.md", "aprendizados": "aprendizados-qa.md", "achados": "achados.json"}
IMG_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
TXT = "text/plain; charset=utf-8"
EVID_TYPES = {**IMG_TYPES, ".txt": TXT, ".log": TXT, ".json": TXT, ".md": TXT, ".diff": TXT, ".patch": TXT, ".csv": TXT}


def frontmatter(path):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    meta = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            for line in text[3:end].splitlines():
                m = re.match(r"^\s*([A-Za-z_]+):\s*(.*)$", line)
                if m and m.group(2):
                    meta.setdefault(m.group(1), m.group(2).strip().strip("\"'"))
            body = text[end + 4 :]
    return meta, body


def short(text, size=90):
    text = " ".join(str(text).split())
    return text if len(text) <= size else text[: size - 1] + "…"


def summarize_tool(name, data):
    data = data or {}
    if name == "Bash":
        return "Terminal", short(data.get("description") or data.get("command", ""))
    if name in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        verb = {"Read": "Lendo", "Edit": "Editando", "MultiEdit": "Editando", "Write": "Escrevendo", "NotebookEdit": "Editando"}[name]
        return verb, Path(str(data.get("file_path") or data.get("notebook_path") or "")).name
    if name in ("Grep", "Glob"):
        return "Procurando", short(data.get("pattern", ""))
    if name in ("Agent", "Task"):
        return "Delegando", short(f"{data.get('subagent_type', 'agente')}: {data.get('description', '')}")
    if name == "WebSearch":
        return "Pesquisando", short(data.get("query", ""))
    if name == "WebFetch":
        return "Lendo a web", short(data.get("url", ""))
    if name.startswith("mcp__"):
        parts = name.split("__")
        return short(parts[1].replace("claude_ai_", ""), 30), short(parts[-1].replace("_", " "))
    return name, ""


class Transcript:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.partial = b""
        self.title = None
        self.last_prompt = None
        self.cwd = None
        self.entrypoint = None
        self.agent = None
        self.last_ts = None
        self.state = "idle"
        self.action = None
        self.open_tools = {}

    def update(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self.offset:
            self.__init__(self.path)
        if size == self.offset:
            return
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            chunk = fh.read()
        self.offset += len(chunk)
        lines = (self.partial + chunk).split(b"\n")
        self.partial = lines.pop()
        for raw in lines:
            if raw.strip():
                try:
                    self.consume(json.loads(raw))
                except (ValueError, TypeError, AttributeError):
                    continue

    def consume(self, entry):
        kind = entry.get("type")
        if kind == "ai-title":
            self.title = entry.get("aiTitle") or self.title
            return
        if kind == "agent-setting":
            self.agent = entry.get("agentSetting") or self.agent
            return
        if kind == "last-prompt":
            self.last_prompt = entry.get("lastPrompt") or self.last_prompt
            return
        if kind not in ("user", "assistant"):
            return
        self.cwd = entry.get("cwd") or self.cwd
        self.entrypoint = entry.get("entrypoint") or self.entrypoint
        self.last_ts = entry.get("timestamp") or self.last_ts
        content = (entry.get("message") or {}).get("content")
        if kind == "user":
            if isinstance(content, list) and any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content):
                for c in content:
                    if isinstance(c, dict):
                        self.open_tools.pop(c.get("tool_use_id"), None)
                self.state = "thinking" if not self.open_tools else "tool"
            else:
                self.state = "thinking"
                self.open_tools.clear()
            return
        if not isinstance(content, list):
            return
        tools = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        if tools:
            for t in tools:
                self.open_tools[t.get("id")] = t.get("name")
                verb, detail = summarize_tool(t.get("name", ""), t.get("input"))
                self.action = {"verb": verb, "detail": detail}
            self.state = "tool"
        elif any(isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip() for c in content):
            self.state = "waiting"
            self.action = None


class Store:
    def __init__(self):
        self.transcripts = {}
        self.lock = Lock()

    def transcript(self, path):
        t = self.transcripts.get(path)
        if t is None:
            t = self.transcripts[path] = Transcript(path)
        t.update()
        return t


STORE = Store()


def status_of(t, mtime, now):
    age = now - mtime
    if t.open_tools and t.state == "tool" and age <= TOOL_MAX_SECS:
        return "working"
    if age > ACTIVE_SECS:
        return "idle"
    if t.state == "waiting":
        return "waiting"
    return "working"


def collect_agents(workspace):
    agents = {}
    sources = [workspace / ".claude" / "agents"] + sorted((workspace / "repos").glob("*/.claude/agents"))
    for folder in sources:
        if not folder.is_dir():
            continue
        origin = "workspace" if folder.parent.parent == workspace else folder.parent.parent.name
        for f in sorted(folder.glob("*.md")):
            meta, _ = frontmatter(f)
            name = meta.get("name") or f.stem
            description = meta.get("description", "")
            agents.setdefault(name, {
                "name": name,
                "description": short(description, 160),
                "origin": origin,
                "room": room_for(name, description, meta.get("room")),
            })
    return agents


ROOMS = ("manager", "triagem", "front", "review", "qa")
ROOM_RULES = (
    ("manager", r"manager|gerente|orquestr|orchestr|coordena"),
    ("review", r"review|revis"),
    ("triagem", r"triag|viabil|refin|card|jira|backlog|feasib"),
    ("front", r"front|\bdev\b|dev-|implement|ui\b|componente|react"),
    ("qa", r"\bqa\b|qa-|test|valida|verif"),
)


def room_for(name, description, explicit=None):
    if explicit and explicit.lower() in ROOMS:
        return explicit.lower()
    for text in (name, description):
        for room, pattern in ROOM_RULES:
            if re.search(pattern, text or "", re.IGNORECASE):
                return room
    return "corredor"


def collect_requests(workspace):
    folder = workspace / "notes" / "pedidos"
    requests = []
    if not folder.is_dir():
        return requests
    for f in folder.glob("*.md"):
        meta, body = frontmatter(f)
        if meta.get("status", "aberto").lower() in ("fechado", "resolvido", "done", "closed"):
            continue
        heading = next((l.lstrip("# ").strip() for l in body.splitlines() if l.strip()), "")
        requests.append({
            "title": short(meta.get("title") or heading or f.stem.replace("-", " "), 90),
            "from": meta.get("from") or meta.get("de") or "manager",
            "file": f.name,
            "updated": f.stat().st_mtime,
        })
    requests.sort(key=lambda r: -r["updated"])
    return requests


def collect_sessions(user, claude_dir, now):
    sessions = []
    running = []
    if not claude_dir.is_dir():
        return sessions, running
    cutoff = now - RECENT_HOURS * 3600
    for project in claude_dir.iterdir():
        if not project.is_dir():
            continue
        for jl in project.glob("*.jsonl"):
            try:
                mtime = jl.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            t = STORE.transcript(jl)
            st = status_of(t, mtime, now)
            sessions.append({
                "id": jl.stem,
                "user": user,
                "title": short(t.title or t.last_prompt or "Sessão sem título", 60),
                "project": Path(t.cwd).name if t.cwd else project.name,
                "status": st,
                "headless": (t.entrypoint or "").startswith("sdk"),
                "agent": t.agent,
                "entrypoint": t.entrypoint,
                "action": t.action if st == "working" else None,
                "updated": mtime,
            })
            sub_dir = project / jl.stem / "subagents"
            if not sub_dir.is_dir():
                continue
            for meta_file in sub_dir.glob("*.meta.json"):
                try:
                    meta = json.loads(meta_file.read_text())
                except (OSError, ValueError):
                    continue
                sub_jl = meta_file.with_name(meta_file.name.replace(".meta.json", ".jsonl"))
                try:
                    sub_mtime = sub_jl.stat().st_mtime
                except OSError:
                    continue
                if meta.get("finished") or now - sub_mtime > ACTIVE_SECS:
                    continue
                st_sub = STORE.transcript(sub_jl)
                running.append({
                    "type": meta.get("agentType") or "agente",
                    "task": short(meta.get("description", ""), 70),
                    "user": user,
                    "session": jl.stem[:8],
                    "action": st_sub.action,
                    "updated": sub_mtime,
                })
    sessions.sort(key=lambda s: -s["updated"])
    return sessions, running


def collect_brain(workspace):
    memories = []
    mem_dir = workspace / "memory"
    if mem_dir.is_dir():
        for f in mem_dir.glob("*.md"):
            if f.name == "MEMORY.md":
                continue
            meta, _ = frontmatter(f)
            memories.append({
                "name": meta.get("name") or f.stem,
                "description": short(meta.get("description", ""), 120),
                "type": meta.get("type", ""),
                "updated": f.stat().st_mtime,
            })
    memories.sort(key=lambda m: -m["updated"])
    notes = []
    notes_dir = workspace / "notes"
    if notes_dir.is_dir():
        for f in notes_dir.rglob("*.md"):
            rel = f.relative_to(notes_dir)
            if any(p.startswith(".") for p in rel.parts):
                continue
            notes.append({"path": str(rel), "folder": rel.parts[0] if len(rel.parts) > 1 else "", "updated": f.stat().st_mtime})
    notes.sort(key=lambda n: -n["updated"])
    return {
        "memory_count": len(memories),
        "memories": memories[:8],
        "notes_count": len(notes),
        "inbox_count": sum(1 for n in notes if n["folder"] == "inbox"),
        "notes": notes[:8],
    }


def collect_feed(workspace):
    if not (workspace / ".git").exists():
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "log", "-20", "--format=%h%x1f%an%x1f%at%x1f%s"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    feed = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            feed.append({"hash": parts[0], "author": parts[1], "at": int(parts[2]), "subject": short(parts[3], 90)})
    return feed


def esteira_dir():
    if not DATA_ROOT.is_dir():
        return None
    for home in sorted(DATA_ROOT.iterdir()):
        d = home / "workspace" / ".escritorio"
        if d.is_dir():
            return d
    return None


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def collect_pipeline():
    base = esteira_dir()
    if base is None:
        return {"pendencias": {"updated": None, "items": []}, "cards": [], "fila": [], "rejeicoes": [], "arquivo": []}
    pend = read_json(base / "pendencias.json", {"updated": None, "items": []})
    if not isinstance(pend, dict) or not isinstance(pend.get("items"), list):
        pend = {"updated": None, "items": []}
    cards = []
    cards_dir = base / "cards"
    if cards_dir.is_dir():
        for d in cards_dir.iterdir():
            if not d.is_dir() or not KEY_RE.match(d.name):
                continue
            estado = read_json(d / "estado.json", None)
            if not isinstance(estado, dict):
                continue
            estado["key"] = d.name
            estado["docs"] = [k for k, f in DOCS.items() if (d / f).is_file()]
            ev = d / "evidencias"
            estado["evidencias"] = sorted(f.name for f in ev.iterdir() if f.is_file() and f.suffix.lower() in EVID_TYPES)[:60] if ev.is_dir() else []
            an = d / "anexos"
            estado["anexos"] = sorted(
                ({"nome": f.name, "bytes": f.stat().st_size} for f in an.iterdir() if f.is_file() and not f.name.startswith(".")),
                key=lambda x: x["nome"])[:40] if an.is_dir() else []
            cards.append(estado)
    cards.sort(key=lambda c: -(c.get("atualizado") or 0))
    rejeicoes = []
    proc = base / "fila" / "processados"
    if proc.is_dir():
        now = time.time()
        for f in proc.glob("*.erro"):
            try:
                mt = f.stat().st_mtime
            except OSError:
                continue
            if now - mt > 1800:
                continue
            item = read_json(f.with_name(f.name[:-5]), {}) or {}
            rejeicoes.append({
                "id": f.name[:-5],
                "key": item.get("key"),
                "acao": item.get("acao"),
                "por": item.get("por"),
                "motivo": short(f.read_text(encoding="utf-8", errors="replace").strip(), 300),
                "em": mt,
            })
        rejeicoes.sort(key=lambda r: -r["em"])
    fila = []
    fila_dir = base / "fila"
    if fila_dir.is_dir():
        for f in sorted(fila_dir.glob("*.json")):
            item = read_json(f, None)
            if isinstance(item, dict):
                fila.append({k: item.get(k) for k in ("key", "acao", "por", "em", "arquivo", "sugestao", "novo")})
    arquivo = []
    arq = base / "arquivo.jsonl"
    if arq.is_file():
        for line in arq.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("key"):
                arquivo.append({k: r.get(k) for k in ("key", "summary", "assignee", "etapa_final", "pr_url", "merged_em", "custo_usd", "concluido_em", "limpo_em", "por")})
    config = read_json(base / "config.json", {}) or {}
    usage = read_json(base / "usage.json", None)
    return {"pendencias": pend, "cards": cards, "fila": fila, "rejeicoes": rejeicoes[:20], "arquivo": arquivo,
            "config": {"max_ativos": config.get("max_ativos")},
            "usage": usage if isinstance(usage, dict) else None}


def collect_permissions(now):
    base = esteira_dir()
    if base is None:
        return []
    pend = base / "permissoes"
    answered = base / "respostas"
    out = []
    if not pend.is_dir():
        return out
    for f in pend.glob("*.json"):
        if not PERM_ID_RE.match(f.stem):
            continue
        item = read_json(f, None)
        if not isinstance(item, dict):
            continue
        criado = item.get("criado") or f.stat().st_mtime
        if now - criado > PERM_TTL_S:
            continue
        out.append({
            "id": f.stem,
            "session_id": item.get("session_id"),
            "agente": item.get("agente"),
            "card": item.get("card"),
            "ferramenta": short(item.get("ferramenta") or "", 40),
            "resumo": short(item.get("resumo") or "", 140),
            "detalhe": str(item.get("detalhe") or "")[:2000],
            "cwd": item.get("cwd"),
            "criado": criado,
            "respondida": (answered / f.name).exists(),
        })
    out.sort(key=lambda x: x["criado"])
    return out


def answer_permission(payload):
    pid = str(payload.get("id", ""))
    decisao = str(payload.get("decisao", ""))
    por = str(payload.get("por", "")).strip().lower()
    motivo = str(payload.get("motivo", "") or "").strip()[:500]
    if not PERM_ID_RE.match(pid):
        return 400, "pedido inválido"
    if decisao not in ("allow", "deny"):
        return 400, "decisão inválida"
    if por not in PESSOAS:
        return 400, "diga quem você é (glauco ou feda)"
    base = esteira_dir()
    if base is None or not (base / "permissoes" / f"{pid}.json").is_file():
        return 404, "esse pedido já foi resolvido ou expirou"
    if not RESP_DIR.is_dir():
        return 503, "a pasta de respostas ainda não existe no servidor"
    item = {"id": pid, "decisao": decisao, "por": por, "motivo": motivo, "em": time.time()}
    tmp = RESP_DIR / f".{pid}.tmp"
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, RESP_DIR / f"{pid}.json")
    return 200, "aprovado" if decisao == "allow" else "negado"


SETORES = ("manager", "triagem", "front", "review", "qa")
_custos_cache = {"mtime": None, "rows": []}


def read_custos():
    base = esteira_dir()
    if base is None:
        return []
    f = base / "custos.jsonl"
    try:
        mtime = f.stat().st_mtime
    except OSError:
        return []
    if _custos_cache["mtime"] != mtime:
        rows = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and isinstance(r.get("custo_usd"), (int, float)) and r.get("em"):
                rows.append(r)
        _custos_cache.update(mtime=mtime, rows=rows)
    return _custos_cache["rows"]


def custos_por_setor(rows, since):
    out = {}
    for r in rows:
        if r["em"] >= since:
            k = r.get("setor") or "outros"
            out[k] = out.get(k, 0) + r["custo_usd"]
    return {k: round(v, 4) for k, v in out.items()}


def custos_resumo(dias):
    rows = read_custos()
    now = time.time()
    since = now - dias * 86400 if dias > 0 else 0
    sel = [r for r in rows if r["em"] >= since]
    por_dia, por_modelo, por_card = {}, {}, {}
    for r in sel:
        dia = time.strftime("%Y-%m-%d", time.localtime(r["em"]))
        setor = r.get("setor") or "outros"
        d = por_dia.setdefault(dia, {})
        d[setor] = d.get(setor, 0) + r["custo_usd"]
        m = r.get("modelo") or "?"
        por_modelo[m] = por_modelo.get(m, 0) + r["custo_usd"]
        if r.get("card"):
            c = por_card.setdefault(r["card"], {"card": r["card"], "usd": 0, "setores": {}, "ultimo": 0})
            c["usd"] += r["custo_usd"]
            c["setores"][setor] = c["setores"].get(setor, 0) + r["custo_usd"]
            c["ultimo"] = max(c["ultimo"], r["em"])
    top = sorted(por_card.values(), key=lambda c: -c["usd"])[:10]
    return {
        "dias": dias,
        "desde": min((r["em"] for r in sel), default=None),
        "total": round(sum(r["custo_usd"] for r in sel), 4),
        "execucoes": len({(r.get("card"), r.get("execucao"), r["em"]) for r in sel}),
        "cards": len(por_card),
        "por_setor": custos_por_setor(sel, 0),
        "por_modelo": {k: round(v, 4) for k, v in por_modelo.items()},
        "por_dia": [{"dia": k, "setores": {s: round(v, 4) for s, v in d.items()}} for k, d in sorted(por_dia.items())],
        "top_cards": [{**c, "usd": round(c["usd"], 4), "setores": {s: round(v, 4) for s, v in c["setores"].items()}} for c in top],
    }


def write_json_atomic(path, data):
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def novo_card(payload):
    import base64
    tipo = str(payload.get("tipo", "")).lower()
    resp = str(payload.get("responsavel", "")).lower()
    por = str(payload.get("por", "")).lower()
    texto = str(payload.get("texto", "") or "").strip()[:20000]
    if tipo not in ("bug", "tarefa"):
        return 400, "tipo inválido", None
    if resp not in PESSOAS or por not in PESSOAS:
        return 400, "escolha o responsável e quem é você", None
    if len(texto) < 10:
        return 400, "descreva um pouco mais o pedido", None
    imgs = payload.get("imagens") or []
    if not isinstance(imgs, list) or len(imgs) > MAX_IMGS:
        return 400, f"no máximo {MAX_IMGS} imagens", None
    if not NOVOS_DIR.is_dir():
        return 503, "a pasta de novos cards ainda não existe no servidor", None
    nid = "n" + str(int(time.time() * 1000)) + os.urandom(2).hex()
    d = NOVOS_DIR / nid
    d.mkdir()
    nomes = []
    for i, im in enumerate(imgs):
        if not isinstance(im, dict):
            continue
        nome = re.sub(r"[^A-Za-z0-9._-]", "-", str(im.get("nome") or f"print-{i + 1}.png"))[:80] or f"print-{i + 1}.png"
        if Path(nome).suffix.lower() not in IMG_TYPES:
            nome += ".png"
        if nome in nomes:
            nome = f"{i + 1}-{nome}"
        try:
            data = base64.b64decode(str(im.get("b64", "")).split(",")[-1], validate=True)
        except ValueError:
            return 400, f"imagem {nome} inválida", None
        if len(data) > MAX_IMG_BYTES:
            return 400, f"imagem {nome} passa de 8 MB", None
        (d / nome).write_bytes(data)
        nomes.append(nome)
    write_json_atomic(d / "pedido.json", {"id": nid, "tipo": tipo, "responsavel": resp, "por": por, "texto": texto, "imagens": nomes, "em": time.time()})
    code, msg = enqueue({"acao": "novo_card", "novo": nid, "por": por})
    return code, ("rascunho na fila" if code == 200 else msg), nid


def confirmar_card(payload):
    nid = str(payload.get("novo", ""))
    por = str(payload.get("por", "")).lower()
    if not NOVO_ID_RE.match(nid) or por not in PESSOAS:
        return 400, "pedido inválido"
    d = NOVOS_DIR / nid
    if not (d / "pedido.json").is_file():
        return 404, "esse pedido não existe"
    titulo = str(payload.get("titulo", "") or "").strip()[:250]
    descricao = str(payload.get("descricao", "") or "").strip()[:30000]
    tipo = str(payload.get("tipo", "")).lower()
    resp = str(payload.get("responsavel", "")).lower()
    if len(titulo) < 5 or not descricao or tipo not in ("bug", "tarefa") or resp not in PESSOAS:
        return 400, "título, descrição, tipo e responsável são obrigatórios"
    write_json_atomic(d / "final.json", {"titulo": titulo, "descricao": descricao, "tipo": tipo, "responsavel": resp, "por": por, "em": time.time()})
    return enqueue({"acao": "confirmar_card", "novo": nid, "por": por})


def descartar_card(payload):
    nid = str(payload.get("novo", ""))
    if not NOVO_ID_RE.match(nid) or not (NOVOS_DIR / nid / "pedido.json").is_file():
        return 400, "pedido inválido"
    (NOVOS_DIR / nid / "descartado").write_text(str(payload.get("por", "")), encoding="utf-8")
    return 200, "descartado"


def collect_novos():
    base = esteira_dir()
    if base is None or not (base / "novos").is_dir():
        return []
    out = []
    for d in (base / "novos").iterdir():
        if not d.is_dir() or not NOVO_ID_RE.match(d.name) or (d / "descartado").exists():
            continue
        ped = read_json(d / "pedido.json", None)
        if not isinstance(ped, dict):
            continue
        est = read_json(d / "estado.json", {}) or {}
        ras = read_json(d / "rascunho.json", None)
        fin = read_json(d / "final.json", None)
        out.append({"id": d.name, "pedido": ped, "estado": est, "rascunho": ras if isinstance(ras, dict) else None,
                    "final": fin if isinstance(fin, dict) else None})
    out.sort(key=lambda x: -(x["pedido"].get("em") or 0))
    return out[:30]


def collect_sugestoes():
    base = esteira_dir()
    if base is None or not (base / "sugestoes").is_dir():
        return []
    out = []
    for d in (base / "sugestoes").iterdir():
        if not d.is_dir() or not SUG_ID_RE.match(d.name):
            continue
        sg = read_json(d / "sugestao.json", None)
        if not isinstance(sg, dict):
            continue
        est = read_json(d / "estado.json", {}) or {}
        imgs = sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix.lower() in IMG_TYPES)[:12]
        out.append({"id": d.name, "s": sg, "estado": est, "imagens": imgs})
    out.sort(key=lambda x: -(x["s"].get("criado") or 0))
    return out[:60]


def card_dir(key):
    base = esteira_dir()
    if base is None or not KEY_RE.match(key):
        return None
    d = base / "cards" / key
    return d if d.is_dir() else None


def enqueue(payload):
    key = str(payload.get("key", "")).strip()
    if not key.upper().startswith("PR-"):
        key = key.upper()
    acao = str(payload.get("acao", "")).strip()
    por = str(payload.get("por", "")).strip().lower()
    comentario = str(payload.get("comentario", "") or "").strip()[:4000]
    if acao not in ACOES:
        return 400, "ação inválida"
    if por not in PESSOAS:
        return 400, "diga quem você é (glauco ou feda)"
    novo_id = str(payload.get("novo", "")) if acao in ("novo_card", "confirmar_card") else None
    if novo_id is not None and not NOVO_ID_RE.match(novo_id):
        return 400, "pedido de card inválido"
    pr = None
    if acao == "revisar_pr":
        m = PR_URL_RE.match(str(payload.get("url", "")).strip())
        if not m:
            return 400, "link inválido: use https://github.com/leme-tech/<repo>/pull/<número>"
        pr = {"url": f"https://github.com/{m.group(1)}/{m.group(2)}/pull/{m.group(3)}", "repo": m.group(2), "numero": int(m.group(3))}
        key = f"PR-{m.group(2)}-{m.group(3)}"
        if FILA_DIR.is_dir() and any((read_json(f, {}) or {}).get("key") == key for f in FILA_DIR.glob("*.json")):
            return 409, f"{key} já está na fila do review"
        d = card_dir(key)
        if d is not None:
            est = read_json(d / "estado.json", {}) or {}
            if est.get("etapa") not in ("concluido", "erro", "inviavel", None):
                return 409, f"{key} já está na esteira"
    sug = None
    if acao.startswith("sugestao_"):
        sug = str(payload.get("sugestao", ""))
        base_e = esteira_dir()
        if not SUG_ID_RE.match(sug) or base_e is None or not (base_e / "sugestoes" / sug / "sugestao.json").is_file():
            return 404, "essa sugestão não existe mais"
        if acao == "sugestao_aprovar":
            tit = str(payload.get("titulo", "") or "").strip()
            if len(tit) < 5 or str(payload.get("tipo", "")).lower() not in ("bug", "tarefa") or str(payload.get("responsavel", "")).lower() not in PESSOAS:
                return 400, "título, tipo e responsável são obrigatórios"
        if acao == "sugestao_duplicada":
            if not KEY_RE.match(key):
                return 400, "informe o card que já existe (ex.: LM-1234)"
        if acao == "sugestao_ignorar" and not comentario:
            return 400, "diga por que ignorar (ajuda o ouvidor a aprender)"
    if acao not in ("atualizar_pendencias", "faxina", "novo_card", "confirmar_card", "revisar_pr", "sugestao_aprovar", "sugestao_ignorar", "sugestao_descartar") and not KEY_RE.match(key):
        return 400, "card inválido"
    if acao == "devolver" and not comentario:
        return 400, "devolver precisa de um comentário"
    arquivo = None
    if acao == "remover_anexo":
        arquivo = str(payload.get("arquivo", ""))
        d = card_dir(key)
        if not arquivo or "/" in arquivo or arquivo.startswith(".") or d is None or not (d / "anexos" / arquivo).is_file():
            return 404, "esse anexo não existe mais no card"
    if not FILA_DIR.is_dir():
        return 503, "a fila da esteira ainda não existe no servidor"
    now = time.time()
    item = {"key": key or None, "acao": acao, "por": por, "comentario": comentario, "em": now}
    if arquivo:
        item["arquivo"] = arquivo
    if novo_id:
        item["novo"] = novo_id
    if pr:
        item.update(pr)
    if sug:
        item["sugestao"] = sug
        if acao == "sugestao_aprovar":
            item.update({
                "titulo": str(payload.get("titulo", "")).strip()[:250],
                "descricao": str(payload.get("descricao", "") or "").strip()[:30000],
                "tipo": str(payload.get("tipo", "")).lower(),
                "responsavel": str(payload.get("responsavel", "")).lower(),
            })
    if acao == "aprovar" and key.startswith("PR-") and isinstance(payload.get("comentarios"), list):
        coms = []
        for c in payload["comentarios"][:80]:
            if not isinstance(c, dict):
                continue
            texto_c = str(c.get("texto", "") or "").strip()[:6000]
            arq = str(c.get("arquivo", "") or "")[:300]
            try:
                linha = int(c.get("linha"))
            except (TypeError, ValueError):
                linha = None
            if texto_c and arq and linha and linha > 0 and ".." not in arq:
                coms.append({"id": str(c.get("id", ""))[:40], "arquivo": arq, "linha": linha, "lado": "LEFT" if c.get("lado") == "LEFT" else "RIGHT", "texto": texto_c})
        item["comentarios"] = coms
        item["resumo"] = str(payload.get("resumo", "") or "").strip()[:10000]
        if not coms and not item["resumo"]:
            return 400, "escolha ao menos um comentário ou escreva um resumo"
    name = f"{int(now * 1000)}-{key or 'geral'}-{acao}.json"
    tmp = FILA_DIR / f".{name}.tmp"
    tmp.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, FILA_DIR / name)
    return 200, "na fila"


def build_state():
    now = time.time()
    agents = {}
    sessions = []
    running = []
    brain = None
    feed = []
    requests = []
    users = sorted(p for p in DATA_ROOT.iterdir() if p.is_dir()) if DATA_ROOT.is_dir() else []
    with STORE.lock:
        for home in users:
            workspace = home / "workspace"
            for name, a in collect_agents(workspace).items():
                agents.setdefault(name, a)
            s, r = collect_sessions(home.name, home / "claude", now)
            sessions += s
            running += r
            if brain is None and workspace.is_dir():
                brain = collect_brain(workspace)
                feed = collect_feed(workspace)
                requests = collect_requests(workspace)
    for r in running:
        if r["type"] not in agents:
            agents[r["type"]] = {"name": r["type"], "description": "Agente avulso, sem ficha no workspace", "origin": "avulso", "room": "corredor"}
    desks = []
    for name, a in agents.items():
        jobs = [r for r in running if r["type"] == name]
        desks.append({**a, "status": "working" if jobs else "idle", "jobs": jobs})
    desks.sort(key=lambda d: (d["origin"] == "avulso", d["origin"] != "workspace", d["name"]))
    return {
        "now": now,
        "users": [u.name for u in users],
        "sessions": sessions,
        "desks": desks,
        "brain": brain or {"memory_count": 0, "memories": [], "notes_count": 0, "inbox_count": 0, "notes": []},
        "feed": feed,
        "requests": requests,
        "esteira": collect_pipeline(),
        "novos": collect_novos(),
        "sugestoes": collect_sugestoes(),
        "permissoes": collect_permissions(now),
        "custos_7d": custos_por_setor(read_custos(), now - 7 * 86400),
    }


JIRA_FEITO = {"testando", "aguardando release", "aguardando o release", "em release", "done", "concluido", "concluído"}


def resumo_compacto():
    import unicodedata
    norm = lambda t: unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()
    feito = {norm(x) for x in JIRA_FEITO}
    st = build_state()
    now = st["now"]
    est = st["esteira"]
    cards = est["cards"]
    pessoa = lambda n: "feda" if re.search(r"fernanda|feda", n or "", re.I) else ("glauco" if re.search(r"glauco", n or "", re.I) else (n or "?"))
    def c_curto(c):
        return {k: v for k, v in {
            "card": c.get("key"), "titulo": c.get("summary"), "responsavel": pessoa(c.get("assignee")),
            "etapa": c.get("etapa"), "status": c.get("status"), "resumo": c.get("resumo"),
            "voltas_qa": c.get("voltas_qa") or None, "voltas_review": c.get("voltas_review") or None,
            "preview_url": c.get("preview_url"), "pr_url": c.get("pr_url"), "merged_em": c.get("merged_em"),
            "custo_usd": c.get("custo_usd"), "atualizado_ha_min": int((now - (c.get("atualizado") or now)) / 60),
        }.items() if v not in (None, "", [])}
    ativos = [c for c in cards if c.get("etapa") != "concluido"]
    pend = [i for i in est["pendencias"]["items"] if norm(i.get("status")) not in feito]
    na_esteira = {c.get("key") for c in cards}
    por_pessoa = {}
    for i in pend:
        por_pessoa.setdefault(pessoa(i.get("assignee")), []).append({"card": i.get("key"), "titulo": i.get("summary"), "status_jira": i.get("status"), "na_esteira": i.get("key") in na_esteira})
    concl = sorted([c for c in cards if c.get("etapa") == "concluido"], key=lambda c: -(c.get("atualizado") or 0))[:5]
    usage = est.get("usage") or {}
    def janela(w):
        if not w or (w.get("resets_at") and w["resets_at"] < now):
            return None
        return {"usado_pct": round(w.get("used_percentage") or 0), "reseta_em": time.strftime("%d/%m %H:%M", time.localtime(w["resets_at"])) if w.get("resets_at") else None}
    perms = [p for p in st.get("permissoes", []) if not p.get("respondida")]
    rodando = [c for c in ativos if c.get("status") == "rodando" and c.get("etapa") != "fila"]
    return {
        "escritorio": "Leme",
        "gerado_em": time.strftime("%d/%m/%Y %H:%M", time.localtime(now)),
        "vagas": {"em_uso": len(rodando), "max": (est.get("config") or {}).get("max_ativos")},
        "rodando": [c_curto(c) for c in rodando],
        "na_fila": [c_curto(c) for c in ativos if c.get("etapa") == "fila"],
        "esperando_voces": [c_curto(c) for c in ativos if c.get("status") == "aguardando_humano"],
        "com_erro": [c_curto(c) for c in ativos if c.get("etapa") == "erro" or c.get("status") == "falhou"],
        "permissoes_pendentes": [{"agente": p.get("agente"), "card": p.get("card"), "ferramenta": p.get("ferramenta"), "resumo": p.get("resumo")} for p in perms],
        "pendencias_jira": {"total": len(pend), "por_pessoa": por_pessoa},
        "concluidos_recentes": [c_curto(c) for c in concl],
        "uso_claude": {"sessao_5h": janela(usage.get("five_hour")), "semana": janela(usage.get("seven_day"))},
        "custo_7d_usd_por_setor": st.get("custos_7d") or {},
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/state":
            try:
                body = json.dumps(build_state(), ensure_ascii=False).encode()
                self.send(200, body, "application/json; charset=utf-8")
            except Exception as exc:
                self.send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        if path == "/api/resumo":
            try:
                self.send(200, json.dumps(resumo_compacto(), ensure_ascii=False, indent=1).encode(), "application/json; charset=utf-8")
            except Exception as exc:
                self.send(500, json.dumps({"error": str(exc)}).encode(), "application/json")
            return
        if path == "/api/custos":
            q = urllib.parse.parse_qs(self.path.partition("?")[2])
            try:
                dias = max(0, min(3650, int((q.get("dias") or ["7"])[0])))
            except ValueError:
                dias = 7
            self.send(200, json.dumps(custos_resumo(dias), ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        if path == "/healthz":
            self.send(200, b"ok", "text/plain")
            return
        ms = re.match(r"^/api/sugestao/(s[0-9A-Za-z_-]+)/img/([A-Za-z0-9._-]+)$", path)
        if ms and SUG_ID_RE.match(ms.group(1)) and IMG_NOME_RE.match(ms.group(2)):
            base_e = esteira_dir()
            dd = base_e / "sugestoes" / ms.group(1) if base_e else None
            f = dd / ms.group(2) if dd else None
            if f is not None and f.is_file() and f.suffix.lower() in IMG_TYPES and f.resolve().parent == dd.resolve():
                self.send(200, f.read_bytes(), IMG_TYPES[f.suffix.lower()])
                return
            self.send(404, b"not found", "text/plain")
            return
        mn = re.match(r"^/api/novo/(n[0-9a-z]+)/img/([A-Za-z0-9._-]+)$", path)
        if mn and NOVO_ID_RE.match(mn.group(1)) and IMG_NOME_RE.match(mn.group(2)):
            f = NOVOS_DIR / mn.group(1) / mn.group(2)
            if f.is_file() and f.suffix.lower() in IMG_TYPES and f.resolve().parent == (NOVOS_DIR / mn.group(1)).resolve():
                self.send(200, f.read_bytes(), IMG_TYPES[f.suffix.lower()])
                return
            self.send(404, b"not found", "text/plain")
            return
        m = re.match(r"^/api/card/(" + KEY_PAT + r")/(doc|evidencia|anexo)/([A-Za-z0-9._ ()%-]+)$", path)
        if m:
            d = card_dir(m.group(1))
            if d is None:
                self.send(404, b"not found", "text/plain")
                return
            if m.group(2) == "doc" and m.group(3) in DOCS:
                f = d / DOCS[m.group(3)]
                if f.is_file():
                    self.send(200, f.read_bytes()[:400000], "text/plain; charset=utf-8")
                    return
            if m.group(2) == "anexo":
                name = urllib.parse.unquote(m.group(3))
                f = d / "anexos" / name
                if "/" not in name and not name.startswith(".") and f.is_file() and f.resolve().parent == (d / "anexos").resolve():
                    ctype = {**EVID_TYPES, ".pdf": "application/pdf", ".gif": "image/gif", ".svg": "text/plain; charset=utf-8"}.get(f.suffix.lower(), "application/octet-stream")
                    self.send(200, f.read_bytes()[:30_000_000], ctype)
                    return
            if m.group(2) == "evidencia":
                f = d / "evidencias" / m.group(3)
                if f.suffix.lower() in EVID_TYPES and f.is_file() and f.resolve().parent == (d / "evidencias").resolve():
                    data = f.read_bytes()
                    if EVID_TYPES[f.suffix.lower()] == TXT:
                        data = data[:400000]
                    self.send(200, data, EVID_TYPES[f.suffix.lower()])
                    return
            self.send(404, b"not found", "text/plain")
            return
        if path in ("/", "/index.html"):
            self.send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            return
        self.send(404, b"not found", "text/plain")


    def do_POST(self):
        route = self.path.split("?")[0]
        if route == "/api/novo":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 120 * 1024 * 1024:
                    raise ValueError("pedido grande demais")
                payload = json.loads(self.rfile.read(length) or b"{}")
                code, msg, nid = novo_card(payload if isinstance(payload, dict) else {})
            except (ValueError, OSError) as exc:
                code, msg, nid = 400, f"pedido inválido: {exc}", None
            self.send(code, json.dumps({"ok": code == 200, "msg": msg, "id": nid}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            return
        handler = {"/api/acao": enqueue, "/api/permissao": answer_permission, "/api/novo/confirmar": confirmar_card, "/api/novo/descartar": descartar_card}.get(route)
        if handler is None:
            self.send(404, b"not found", "text/plain")
            return
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 80000)
            payload = json.loads(self.rfile.read(length) or b"{}")
            code, msg = handler(payload if isinstance(payload, dict) else {})
        except (ValueError, OSError) as exc:
            code, msg = 400, f"pedido inválido: {exc}"
        self.send(code, json.dumps({"ok": code == 200, "msg": msg}, ensure_ascii=False).encode(), "application/json; charset=utf-8")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
