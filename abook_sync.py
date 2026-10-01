"""abook_sync — профили между компьютерами через приватный GitHub-репозиторий данных.

Каталог интернета общий и приезжает снимком (abook_setup), аудио у каждого компьютера своё. Переносить нужно только
личное — то, по чему консультант советует: профили, анкеты, отзывы (+ история), очередь, свои книги («вне
библиотеки»), память консультанта, реакции 👍/👎/«читал», жалобы на источники и последний профиль вкуса от ИИ.
Всё это — один JSON (profiles.json, сотни КБ) в приватном репозитории `<владелец>/abook-data`, клон в ~/abook/sync.

Слияние без конфликтов git: pull → слить файл с базой (по естественным ключам; при совпадении побеждает более
свежее updated/created; удаления не распространяются — отзыв, удалённый на одном компьютере, не воскреснет только
если удалён на обоих) → записать файл → commit → push (повтор при гонке). Профили сопоставляются по имени.
Запуск: при старте сервера и через SYNC_DELAY секунд после изменений (кнопка «Синхронизировать» — сразу).
Без gh/репозитория — тихо выключено. Инкогнито ничего не пишет и сюда не попадает.
"""
import contextlib
import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

DATA_REPO = os.environ.get("ABOOK_DATA_REPO", "")        # «владелец/abook-data»; пусто — из gh: <login>/abook-data
SYNC_DELAY = 20
_LOCK = threading.Lock()
_STATE = {"last": None, "error": None, "running": False, "pending": False}
_TIMER = None


def _A():
    import abook_find as F   # noqa: PLC0415
    return F.A


def _dir():
    return _A().ABOOK_DIR / "sync"


def _git(*args, cwd=None, timeout=120):
    r = subprocess.run(["git", *args], cwd=str(cwd or _dir()), capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def repo_name():
    if DATA_REPO:
        return DATA_REPO
    if not shutil.which("gh"):
        return None
    with contextlib.suppress(Exception):
        login = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True, timeout=20).stdout.strip()
        return f"{login}/abook-data" if login else None
    return None


def enabled():
    return bool(shutil.which("git") and shutil.which("gh"))


