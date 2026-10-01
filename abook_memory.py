"""abook_memory — память профиля консультанта: журнал → факты → выборка под вопрос, с бюджетом токенов.

Почему так (коротко, по слоям — docs/ПОИСК_И_ЧАТ.md, «Память»):
  1. Журнал событий `mem_events` (append-only): реплики, реакции 👍/👎/«читал», оценки, жалобы, анкета. В промпт
     не попадает никогда — это сырьё. Инкогнито не пишет ничего.
  2. Факты `consultant_memory` (+ confidence, half_life, hits, last_used, vec): «консолидация» — дешёвый вызов
     (Haiku) раз в CONSOLIDATE_EVERY событий сводит журнал в факты: добавить / уточнить / слить дубли / удалить
     опровергнутое. Факты «от вас» (source=user) не трогаются и не стареют.
  3. Забывание: вес факта = confidence · 0.5^(возраст/период полураспада); вкус — год, обстоятельства («сейчас
     хочу короткое») — 2 недели; использование в ответе освежает факт.
  4. Выборка под вопрос: ядро (самые весомые) + релевантные сообщению (косинус по векторам e5 из abook_vec;
     без демона — пересечение основ слов) с MMR (λ = 0.7), чтобы не брать пять почти одинаковых фактов; всё —
     в пределах бюджета символов.
  5. Рабочая память разговора: последние KEEP_TURNS реплик дословно + свёрнутое резюме более ранних (Haiku,
     пересчитывается, когда хвост вырос на SUMMARY_STEP реплик), хранится в chat_sessions.summary.
  6. Бюджет промпта: у каждого раздела потолок; стабильная часть идёт первой (её кэширует Claude), изменчивая —
     последней; meta.budget — сколько символов/≈токенов ушло на каждый раздел (видно в «Статистике»).
Только stdlib; векторы — через демон abook_vec, если он есть.
"""
import contextlib
import json
import math
import re
import threading
import time
from datetime import datetime, timezone

import abook_find as F

CONSOLIDATE_EVERY = 8          # событий до сводки
KEEP_TURNS = 6                 # реплик разговора дословно
SUMMARY_STEP = 4               # пересчитать резюме, когда за его пределами накопилось столько реплик
HALF_LIFE = {"taste": 365, "dislike": 365, "context": 14, "not_interested": 730}
MMR_LAMBDA = 0.7
MEM_MODEL = "haiku"
BUDGET = {"rules": 6000, "profile": 9000, "memory": 1600, "known": 2500, "links": 3500, "candidates": 7000,
          "summary": 1200, "history": 3000, "message": 2200}
CHARS_PER_TOKEN = 3.3          # русский текст у Claude: ≈ 3–3.5 символа на токен

_LOCK = threading.Lock()
_BUSY = set()


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _age_days(ts):
    with contextlib.suppress(Exception):
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400)
    return 0.0


# ------------------------------------------------------------------ схема

