#!/usr/bin/env python3
"""
classroom_check.py
Coleta novidades do Google Classroom e do Gmail da conta institucional da UFCG
e devolve um JSON para a sessão do Claude processar.

Subcomandos
  fetch   [--out ARQ] [--mail-days N]     novidades não vistas, pendências e turmas
  ack     --from-file ARQ | --ids K [K ...] marca itens como vistos
  status                                   mostra o estado guardado
  courses                                  lista as turmas (teste rápido de acesso)

Credenciais (uma das formas)
  1) variáveis GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REFRESH_TOKEN
  2) arquivo token.json gerado por auth_local.py (caminho em GOOGLE_TOKEN_FILE
     ou ao lado deste script)

O estado (ids já vistos) fica em um arquivo oculto no Drive da própria conta
UFCG (appDataFolder). Por isso o script funciona igual em qualquer máquina.
"""
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

import argparse
import base64
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.appdata",
]
TZ = ZoneInfo("America/Fortaleza")
STATE_NAME = "ufcg-rotina-state.json"
FIRST_RUN_DAYS = 14      # na primeira execução, só itens dos últimos N dias (ou com prazo futuro)
SEEN_TTL_DAYS = 180      # ids vistos há mais de N dias saem do estado
HERE = os.path.dirname(os.path.abspath(__file__))
DONE_STATES = {"TURNED_IN", "RETURNED"}


