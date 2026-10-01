"""abook_vault — зеркало памяти профиля в Obsidian (`abook review`).

Слой «для человека» поверх базы: каждый профиль — папка vault-а, внутри заметки-markdown со связями [[…]], так что
граф Obsidian показывает карту вкуса: профиль → теги «Любите/Избегать» → книги → признаки карты связей.

  <vault>/<профиль>/Профиль.md        — выжимка профиля ИИ, оси вкуса, теги как [[Тег]]
  <vault>/<профиль>/Память.md         — факты консультанта; СВОИ правки сюда → «Импорт» добавит их в память «от вас»
  <vault>/<профиль>/Книги/<…>.md      — отзывы и реакции: оценка, статус, цитаты, признаки как [[Признак]]
  <vault>/<профиль>/Теги/<…>.md, Признаки/<…>.md — узлы графа (пустые заметки-якоря со ссылками назад)
  <vault>/<профиль>/Разговоры/<…>.md  — чаты (кроме инкогнито)

База — источник правды; vault пересобирается целиком (свои файлы помечены `abook: generated` во frontmatter,
чужие заметки в папке не трогаются). Обратно импортируется только Память.md: новые строки «- факт» становятся
фактами памяти с source=user (их консультант не удаляет). Путь — $ABOOK_VAULT или D:\\VideoDownloader\\Аудиотека-Obsidian
(на D:, чтобы не раздувать WSL-диск на C: и чтобы Obsidian в Windows открыл папку напрямую). Только stdlib.
"""
import json
import os
import re
from pathlib import Path

import abook_find as F

VAULT = Path(os.environ.get("ABOOK_VAULT", "/mnt/d/VideoDownloader/Аудиотека-Obsidian"))
MARK = "abook: generated"


def _safe(s, n=90):
    s = re.sub(r'[\\/:*?"<>|#^\[\]]+', " ", str(s or "")).strip()
    return re.sub(r"\s+", " ", s)[:n].strip() or "без названия"


def _write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        old = p.read_text(encoding="utf-8", errors="replace")
        head = old.split("---", 2)[1] if old.startswith("---") and old.count("---") >= 2 else ""
        if MARK not in head:
            return False                       # заметку написал человек — не перетираем
        if old == text:
            return False
    p.write_text(text, encoding="utf-8")
    return True


def _fm(**kw):
    lines = ["---", MARK]
    for k, v in kw.items():
        lines.append(f"{k}: {json.dumps(v, ensure_ascii=False)}")
    return "\n".join(lines + ["---", ""])