def ensure_repo(create=False):
    d = _dir()
    if (d / ".git").exists():
        return d
    name = repo_name()
    if not name:
        raise RuntimeError("нужен gh (GitHub CLI) с входом: gh auth login")
    exists = subprocess.run(["gh", "repo", "view", name], capture_output=True, text=True, timeout=30).returncode == 0
    if not exists:
        if not create:
            raise RuntimeError(f"репозитория {name} ещё нет — нажмите «Включить синхронизацию»")
        r = subprocess.run(["gh", "repo", "create", name, "--private", "--description",
                            "abook: профили, анкеты, отзывы и память — синхронизация между компьютерами"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError("gh repo create: " + (r.stderr or r.stdout).strip()[:300])
    d.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["gh", "repo", "clone", name, str(d)], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("gh repo clone: " + (r.stderr or r.stdout).strip()[:300])
    return d


# ------------------------------------------------------------------ выгрузка / слияние

def _rows(conn, sql, args=()):
    with contextlib.suppress(Exception):
        return [dict(r) for r in conn.execute(sql, args)]
    return []


def dump(conn):
    """Личные данные всех профилей → dict (ключ профиля — имя)."""
    out = {"version": 1, "updated": time.strftime("%Y-%m-%dT%H:%M:%S"), "profiles": {}}
    for p in _rows(conn, "SELECT * FROM profiles"):
        pid = p["id"]
        cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)")} if conn else set()
        rv = _rows(conn, "SELECT * FROM reviews WHERE profile_id=?", (pid,))
        ids = sorted({r["item_id"] for r in rv} | {q["item_id"] for q in _rows(conn, "SELECT item_id FROM queue WHERE profile_id=?", (pid,))})
        custom = [r for r in _rows(conn, f"SELECT * FROM items WHERE custom=1 AND id IN ({','.join('?' * len(ids))})", ids)] if ids else []
        last_ai = _rows(conn, "SELECT kind, status, started, finished, model, result, meta FROM ai_runs WHERE profile_id=? AND "
                              "status='done' AND kind IN ('initial','refresh') ORDER BY id DESC LIMIT 1", (pid,))
        out["profiles"][p["name"]] = {
            "profile": {k: p[k] for k in ("name", "slug", "is_default", "created", "updated")},
            "questionnaire": (_rows(conn, "SELECT answers, step, status, source, updated, submitted FROM questionnaire WHERE profile_id=?", (pid,)) or [None])[0],
            "reviews": [{k: v for k, v in r.items() if k != "profile_id"} for r in rv],
            "review_history": [{k: v for k, v in r.items() if k not in ("id", "profile_id")}
                               for r in _rows(conn, "SELECT * FROM review_history WHERE profile_id=? ORDER BY id DESC LIMIT 400", (pid,))],
            "queue": _rows(conn, "SELECT item_id, position, added FROM queue WHERE profile_id=?", (pid,)),
            "custom_items": custom,
            "memory": _rows(conn, "SELECT fact, kind, source, author, title, item_id, created, updated FROM consultant_memory WHERE profile_id=?", (pid,)),
            "feedback": _rows(conn, "SELECT author, title, item_id, src_key, verdict, created FROM rec_feedback WHERE profile_id=?", (pid,)),
            "reports": _rows(conn, "SELECT url, src_key, item_id, author, title, reason, note, created FROM source_reports WHERE profile_id=?", (pid,)),
            "ai_profile": last_ai[0] if last_ai else None}
    return out


def _newer(a, b):
    return str(a or "") > str(b or "")


def merge_into_db(conn, data):
    """Слить чужой файл в базу: добавить недостающее, обновить то, что свежее. -> счётчики."""
    A = _A()
    n = {"profiles": 0, "reviews": 0, "memory": 0, "feedback": 0, "queue": 0, "questionnaire": 0}
    with A._WRITE_LOCK, A._tx(conn):
        for name, P in (data.get("profiles") or {}).items():
            row = conn.execute("SELECT id FROM profiles WHERE name=?", (name,)).fetchone()
            if not row:
                pr = P.get("profile") or {}
                slug = pr.get("slug") or name
                while conn.execute("SELECT 1 FROM profiles WHERE slug=?", (slug,)).fetchone():
                    slug += "-2"
                pid = conn.execute("INSERT INTO profiles(name, slug, is_default, created, updated) VALUES(?,?,0,?,?)",
                                   (name, slug, pr.get("created"), pr.get("updated"))).lastrowid
                n["profiles"] += 1
            else:
                pid = row[0]
            for it in P.get("custom_items") or []:
                cols = [c for c in it if c in {r[1] for r in conn.execute("PRAGMA table_info(items)")}]
                conn.execute(f"INSERT OR IGNORE INTO items({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [it[c] for c in cols])
            q = P.get("questionnaire")
            if q:
                cur = conn.execute("SELECT updated FROM questionnaire WHERE profile_id=?", (pid,)).fetchone()
                if not cur or _newer(q.get("updated"), cur[0]):
                    conn.execute("INSERT OR REPLACE INTO questionnaire(profile_id, answers, step, status, source, updated, submitted) "
                                 "VALUES(?,?,?,?,?,?,?)", (pid, q["answers"], q.get("step"), q.get("status"), q.get("source"),
                                                          q.get("updated"), q.get("submitted")))
                    n["questionnaire"] += 1
            rcols = [r[1] for r in conn.execute("PRAGMA table_info(reviews)")]
            for r in P.get("reviews") or []:
                cur = conn.execute("SELECT updated FROM reviews WHERE profile_id=? AND item_id=?", (pid, r["item_id"])).fetchone()
                if conn.execute("SELECT 1 FROM items WHERE id=?", (r["item_id"],)).fetchone() is None:
                    continue                                   # книги нет в этой базе (ещё не синхронизирован манифест)
                if not cur or _newer(r.get("updated"), cur[0]):
                    vals = {**r, "profile_id": pid}
                    cl = [c for c in rcols if c in vals]
                    conn.execute(f"INSERT OR REPLACE INTO reviews({','.join(cl)}) VALUES({','.join('?' * len(cl))})", [vals[c] for c in cl])
                    n["reviews"] += 1
            have_h = {(h[0], h[1]) for h in conn.execute("SELECT item_id, saved_at FROM review_history WHERE profile_id=?", (pid,))}
            for h in P.get("review_history") or []:
                if (h.get("item_id"), h.get("saved_at")) not in have_h:
                    conn.execute("INSERT INTO review_history(item_id, snapshot, saved_at, reason, profile_id) VALUES(?,?,?,?,?)",
                                 (h.get("item_id"), h.get("snapshot"), h.get("saved_at"), h.get("reason"), pid))
            for qi in P.get("queue") or []:
                if conn.execute("SELECT 1 FROM items WHERE id=?", (qi["item_id"],)).fetchone():
                    n["queue"] += conn.execute("INSERT OR IGNORE INTO queue(profile_id, item_id, position, added) VALUES(?,?,?,?)",
                                               (pid, qi["item_id"], qi.get("position"), qi.get("added"))).rowcount
            facts = {f[0].strip().lower() for f in conn.execute("SELECT fact FROM consultant_memory WHERE profile_id=?", (pid,))}
            for m in P.get("memory") or []:
                if (m.get("fact") or "").strip().lower() not in facts:
                    conn.execute("INSERT INTO consultant_memory(profile_id, fact, kind, source, author, title, item_id, created, updated) "
                                 "VALUES(?,?,?,?,?,?,?,?,?)", (pid, m["fact"], m.get("kind") or "taste", m.get("source") or "auto",
                                                              m.get("author") or "", m.get("title") or "", m.get("item_id"),
                                                              m.get("created"), m.get("updated")))
                    n["memory"] += 1
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='rec_feedback'").fetchone():
                fb = {(f[0] or "", f[1] or ""): f[2] for f in conn.execute("SELECT title, item_id, created FROM rec_feedback WHERE profile_id=?", (pid,))}
                for f in P.get("feedback") or []:
                    k = (f.get("title") or "", f.get("item_id") or "")
                    if k not in fb or _newer(f.get("created"), fb[k]):
                        conn.execute("DELETE FROM rec_feedback WHERE profile_id=? AND title=? AND coalesce(item_id,'')=?", (pid, k[0], k[1]))
                        conn.execute("INSERT INTO rec_feedback(profile_id, author, title, item_id, src_key, verdict, created) VALUES(?,?,?,?,?,?,?)",
                                     (pid, f.get("author"), f.get("title"), f.get("item_id"), f.get("src_key"), f.get("verdict"), f.get("created")))
                        n["feedback"] += 1
            if conn.execute("SELECT 1 FROM sqlite_master WHERE name='source_reports'").fetchone():
                have = {(r[0], r[1]) for r in conn.execute("SELECT url, reason FROM source_reports WHERE profile_id=?", (pid,))}
                for r in P.get("reports") or []:
                    if (r.get("url"), r.get("reason")) not in have:
                        conn.execute("INSERT INTO source_reports(profile_id, url, src_key, item_id, author, title, reason, note, created) "
                                     "VALUES(?,?,?,?,?,?,?,?,?)", (pid, r.get("url"), r.get("src_key"), r.get("item_id"), r.get("author"),
                                                                  r.get("title"), r.get("reason"), r.get("note"), r.get("created")))
            ai = P.get("ai_profile")
            if ai and not conn.execute("SELECT 1 FROM ai_runs WHERE profile_id=? AND finished=? AND kind=?", (pid, ai.get("finished"), ai.get("kind"))).fetchone():
                last = conn.execute("SELECT max(finished) FROM ai_runs WHERE profile_id=? AND status='done' AND kind IN ('initial','refresh')", (pid,)).fetchone()[0]
                if _newer(ai.get("finished"), last):
                    conn.execute("INSERT INTO ai_runs(profile_id, kind, status, started, finished, model, result, meta) VALUES(?,?,?,?,?,?,?,?)",
                                 (pid, ai.get("kind"), "done", ai.get("started"), ai.get("finished"), ai.get("model"), ai.get("result"), ai.get("meta")))
    return n


def sync(conn, create=False):
    """pull → слить → выгрузить → push. -> {pulled, pushed, merged}."""
    with _LOCK:
        if _STATE["running"]:
            return {"busy": True}
        _STATE["running"] = True
    try:
        d = ensure_repo(create=create)
        f = d / "profiles.json"
        with contextlib.suppress(RuntimeError):
            _git("pull", "--rebase", "--quiet")
        merged = merge_into_db(conn, json.loads(f.read_text(encoding="utf-8"))) if f.exists() else {}
        cur = dump(conn)
        blob = json.dumps(cur, ensure_ascii=False, indent=1, sort_keys=True)
        old = {}
        with contextlib.suppress(Exception):
            old = json.loads(f.read_text(encoding="utf-8"))
        pushed = False
        if cur.get("profiles") != old.get("profiles"):          # метка времени файла не в счёт
            f.write_text(blob, encoding="utf-8")
            _git("add", "profiles.json")
            _git("-c", "user.name=abook", "-c", "user.email=abook@localhost", "commit", "-q", "-m",
                 f"профили: {time.strftime('%Y-%m-%d %H:%M')} · {os.uname().nodename}")
            for _ in range(3):
                try:
                    _git("push", "-q")
                    pushed = True
                    break
                except RuntimeError:
                    _git("pull", "--rebase", "-X", "theirs", "--quiet")
        _STATE.update(last=time.strftime("%Y-%m-%d %H:%M:%S"), error=None)
        return {"ok": True, "merged": merged, "pushed": pushed, "repo": repo_name()}
    except Exception as e:
        _STATE["error"] = str(e)[:300]
        return {"ok": False, "error": _STATE["error"]}
    finally:
        _STATE["running"] = False


def schedule():
    """Отложенная синхронизация после изменений (склеивает серию правок в одну отправку)."""
    global _TIMER
    if not enabled() or not (_dir() / ".git").exists():
        return
    if _TIMER:
        _TIMER.cancel()

    def run():
        conn = _A().db_connect()
        try:
            sync(conn)
        finally:
            conn.close()
    _TIMER = threading.Timer(SYNC_DELAY, run)
    _TIMER.daemon = True
    _TIMER.start()


def start_background():
    """Синхронизация при старте сервера (если включена) — в фоне, чтобы не задерживать запуск."""
    if not enabled() or not (_dir() / ".git").exists():
        return

    def run():
        conn = _A().db_connect()
        try:
            sync(conn)
        finally:
            conn.close()
    threading.Thread(target=run, daemon=True, name="abook-sync").start()


def status():
    return {"enabled": enabled(), "configured": (_dir() / ".git").exists(), "repo": repo_name() if enabled() else None, **_STATE}