def migrate(conn):
    if getattr(migrate, "ok", False):
        return
    A = F.A
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("""CREATE TABLE IF NOT EXISTS mem_events(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL,
          kind TEXT NOT NULL, text TEXT, data TEXT, created TEXT, consolidated INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS mem_events_p ON mem_events(profile_id, consolidated, id)")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(consultant_memory)")}
        for c, d in (("confidence", "REAL NOT NULL DEFAULT 0.6"), ("hits", "INTEGER NOT NULL DEFAULT 0"),
                     ("last_used", "TEXT"), ("vec", "TEXT")):
            if c not in cols:
                conn.execute(f"ALTER TABLE consultant_memory ADD COLUMN {c} {d}")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)")}
        for c, d in (("summary", "TEXT"), ("summary_upto", "INTEGER NOT NULL DEFAULT 0")):
            if c not in cols:
                conn.execute(f"ALTER TABLE chat_sessions ADD COLUMN {c} {d}")
    migrate.ok = True


# ------------------------------------------------------------------ 1. журнал

def log_event(conn, pid, kind, text="", data=None, incognito=False):
    """Записать событие профиля (в инкогнито — ничего). Сводка запускается сама, когда накопилось."""
    if incognito or not pid:
        return
    with contextlib.suppress(Exception):
        migrate(conn)
        A = F.A
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute("INSERT INTO mem_events(profile_id, kind, text, data, created) VALUES(?,?,?,?,?)",
                         (pid, kind, str(text or "")[:1500], json.dumps(data, ensure_ascii=False) if data else None, _now()))
        with contextlib.suppress(Exception):
            import abook_sync   # noqa: PLC0415 — личное изменилось: отложенная синхронизация между компьютерами
            abook_sync.schedule()
        n = conn.execute("SELECT count(*) FROM mem_events WHERE profile_id=? AND consolidated=0", (pid,)).fetchone()[0]
        if n >= CONSOLIDATE_EVERY:
            consolidate_async(pid)


# ------------------------------------------------------------------ 2. консолидация

CONS_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["ops"], "properties": {"ops": {
    "type": "array", "maxItems": 12, "items": {"type": "object", "additionalProperties": False,
        "required": ["op", "ids", "fact", "kind", "confidence"],
        "properties": {"op": {"type": "string", "enum": ["add", "update", "merge", "delete", "confirm"]},
                       "ids": {"type": "array", "items": {"type": "integer"}},
                       "fact": {"type": "string"}, "kind": {"type": "string", "enum": ["taste", "dislike", "context"]},
                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}}}}


def consolidate_async(pid):
    with _LOCK:
        if pid in _BUSY:
            return
        _BUSY.add(pid)
    threading.Thread(target=_consolidate_thread, args=(pid,), daemon=True, name=f"abook-mem-{pid}").start()


def _consolidate_thread(pid):
    conn = F.A.db_connect()
    try:
        consolidate(conn, pid)
    except Exception as e:
        F.A.log(f"WARN: abook_memory: сводка памяти: {e}")
    finally:
        conn.close()
        with _LOCK:
            _BUSY.discard(pid)


def consolidate(conn, pid, force=False):
    """Журнал → факты одним дешёвым вызовом. -> {ops, cost_usd}."""
    migrate(conn)
    A = F.A
    ev = conn.execute("SELECT id, kind, text, created FROM mem_events WHERE profile_id=? AND consolidated=0 ORDER BY id LIMIT 60",
                      (pid,)).fetchall()
    if not ev or (len(ev) < CONSOLIDATE_EVERY and not force):
        return {"ops": 0}
    facts = conn.execute("SELECT id, fact, kind, source, confidence FROM consultant_memory WHERE profile_id=? AND "
                         "kind<>'not_interested' ORDER BY id", (pid,)).fetchall()
    fl = "\n".join(f"#{f['id']} [{f['kind']}{', от слушателя — не менять' if f['source'] == 'user' else ''}; "
                   f"уверенность {f['confidence']:.2f}] {f['fact']}" for f in facts) or "- пусто"
    el = "\n".join(f"- {e['created'][:10]} {e['kind']}: {e['text']}" for e in ev)
    prompt = ("Ты ведёшь память о вкусе слушателя аудиокниг. Сведи НОВЫЕ СОБЫТИЯ в ФАКТЫ — коротко (≤ 15 слов), "
              "обобщая, а не пересказывая события; один факт — одна мысль. Операции: add (новый факт), update (уточнить "
              "#id), merge (слить дубли ids в один fact), delete (событие опровергает #id), confirm (событие подтверждает "
              "#id — подними confidence). confidence: 0.4 — догадка по одному событию, 0.7 — повторилось, 0.9 — сказано "
              "прямо. kind: taste (любит), dislike (не любит), context (обстоятельства: где/когда/сколько слушает, сейчас). "
              "Факты «от слушателя» не меняй и не удаляй. Ничего нового — пустой ops.\n\nФАКТЫ:\n" + fl
              + "\n\nНОВЫЕ СОБЫТИЯ:\n" + el + "\n\nОтвет — JSON по схеме.")
    job = F.new_job()
    data, meta, err = F.run_claude(prompt, CONS_SCHEMA, job, MEM_MODEL, timeout=120, budget=0.2)
    if data is None:
        raise RuntimeError(err)
    by_id = {f["id"]: f for f in facts}
    n, now = 0, _now()
    with A._WRITE_LOCK, A._tx(conn):
        for o in data.get("ops") or []:
            ids = [i for i in (o.get("ids") or []) if i in by_id and by_id[i]["source"] != "user"]
            fact = re.sub(r"\s+", " ", str(o.get("fact") or "")).strip()[:300]
            kind = o.get("kind") if o.get("kind") in ("taste", "dislike", "context") else "taste"
            conf = max(0.0, min(1.0, float(o.get("confidence") or 0.6)))
            op = o.get("op")
            if op == "add" and fact:
                conn.execute("INSERT INTO consultant_memory(profile_id, fact, kind, source, confidence, created, updated) "
                             "VALUES(?,?,?,'auto',?,?,?)", (pid, fact, kind, conf, now, now))
            elif op == "update" and ids and fact:
                conn.execute("UPDATE consultant_memory SET fact=?, kind=?, confidence=?, updated=?, vec=NULL WHERE id=?",
                             (fact, kind, conf, now, ids[0]))
            elif op == "confirm" and ids:
                conn.execute("UPDATE consultant_memory SET confidence=min(1, max(confidence, ?) + 0.1), updated=? WHERE id IN "
                             f"({','.join('?' * len(ids))})", (conf, now, *ids))
            elif op == "merge" and len(ids) >= 2 and fact:
                conn.execute("UPDATE consultant_memory SET fact=?, kind=?, confidence=?, updated=?, vec=NULL WHERE id=?",
                             (fact, kind, conf, now, ids[0]))
                conn.execute(f"DELETE FROM consultant_memory WHERE id IN ({','.join('?' * (len(ids) - 1))})", ids[1:])
            elif op == "delete" and ids:
                conn.execute(f"DELETE FROM consultant_memory WHERE id IN ({','.join('?' * len(ids))})", ids)
            else:
                continue
            n += 1
        conn.execute(f"UPDATE mem_events SET consolidated=1 WHERE id IN ({','.join('?' * len(ev))})", [e["id"] for e in ev])
        _prune(conn, pid)
    return {"ops": n, "events": len(ev), "cost_usd": meta.get("cost_usd")}


def _prune(conn, pid, cap=80):
    """Автофактов не больше cap: выпадают самые слабые по весу."""
    rows = conn.execute("SELECT id, kind, confidence, updated, created FROM consultant_memory WHERE profile_id=? AND "
                        "source<>'user' AND kind<>'not_interested'", (pid,)).fetchall()
    if len(rows) <= cap:
        return
    rows = sorted(rows, key=lambda r: weight(r["kind"], r["confidence"], r["updated"] or r["created"], "auto"))
    ids = [r["id"] for r in rows[:len(rows) - cap]]
    conn.execute(f"DELETE FROM consultant_memory WHERE id IN ({','.join('?' * len(ids))})", ids)


def weight(kind, confidence, ts, source):
    if source == "user":
        return 1.0
    hl = HALF_LIFE.get(kind, 365)
    return float(confidence or 0.6) * 0.5 ** (_age_days(ts) / hl)


# ------------------------------------------------------------------ 4. выборка под вопрос

def _stems(s):
    return {w[:6] for w in re.findall(r"[a-zа-яёіїєґ0-9]{3,}", str(s).lower())}


def _cos(a, b):
    num = sum(x * y for x, y in zip(a, b))
    da, db = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return num / (da * db) if da and db else 0.0


def _embed(conn, texts, query=False):
    with contextlib.suppress(Exception):
        import abook_vec as V   # noqa: PLC0415
        r = V.call(conn, "embed", texts=texts, query=query)
        if r and r.get("vecs"):
            return r["vecs"]
    return None


def select_facts(conn, pid, message, budget=None):
    """-> (строки фактов для промпта, ids использованных). Ядро + релевантные + MMR, в пределах бюджета."""
    migrate(conn)
    budget = budget or BUDGET["memory"]
    rows = [dict(r) for r in conn.execute("SELECT id, fact, kind, source, confidence, created, updated, vec FROM "
                                          "consultant_memory WHERE profile_id=? AND kind<>'not_interested'", (pid,))]
    if not rows:
        return [], []
    for r in rows:
        r["w"] = weight(r["kind"], r["confidence"], r["updated"] or r["created"], r["source"])
    # векторы фактов — лениво, кэш в колонке vec
    need = [r for r in rows if not r["vec"]]
    if need:
        vs = _embed(conn, [r["fact"] for r in need])
        if vs:
            A = F.A
            with A._WRITE_LOCK, A._tx(conn):
                for r, v in zip(need, vs):
                    r["vec"] = json.dumps([round(x, 4) for x in v])
                    conn.execute("UPDATE consultant_memory SET vec=? WHERE id=?", (r["vec"], r["id"]))
    qv = _embed(conn, [message], query=True) if message else None
    qs = _stems(message)
    for r in rows:
        v = json.loads(r["vec"]) if r["vec"] else None
        r["_v"] = v
        if qv and v:
            r["rel"] = max(0.0, _cos(qv[0], v))
        else:
            fs = _stems(r["fact"])
            r["rel"] = len(fs & qs) / (len(fs | qs) or 1)
        r["score"] = 0.55 * r["rel"] + 0.45 * r["w"]
    core = sorted(rows, key=lambda r: -r["w"])[:3]
    chosen, used = list(core), sum(len(r["fact"]) + 12 for r in core)
    pool = [r for r in rows if r not in chosen]
    while pool and used < budget:
        def mmr(r):
            sim = max((_cos(r["_v"], c["_v"]) if r["_v"] and c["_v"] else
                       len(_stems(r["fact"]) & _stems(c["fact"])) / (len(_stems(r["fact"]) | _stems(c["fact"])) or 1))
                      for c in chosen) if chosen else 0
            return MMR_LAMBDA * r["score"] - (1 - MMR_LAMBDA) * sim
        best = max(pool, key=mmr)
        pool.remove(best)
        if used + len(best["fact"]) + 12 > budget:
            continue
        chosen.append(best)
        used += len(best["fact"]) + 12
    lab = {"taste": "вкус", "dislike": "не нравится", "context": "обстоятельства"}
    lines = []
    for r in chosen:
        tag = ", от слушателя" if r["source"] == "user" else f", вес {r['w']:.1f}"
        lines.append(f"- #{r['id']} [{lab.get(r['kind'], r['kind'])}{tag}] {r['fact']}")
    return lines, [r["id"] for r in chosen]


def touch(conn, ids):
    """Факт попал в ответ — освежить (hits+1, last_used)."""
    if not ids:
        return
    with contextlib.suppress(Exception):
        A = F.A
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute(f"UPDATE consultant_memory SET hits=hits+1, last_used=? WHERE id IN ({','.join('?' * len(ids))})",
                         (_now(), *ids))


# ------------------------------------------------------------------ 5. рабочая память разговора

SUM_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["summary"],
              "properties": {"summary": {"type": "string"}}}


def session_context(conn, sid, upto_id=None):
    """-> (резюме ранних реплик или '', последние KEEP_TURNS реплик строками). Резюме пересчитывается дёшево и
    только когда за его пределами накопилось SUMMARY_STEP новых реплик."""
    migrate(conn)
    q = "SELECT id, role, text, data FROM chat_messages WHERE session_id=? AND status='done'" + (" AND id<?" if upto_id else "") + " ORDER BY id"
    msgs = conn.execute(q, (sid, upto_id) if upto_id else (sid,)).fetchall()
    recent, older = msgs[-KEEP_TURNS:], msgs[:-KEEP_TURNS]
    s = conn.execute("SELECT summary, summary_upto FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    summary, upto = (s["summary"] or "", s["summary_upto"] or 0) if s else ("", 0)
    fresh = [m for m in older if m["id"] > upto]
    if older and len(fresh) >= SUMMARY_STEP:
        text = "\n".join(_line(m) for m in fresh)
        prompt = ("Сверни разговор слушателя аудиокниг с консультантом в 3–6 строк: что он просил, какие ограничения "
                  "назвал (длина, настроение, язык), какие книги ему предложили и как он на них отреагировал. Только факты.\n\n"
                  + (f"ПРЕЖНЕЕ РЕЗЮМЕ:\n{summary}\n\n" if summary else "") + "НОВЫЕ РЕПЛИКИ:\n" + text)
        with contextlib.suppress(Exception):
            data, meta, err = F.run_claude(prompt, SUM_SCHEMA, F.new_job(), MEM_MODEL, timeout=90, budget=0.1)
            if data and data.get("summary"):
                summary = str(data["summary"]).strip()[:BUDGET["summary"]]
                A = F.A
                with A._WRITE_LOCK, A._tx(conn):
                    conn.execute("UPDATE chat_sessions SET summary=?, summary_upto=? WHERE id=?", (summary, older[-1]["id"], sid))
    return summary, [_line(m) for m in recent]


def _line(m):
    if m["role"] == "user":
        return "СЛУШАТЕЛЬ: " + re.sub(r"\s+", " ", m["text"] or "")[:800]
    d = json.loads(m["data"] or "{}") if m["data"] else {}
    titles = "; ".join(f"{x.get('author') or ''} — «{x.get('title')}»" for x in d.get("recs") or [])
    return "КОНСУЛЬТАНТ: " + re.sub(r"\s+", " ", m["text"] or "")[:600] + (f" [советы: {titles}]" if titles else "")


# ------------------------------------------------------------------ 6. бюджет промпта

def fit(sections):
    """sections: [(имя, текст)] в порядке «стабильное → изменчивое». Каждый раздел — не длиннее BUDGET[имя]
    (режется по строкам с хвоста, кроме message). -> (prompt, meta.budget)."""
    out, meta = [], {}
    for name, text in sections:
        if not text:
            continue
        cap = BUDGET.get(name)
        t = text
        if cap and len(t) > cap:
            lines, acc = t.split("\n"), []
            size = 0
            for ln in lines:
                if size + len(ln) + 1 > cap:
                    acc.append("… (обрезано по бюджету)")
                    break
                acc.append(ln)
                size += len(ln) + 1
            t = "\n".join(acc)
        out.append(t)
        m = meta.setdefault(name, {"chars": 0, "cut": 0})
        m["chars"] += len(t)
        m["cut"] += len(text) - len(t)
    prompt = "\n\n".join(out)
    meta["_total"] = {"chars": len(prompt), "tokens_est": round(len(prompt) / CHARS_PER_TOKEN)}
    return prompt, meta


def stats(conn, pid):
    migrate(conn)
    ev = conn.execute("SELECT count(*), sum(consolidated=0) FROM mem_events WHERE profile_id=?", (pid,)).fetchone()
    facts = conn.execute("SELECT kind, source, count(*) n, avg(confidence) c FROM consultant_memory WHERE profile_id=? "
                         "GROUP BY 1, 2", (pid,)).fetchall()
    return {"events": ev[0] or 0, "pending": ev[1] or 0, "facts": [dict(r) for r in facts],
            "consolidate_every": CONSOLIDATE_EVERY, "budget": BUDGET}