def log(msg):
    print(msg, file=sys.stderr)


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- credenciais
def load_credentials():
    cid = os.environ.get("GOOGLE_CLIENT_ID")
    sec = os.environ.get("GOOGLE_CLIENT_SECRET")
    rt = os.environ.get("GOOGLE_REFRESH_TOKEN")
    if not (cid and sec and rt):
        path = os.environ.get("GOOGLE_TOKEN_FILE") or os.path.join(HERE, "token.json")
        if not os.path.exists(path):
            sys.exit(
                "Credenciais ausentes. Defina GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e "
                "GOOGLE_REFRESH_TOKEN, ou gere token.json com auth_local.py."
            )
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        cid, sec, rt = data["client_id"], data["client_secret"], data["refresh_token"]
    creds = Credentials(
        None,
        refresh_token=rt,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cid,
        client_secret=sec,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


class Google:
    def __init__(self, creds):
        kw = dict(credentials=creds, cache_discovery=False)
        self.classroom = build("classroom", "v1", **kw)
        self.gmail = build("gmail", "v1", **kw)
        self.drive = build("drive", "v3", **kw)


# ---------------------------------------------------------------- estado (Drive appDataFolder)
def state_file_id(drive):
    res = drive.files().list(
        spaces="appDataFolder", q=f"name='{STATE_NAME}'", fields="files(id,name)"
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def load_state(drive):
    fid = state_file_id(drive)
    if not fid:
        return {"initialized": False, "seen": {}}, None
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, drive.files().get_media(fileId=fid))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    try:
        state = json.loads(buf.getvalue().decode("utf-8") or "{}")
    except json.JSONDecodeError:
        state = {}
    state.setdefault("initialized", False)
    state.setdefault("seen", {})
    return state, fid


def save_state(drive, state, fid):
    cutoff = (now_utc() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    state["seen"] = {k: v for k, v in state["seen"].items() if v >= cutoff}
    state["updated_at"] = now_utc().isoformat()
    payload = json.dumps(state, ensure_ascii=False).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json", resumable=False)
    if fid:
        drive.files().update(fileId=fid, media_body=media).execute()
    else:
        drive.files().create(
            body={"name": STATE_NAME, "parents": ["appDataFolder"]}, media_body=media, fields="id"
        ).execute()


# ---------------------------------------------------------------- helpers Classroom
def list_all(method, key, max_pages=5, **kwargs):
    items, token, pages = [], None, 0
    while True:
        params = dict(kwargs)
        if token:
            params["pageToken"] = token
        res = method(**params).execute()
        items.extend(res.get(key, []))
        token = res.get("nextPageToken")
        pages += 1
        if not token or pages >= max_pages:
            return items


def due_local(cw):
    """Prazo da atividade em America/Fortaleza (ISO 8601) ou None."""
    d = cw.get("dueDate")
    if not d:
        return None
    t = cw.get("dueTime") or {}
    if t:
        dt = datetime(
            d["year"], d["month"], d["day"], t.get("hours", 0), t.get("minutes", 0), tzinfo=timezone.utc
        ).astimezone(TZ)
    else:
        dt = datetime(d["year"], d["month"], d["day"], 23, 59, tzinfo=TZ)
    return dt.isoformat()


def item_key(kind, course_id, obj):
    stamp = obj.get("updateTime") or obj.get("creationTime") or ""
    return f"{kind}:{course_id}:{obj['id']}@{stamp}"


def materials_of(obj):
    out = []
    for m in obj.get("materials", []) or []:
        if "driveFile" in m:
            df = m["driveFile"].get("driveFile", {})
            out.append({"tipo": "drive", "titulo": df.get("title"), "url": df.get("alternateLink")})
        elif "link" in m:
            out.append({"tipo": "link", "titulo": m["link"].get("title"), "url": m["link"].get("url")})
        elif "youtubeVideo" in m:
            yt = m["youtubeVideo"]
            out.append({"tipo": "youtube", "titulo": yt.get("title"), "url": yt.get("alternateLink")})
        elif "form" in m:
            out.append({"tipo": "form", "titulo": m["form"].get("title"), "url": m["form"].get("formUrl")})
    return out


def to_local(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ).isoformat()
    except ValueError:
        return ts


# ---------------------------------------------------------------- helpers Gmail
def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", "replace")


def extract_text(payload):
    def walk(p, want):
        data = p.get("body", {}).get("data")
        if p.get("mimeType") == want and data:
            return _b64(data)
        for part in p.get("parts", []) or []:
            t = walk(part, want)
            if t:
                return t
        return None

    text = walk(payload, "text/plain")
    if text is None:
        html = walk(payload, "text/html")
        if html:
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"&nbsp;", " ", text)
            text = re.sub(r"\s+", " ", text)
    return (text or "").strip()


def gmail_new(g, seen, days):
    query = f"-from:classroom.google.com newer_than:{days}d"
    res = g.gmail.users().messages().list(userId="me", q=query, maxResults=50).execute()
    out = []
    for m in res.get("messages", []) or []:
        key = f"mail:{m['id']}"
        if key in seen:
            continue
        full = g.gmail.users().messages().get(userId="me", id=m["id"], format="full").execute()
        headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
        body = extract_text(full.get("payload", {}))
        out.append(
            {
                "key": key,
                "id": m["id"],
                "de": headers.get("from"),
                "para": headers.get("to"),
                "assunto": headers.get("subject"),
                "data": headers.get("date"),
                "resumo": full.get("snippet"),
                "corpo": body[:4000],
                "url": f"https://mail.google.com/mail/u/0/#inbox/{m['id']}",
            }
        )
    return out


# ---------------------------------------------------------------- comandos
def cmd_fetch(args):
    g = Google(load_credentials())
    state, fid = load_state(g.drive)
    seen = state["seen"]
    first_run = not state["initialized"]
    now = now_utc()
    now_local = now.astimezone(TZ)
    recent_cutoff = (now - timedelta(days=FIRST_RUN_DAYS)).isoformat()
    newly_seen = {}
    turmas, novidades, pendencias, avisos_erro = [], [], [], []

    courses = list_all(g.classroom.courses().list, "courses", courseStates=["ACTIVE"], pageSize=100)
    for c in courses:
        cid, cname = c["id"], c.get("name", "")
        turmas.append({"id": cid, "nome": cname, "secao": c.get("section"), "url": c.get("alternateLink")})

        subs = {}
        try:
            for s in list_all(
                g.classroom.courses().courseWork().studentSubmissions().list,
                "studentSubmissions",
                courseId=cid,
                courseWorkId="-",
                userId="me",
                pageSize=100,
            ):
                subs[s["courseWorkId"]] = s.get("state")
        except HttpError as e:
            avisos_erro.append(f"sem acesso às entregas em '{cname}': {e.status_code if hasattr(e, 'status_code') else e}")

        sources = (
            ("atividade", g.classroom.courses().courseWork().list, "courseWork"),
            ("aviso", g.classroom.courses().announcements().list, "announcements"),
            ("material", g.classroom.courses().courseWorkMaterials().list, "courseWorkMaterial"),
        )
        for kind, lister, key in sources:
            try:
                objs = list_all(lister, key, courseId=cid, orderBy="updateTime desc", pageSize=100)
            except HttpError as e:
                avisos_erro.append(f"falha ao listar {kind}s em '{cname}': {e}")
                continue
            for o in objs:
                k = item_key(kind, cid, o)
                due = due_local(o) if kind == "atividade" else None
                sub_state = subs.get(o["id"]) if kind == "atividade" else None

                if kind == "atividade" and due and sub_state not in DONE_STATES:
                    due_dt = datetime.fromisoformat(due)
                    if due_dt >= now_local - timedelta(days=1):
                        pendencias.append(
                            {
                                "turma": cname,
                                "titulo": o.get("title"),
                                "prazo": due,
                                "estado_entrega": sub_state or "DESCONHECIDO",
                                "url": o.get("alternateLink"),
                            }
                        )

                if k in seen:
                    continue
                upd = o.get("updateTime") or o.get("creationTime") or ""
                is_recent = upd >= recent_cutoff
                future_due = bool(due) and datetime.fromisoformat(due) >= now_local
                if first_run and not (is_recent or future_due):
                    newly_seen[k] = now.isoformat()
                    continue

                item = {
                    "key": k,
                    "tipo": kind,
                    "turma": cname,
                    "titulo": o.get("title"),
                    "descricao": (o.get("description") or o.get("text") or "")[:4000],
                    "prazo": due,
                    "criado_em": to_local(o.get("creationTime")),
                    "atualizado_em": to_local(o.get("updateTime")),
                    "url": o.get("alternateLink"),
                    "materiais": materials_of(o),
                }
                if kind == "atividade":
                    item["tipo_atividade"] = o.get("workType")
                    item["pontos"] = o.get("maxPoints")
                    item["estado_entrega"] = sub_state
                novidades.append(item)

    emails = []
    try:
        emails = gmail_new(g, seen, max(1, args.mail_days if not first_run else max(args.mail_days, 3)))
    except HttpError as e:
        avisos_erro.append(f"falha ao ler o Gmail: {e}")

    if first_run or newly_seen:
        seen.update(newly_seen)
        state["initialized"] = True
        save_state(g.drive, state, fid)

    def sort_key(i):
        return (i.get("prazo") or "9999", i.get("atualizado_em") or "")

    novidades.sort(key=sort_key)
    pendencias.sort(key=lambda p: p["prazo"])

    out = {
        "gerado_em": now_local.isoformat(),
        "fuso": "America/Fortaleza",
        "primeira_execucao": first_run,
        "turmas": turmas,
        "novidades": novidades,
        "emails_novos": emails,
        "pendencias": pendencias,
        "avisos": avisos_erro,
        "contagem": {
            "turmas": len(turmas),
            "novidades": len(novidades),
            "emails_novos": len(emails),
            "pendencias": len(pendencias),
        },
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        log(f"gravado em {args.out}: {out['contagem']}")
    else:
        print(text)


def cmd_ack(args):
    g = Google(load_credentials())
    state, fid = load_state(g.drive)
    keys = list(args.ids or [])
    if args.from_file:
        with open(args.from_file, encoding="utf-8") as f:
            data = json.load(f)
        keys += [i["key"] for i in data.get("novidades", [])]
        keys += [m["key"] for m in data.get("emails_novos", [])]
    stamp = now_utc().isoformat()
    for k in keys:
        state["seen"][k] = stamp
    state["initialized"] = True
    save_state(g.drive, state, fid)
    print(json.dumps({"marcados": len(keys), "total_vistos": len(state["seen"])}))


def cmd_status(args):
    g = Google(load_credentials())
    state, fid = load_state(g.drive)
    print(
        json.dumps(
            {
                "arquivo_estado": fid,
                "inicializado": state["initialized"],
                "vistos": len(state["seen"]),
                "atualizado_em": state.get("updated_at"),
            },
            indent=2,
        )
    )


def cmd_courses(args):
    g = Google(load_credentials())
    profile = g.gmail.users().getProfile(userId="me").execute()
    print("Conta:", profile.get("emailAddress"))
    courses = list_all(g.classroom.courses().list, "courses", courseStates=["ACTIVE"], pageSize=100)
    print(f"Turmas ativas: {len(courses)}")
    for c in courses:
        print(" -", c.get("name"), f"({c.get('section')})" if c.get("section") else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", help="grava o JSON neste arquivo em vez de imprimir")
    f.add_argument("--mail-days", type=int, default=2, help="janela de busca no Gmail, em dias (padrão 2)")
    f.set_defaults(fn=cmd_fetch)
    a = sub.add_parser("ack")
    a.add_argument("--from-file", help="JSON gerado por fetch; marca todas as novidades e e-mails dele")
    a.add_argument("--ids", nargs="*", help="chaves específicas para marcar")
    a.set_defaults(fn=cmd_ack)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("courses").set_defaults(fn=cmd_courses)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