def export(conn, pid):
    A = F.A
    import abook_links as L   # noqa: PLC0415
    prof = conn.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    pname = _safe(prof[0] if prof else f"профиль {pid}")
    root = VAULT / pname
    n = {"written": 0, "notes": 0}

    def put(rel, text):
        n["notes"] += 1
        n["written"] += _write(root / rel, text)

    # профиль и теги
    run = None
    if F.AI:
        run = F.AI.latest_run(conn, pid)
    p = ((run or {}).get("result") or {}).get("profile") or {}
    loves = [x if isinstance(x, str) else (x.get("tag") or x.get("label") or x.get("text") or "") for x in p.get("loves") or []]
    avoid = [x if isinstance(x, str) else (x.get("tag") or x.get("label") or x.get("text") or "") for x in p.get("avoid") or []]
    body = [_fm(type="профиль", profile=pname), f"# {pname}", ""]
    if p.get("summary"):
        body += [p["summary"], ""]
    for ax in p.get("taste_axes") or []:
        if isinstance(ax, dict):
            body.append(f"- **{ax.get('axis') or ax.get('name') or ''}**: {ax.get('value') or ax.get('pole') or ''}"
                        + (f" — {ax.get('evidence')}" if ax.get("evidence") else ""))
    if loves:
        body += ["", "## Любите", *[f"- [[Теги/{_safe(t)}|+ {t}]]" for t in loves if t]]
    if avoid:
        body += ["", "## Лучше избегать", *[f"- [[Теги/{_safe(t)}|− {t}]]" for t in avoid if t]]
    if p.get("listening_context"):
        body += ["", "## Как слушаете", str(p["listening_context"])]
    body += ["", "Память консультанта — [[Память]]."]
    put("Профиль.md", "\n".join(body) + "\n")
    for t, sign in [(t, "+") for t in loves if t] + [(t, "−") for t in avoid if t]:
        put(f"Теги/{_safe(t)}.md", _fm(type="тег", sign=sign) + f"# {sign} {t}\n\nИз [[Профиль|профиля]].\n")

    # память
    mem = L.memory_list(conn, pid)
    mtxt = [_fm(type="память", profile=pname), "# Память консультанта", "",
            "Допишите свои факты строками «- …» в конец — «Импорт из Obsidian» добавит их в память «от вас».", ""]
    for kind, lab in (("taste", "Вкус"), ("dislike", "Не нравится"), ("context", "Обстоятельства"), ("not_interested", "Не интересно")):
        rows = [m for m in mem if m["kind"] == kind]
        if rows:
            mtxt += [f"## {lab}", *[f"- {m['fact']}{' ✎' if m['source'] == 'user' else ''}" for m in rows], ""]
    put("Память.md", "\n".join(mtxt) + "\n")

    # книги: отзывы и реакции, признаки карты связей
    feats = {k: v[1] for k, v in L._stored(conn).items()}
    with A._profile_ctx(pid):
        revs = A.all_reviews(conn)
    ids = set(revs)
    fb = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='rec_feedback'").fetchone():
        fb = [dict(r) for r in conn.execute("SELECT * FROM rec_feedback WHERE profile_id=?", (pid,))]
        ids |= {f["item_id"] for f in fb if f.get("item_id")}
    items = {i["id"]: i for i in A.get_items(conn, ids=sorted(ids))} if ids else {}
    seen_feat = set()
    for iid in sorted(ids):
        it = items.get(iid)
        if not it:
            continue
        r = revs.get(iid) or {}
        f = next((x for x in fb if x.get("item_id") == iid), None)
        name = _safe(f"{it['author']} — {it['title']}" if it["author"] else it["title"])
        tx = [_fm(type="книга", id=iid, overall=r.get("overall"), status=r.get("status"), reaction=(f or {}).get("verdict")),
              f"# {it['title']}", f"{it['author']}" if it["author"] else "", ""]
        if r.get("overall") is not None:
            tx.append(f"Оценка: **{r['overall']}/10** · {r.get('status') or ''}")
        if f:
            tx.append({"like": "👍 нравится", "dislike": "👎 не моё", "read": "✓ читал"}.get(f["verdict"], f["verdict"]))
        for k in ("text", "impression", "notes"):
            if r.get(k):
                tx += ["", str(r[k])]
        if r.get("quote"):
            tx += ["", *[f"> {q}" for q in str(r["quote"]).split("\n\n") if q.strip()]]
        fs = feats.get(iid) or {}
        tags = []
        for facet, vals in fs.items():
            if isinstance(vals, list):
                tags += [str(v) for v in vals[:4]]
        if tags:
            tx += ["", "Признаки: " + " · ".join(f"[[Признаки/{_safe(t, 60)}|{t}]]" for t in tags[:16])]
            seen_feat |= set(tags[:16])
        put(f"Книги/{name}.md", "\n".join(tx) + "\n")
    for t in seen_feat:
        put(f"Признаки/{_safe(t, 60)}.md", _fm(type="признак") + f"# {t}\n")

    # разговоры (кроме инкогнито)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)")}
    q = "SELECT id, title, created FROM chat_sessions WHERE profile_id=?" + (" AND incognito=0" if "incognito" in cols else "")
    for s in conn.execute(q, (pid,)).fetchall():
        tx = [_fm(type="разговор", id=s["id"]), f"# {s['title'] or 'Разговор'}", ""]
        for m in conn.execute("SELECT role, text, data FROM chat_messages WHERE session_id=? AND status='done' ORDER BY id", (s["id"],)):
            if m["role"] == "user":
                tx += [f"**Вы:** {m['text']}", ""]
            else:
                tx += [m["text"] or "", ""]
                for rec in (json.loads(m["data"] or "{}").get("recs") or []):
                    tx.append(f"- {rec.get('author') or ''} — «{rec.get('title')}»: {rec.get('why') or ''}")
                tx.append("")
        put(f"Разговоры/{(s['created'] or '')[:10]} {_safe(s['title'], 60)}.md", "\n".join(tx) + "\n")
    return {"ok": True, "path": str(root), "windows_path": _winpath(root), **n}


def import_memory(conn, pid):
    """Новые строки «- факт» из Память.md → факты памяти от вас (дубли и уже известные пропускаются)."""
    import abook_links as L   # noqa: PLC0415
    prof = conn.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    p = VAULT / _safe(prof[0] if prof else f"профиль {pid}") / "Память.md"
    if not p.exists():
        raise ValueError("Сначала выгрузите память в Obsidian")
    known = {re.sub(r"\s+", " ", m["fact"]).strip().lower() for m in L.memory_list(conn, pid)}
    added = 0
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*[-*]\s+(.+?)\s*(✎)?\s*$", line)
        if not m:
            continue
        fact = m.group(1).strip()
        if len(fact) < 4 or fact.lower() in known:
            continue
        L.memory_op(conn, pid, {"op": "add", "fact": fact})
        known.add(fact.lower())
        added += 1
    return {"ok": True, "added": added}


def _winpath(p):
    s = str(p)
    m = re.match(r"^/mnt/([a-z])/(.*)$", s)
    return f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\") if m else s
