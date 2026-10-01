#!/usr/bin/env python3
"""Apply the profiles/questionnaire/AI wiring to an abook source file.
usage: wire.py SRC DST   — every replacement must match exactly once (else abort, nothing written)."""
import ast
import sys

R = []


def rep(old, new, count=1):
    R.append((old, new, count))


# ---------------------------------------------------------------- core: profile context + module
rep('''AIDOC_VERSION = 3
''', '''AIDOC_VERSION = 4
DEFAULT_PROFILE_ID = 1   # «Основной»: can be renamed, never deleted; owns БИБЛИОТЕКА_ДЛЯ_ИИ.md
_PROFILE = threading.local()   # active listener profile of the current thread (HTTP request / AI job)
''')

rep('''_WRITE_LOCK = threading.RLock()     # serialises every mutation + output regeneration
OUT_STATUS = {"d_ok": None, "d_time": None, "d_error": None, "home_time": None,
              "cloud_time": None, "aidoc": {}, "warnings": []}
''', '''_WRITE_LOCK = threading.RLock()     # serialises every mutation + output regeneration
OUT_STATUS = {"d_ok": None, "d_time": None, "d_error": None, "home_time": None,
              "cloud_time": None, "aidoc": {}, "aidoc_p": {}, "warnings": []}

try:   # profiles, questionnaire, Claude recommendations (~/.local/bin/abook_ai.py, stdlib only)
    import abook_ai as AI  # noqa: E402
    AI.bind(globals())
except ImportError as _e:   # the downloader keeps working without it
    AI = None
    print(f"WARN: abook_ai не загружен: {_e}", file=sys.stderr)


def _pid():
    return getattr(_PROFILE, "id", None) or DEFAULT_PROFILE_ID


@contextlib.contextmanager
def _profile_ctx(pid):
    old = getattr(_PROFILE, "id", None)
    _PROFILE.id = pid
    try:
        yield
    finally:
        _PROFILE.id = old


def _profile_ids(conn):
    return [r[0] for r in conn.execute("SELECT id FROM profiles ORDER BY id")]


def _resolve_profile(conn, raw):
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PROFILE_ID
    return pid if conn.execute("SELECT 1 FROM profiles WHERE id=?", (pid,)).fetchone() else DEFAULT_PROFILE_ID


def _aidoc_names(conn, pid):
    """(full, lite) file names of a profile's AI document: the default profile keeps the historical
    names, the others get БИБЛИОТЕКА_ДЛЯ_ИИ_<slug>.md / _<slug>_lite.md."""
    if pid == DEFAULT_PROFILE_ID:
        return AIDOC_NAME, AIDOC_LITE_NAME
    r = conn.execute("SELECT slug FROM profiles WHERE id=?", (pid,)).fetchone()
    slug = r[0] if r else f"p{pid}"
    return f"БИБЛИОТЕКА_ДЛЯ_ИИ_{slug}.md", f"БИБЛИОТЕКА_ДЛЯ_ИИ_{slug}_lite.md"
''')

# ---------------------------------------------------------------- schema v2
rep('''        conn.execute("PRAGMA user_version=1")
    # future migrations: if v < 2: ...
''', '''        conn.execute("PRAGMA user_version=1")
    if v < 2:
        _migrate_v2(conn, backup=v >= 1)
    # future migrations: if v < 3: ...


def _migrate_v2(conn, backup):
    """Listener profiles: reviews, history, tags usage and the queue get a profile_id; everything
    that exists goes to profile 1 «Основной». Library items/files stay shared. A copy of the DB is
    made first (db-backups/library-pre-profiles-*.db)."""
    if backup:
        try:
            dbfile = next((r[2] for r in conn.execute("PRAGMA database_list") if r[1] == "main"), "")
            if dbfile:
                bdir = Path(dbfile).parent / "db-backups"
                bdir.mkdir(parents=True, exist_ok=True)
                conn.execute("VACUUM INTO ?", (str(bdir / f"library-pre-profiles-{datetime.now():%Y%m%d-%H%M%S}.db"),))
        except Exception as e:
            raise RuntimeError(f"миграция v2: не удалось сделать копию базы: {e}")
    now = now_iso()
    cols = "item_id,overall," + ",".join(SUB_KEYS) + ",status,stopped_at,started,finished,quote,relisten,text,created,updated"
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:   # another connection won the race
            conn.execute("ROLLBACK")
            return
        for sql in [
            """CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY, name TEXT NOT NULL,
                 slug TEXT NOT NULL UNIQUE, is_default INTEGER NOT NULL DEFAULT 0,
                 created TEXT NOT NULL, updated TEXT NOT NULL)""",
            f"""CREATE TABLE reviews_v2(profile_id INTEGER NOT NULL DEFAULT 1, item_id TEXT NOT NULL,
                 overall INTEGER, {', '.join(k + ' INTEGER' for k in SUB_KEYS)},
                 status TEXT NOT NULL, stopped_at TEXT NOT NULL DEFAULT '', started TEXT NOT NULL DEFAULT '',
                 finished TEXT NOT NULL DEFAULT '', quote TEXT NOT NULL DEFAULT '', relisten INTEGER NOT NULL DEFAULT 0,
                 text TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL,
                 PRIMARY KEY(profile_id, item_id))""",
            f"INSERT INTO reviews_v2(profile_id,{cols}) SELECT 1,{cols} FROM reviews",
            "DROP TABLE reviews",
            "ALTER TABLE reviews_v2 RENAME TO reviews",
            "ALTER TABLE review_history ADD COLUMN profile_id INTEGER NOT NULL DEFAULT 1",
            "DROP INDEX IF EXISTS review_history_item",
            "CREATE INDEX review_history_item ON review_history(profile_id, item_id, id)",
            """CREATE TABLE item_tags_v2(profile_id INTEGER NOT NULL DEFAULT 1, item_id TEXT NOT NULL,
                 tag TEXT NOT NULL, PRIMARY KEY(profile_id, item_id, tag))""",
            "INSERT INTO item_tags_v2(profile_id,item_id,tag) SELECT 1,item_id,tag FROM item_tags ORDER BY rowid",
            "DROP TABLE item_tags",
            "ALTER TABLE item_tags_v2 RENAME TO item_tags",
            """CREATE TABLE queue_v2(profile_id INTEGER NOT NULL DEFAULT 1, item_id TEXT NOT NULL,
                 position REAL NOT NULL, added TEXT NOT NULL, PRIMARY KEY(profile_id, item_id))""",
            "INSERT INTO queue_v2(profile_id,item_id,position,added) SELECT 1,item_id,position,added FROM queue",
            "DROP TABLE queue",
            "ALTER TABLE queue_v2 RENAME TO queue",
            """CREATE TABLE IF NOT EXISTS questionnaire(profile_id INTEGER PRIMARY KEY,
                 answers TEXT NOT NULL DEFAULT '{}', step INTEGER NOT NULL DEFAULT 0,
                 status TEXT NOT NULL DEFAULT 'draft', source TEXT NOT NULL DEFAULT 'user',
                 updated TEXT, submitted TEXT)""",
            """CREATE TABLE IF NOT EXISTS ai_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,
                 profile_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
                 started TEXT NOT NULL, finished TEXT, model TEXT, inputs_hash TEXT, prompt_chars INTEGER,
                 duration_sec REAL, cost_usd REAL, raw TEXT, result TEXT, notes TEXT, meta TEXT, error TEXT)""",
            "CREATE INDEX IF NOT EXISTS ai_runs_profile ON ai_runs(profile_id, id)",
        ]:
            conn.execute(sql)
        conn.execute("INSERT OR IGNORE INTO profiles(id,name,slug,is_default,created,updated) "
                     "VALUES(1,'Основной','osnovnoy',1,?,?)", (now, now))
        conn.execute("PRAGMA user_version=2")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
''')

# ---------------------------------------------------------------- per-profile SQL
rep('''FROM items i LEFT JOIN files f ON f.item_id=i.id LEFT JOIN reviews r ON r.item_id=i.id
LEFT JOIN queue q ON q.item_id=i.id
''', '''FROM items i LEFT JOIN files f ON f.item_id=i.id LEFT JOIN reviews r ON r.item_id=i.id AND r.profile_id=?
LEFT JOIN queue q ON q.item_id=i.id AND q.profile_id=?
''')
rep('''        rows = conn.execute(_ITEM_SELECT + f" WHERE i.id IN ({','.join('?' * len(ids))})", list(ids)).fetchall()''',
    '''        rows = conn.execute(_ITEM_SELECT + f" WHERE i.id IN ({','.join('?' * len(ids))})",
                            [_pid(), _pid()] + list(ids)).fetchall()''')
rep('''    return [_item_dict(r, full) for r in conn.execute(sql, args)]''',
    '''    return [_item_dict(r, full) for r in conn.execute(sql, [_pid(), _pid()] + list(args))]''')
rep('''    for r in conn.execute("SELECT item_id, tag FROM item_tags ORDER BY rowid"):''',
    '''    for r in conn.execute("SELECT item_id, tag FROM item_tags WHERE profile_id=? ORDER BY rowid", (_pid(),)):''')
rep('''    r = conn.execute("SELECT * FROM reviews WHERE item_id=?", (iid,)).fetchone()
    rev = None
    if r:
        tags = [x[0] for x in conn.execute("SELECT tag FROM item_tags WHERE item_id=? ORDER BY rowid", (iid,))]''',
    '''    r = conn.execute("SELECT * FROM reviews WHERE profile_id=? AND item_id=?", (_pid(), iid)).fetchone()
    rev = None
    if r:
        tags = [x[0] for x in conn.execute("SELECT tag FROM item_tags WHERE profile_id=? AND item_id=? ORDER BY rowid",
                                           (_pid(), iid))]''')
rep('''            for h in conn.execute("SELECT * FROM review_history WHERE item_id=? ORDER BY id DESC", (iid,))]''',
    '''            for h in conn.execute("SELECT * FROM review_history WHERE profile_id=? AND item_id=? ORDER BY id DESC",
                                  (_pid(), iid))]''')
rep('''    for r in conn.execute("SELECT * FROM reviews ORDER BY item_id"):''',
    '''    for r in conn.execute("SELECT * FROM reviews WHERE profile_id=? ORDER BY item_id", (_pid(),)):''')
rep('''        for h in conn.execute("SELECT * FROM review_history ORDER BY id DESC"):''',
    '''        for h in conn.execute("SELECT * FROM review_history WHERE profile_id=? ORDER BY id DESC", (_pid(),)):''')
rep('''    return [r[0] for r in conn.execute("SELECT item_id FROM queue ORDER BY position, added")]''',
    '''    return [r[0] for r in conn.execute("SELECT item_id FROM queue WHERE profile_id=? ORDER BY position, added",
                                       (_pid(),))]''')
rep('''    if conn.execute("SELECT 1 FROM queue WHERE item_id=?", (iid,)).fetchone():
        return
    pos = conn.execute("SELECT coalesce(max(position),0)+1 FROM queue").fetchone()[0]
    conn.execute("INSERT INTO queue(item_id,position,added) VALUES(?,?,?)", (iid, pos, now_iso()))''',
    '''    if conn.execute("SELECT 1 FROM queue WHERE profile_id=? AND item_id=?", (_pid(), iid)).fetchone():
        return
    pos = conn.execute("SELECT coalesce(max(position),0)+1 FROM queue WHERE profile_id=?", (_pid(),)).fetchone()[0]
    conn.execute("INSERT INTO queue(profile_id,item_id,position,added) VALUES(?,?,?,?)", (_pid(), iid, pos, now_iso()))''')
rep('''        conn.execute("INSERT INTO review_history(item_id,snapshot,saved_at,reason) VALUES(?,?,?,?)",
                     (iid, json.dumps(_snapshot(cur), ensure_ascii=False), now, reason))
    sc = f["scores"]
    conn.execute(f"""
        INSERT INTO reviews(item_id,overall,{','.join(SUB_KEYS)},status,stopped_at,started,finished,
                            quote,relisten,text,created,updated)
        VALUES(?,?,{','.join('?' * len(SUB_KEYS))},?,?,?,?,?,?,?,?,?)
        ON CONFLICT(item_id) DO UPDATE SET overall=excluded.overall,''',
    '''        conn.execute("INSERT INTO review_history(profile_id,item_id,snapshot,saved_at,reason) VALUES(?,?,?,?,?)",
                     (_pid(), iid, json.dumps(_snapshot(cur), ensure_ascii=False), now, reason))
    sc = f["scores"]
    conn.execute(f"""
        INSERT INTO reviews(profile_id,item_id,overall,{','.join(SUB_KEYS)},status,stopped_at,started,finished,
                            quote,relisten,text,created,updated)
        VALUES(?,?,?,{','.join('?' * len(SUB_KEYS))},?,?,?,?,?,?,?,?,?)
        ON CONFLICT(profile_id,item_id) DO UPDATE SET overall=excluded.overall,''')
rep('''                 [iid, f["overall"]] + [sc.get(k) for k in SUB_KEYS] +''',
    '''                 [_pid(), iid, f["overall"]] + [sc.get(k) for k in SUB_KEYS] +''')
rep('''    conn.execute("DELETE FROM item_tags WHERE item_id=?", (iid,))
    conn.executemany("INSERT OR IGNORE INTO item_tags(item_id,tag) VALUES(?,?)",
                     [(iid, t) for t in _canon_tags(conn, f["tags"])])
    if f["status"] == "want":
        _queue_add(conn, iid)
    else:
        conn.execute("DELETE FROM queue WHERE item_id=?", (iid,))''',
    '''    conn.execute("DELETE FROM item_tags WHERE profile_id=? AND item_id=?", (_pid(), iid))
    conn.executemany("INSERT OR IGNORE INTO item_tags(profile_id,item_id,tag) VALUES(?,?,?)",
                     [(_pid(), iid, t) for t in _canon_tags(conn, f["tags"])])
    if f["status"] == "want":
        _queue_add(conn, iid)
    else:
        conn.execute("DELETE FROM queue WHERE profile_id=? AND item_id=?", (_pid(), iid))''')
rep('''            h = conn.execute("SELECT snapshot FROM review_history WHERE id=? AND item_id=?", (hid, iid)).fetchone()''',
    '''            h = conn.execute("SELECT snapshot FROM review_history WHERE id=? AND item_id=? AND profile_id=?",
                             (hid, iid, _pid())).fetchone()''')
rep('''            conn.execute("INSERT INTO review_history(item_id,snapshot,saved_at,reason) VALUES(?,?,?,'deleted')",
                         (iid, json.dumps(_snapshot(cur), ensure_ascii=False), now_iso()))
            conn.execute("DELETE FROM reviews WHERE item_id=?", (iid,))
            conn.execute("DELETE FROM item_tags WHERE item_id=?", (iid,))''',
    '''            conn.execute("INSERT INTO review_history(profile_id,item_id,snapshot,saved_at,reason) "
                         "VALUES(?,?,?,?,'deleted')",
                         (_pid(), iid, json.dumps(_snapshot(cur), ensure_ascii=False), now_iso()))
            conn.execute("DELETE FROM reviews WHERE profile_id=? AND item_id=?", (_pid(), iid))
            conn.execute("DELETE FROM item_tags WHERE profile_id=? AND item_id=?", (_pid(), iid))''')
rep('''            elif op == "remove":
                conn.execute("DELETE FROM queue WHERE item_id=?", (iid,))''',
    '''            elif op == "remove":
                conn.execute("DELETE FROM queue WHERE profile_id=? AND item_id=?", (_pid(), iid))''')
rep('''                conn.executemany("UPDATE queue SET position=? WHERE item_id=?",
                                 [(i + 1, k) for i, k in enumerate(order)])''',
    '''                conn.executemany("UPDATE queue SET position=? WHERE profile_id=? AND item_id=?",
                                 [(i + 1, _pid(), k) for i, k in enumerate(order)])''')
rep('''    for h in conn.execute("SELECT * FROM review_history WHERE item_id NOT IN (SELECT item_id FROM reviews) ORDER BY id DESC"):''',
    '''    for h in conn.execute("SELECT * FROM review_history WHERE profile_id=? AND item_id NOT IN "
                          "(SELECT item_id FROM reviews WHERE profile_id=?) ORDER BY id DESC", (_pid(), _pid())):''')
rep('''    extra_ids = [r[0] for r in conn.execute(
        "SELECT item_id FROM reviews UNION SELECT item_id FROM queue ORDER BY 1")]
    by_id = {i["id"]: i for i in lib + outside}''',
    '''    extra_ids = [r[0] for r in conn.execute(
        "SELECT item_id FROM reviews WHERE profile_id=? UNION SELECT item_id FROM queue WHERE profile_id=? ORDER BY 1",
        (_pid(), _pid()))]
    if _pid() != DEFAULT_PROFILE_ID:   # own/«уже прочитано» books of other listeners are not this one's
        own = [i for i in own if i["id"] in set(extra_ids)]
    by_id = {i["id"]: i for i in lib + outside}''')
rep('''        (SELECT count(*) FROM files WHERE status='done'), (SELECT count(*) FROM reviews),
        (SELECT count(*) FROM queue), (SELECT coalesce(sum(hours),0) FROM items WHERE in_library=1),
        (SELECT count(*) FROM items WHERE in_library=0 AND source NOT IN ('read','custom','orphan'))""").fetchone()
    tags = [dict(r) for r in conn.execute(
        "SELECT t.tag, t.is_preset, t.polarity, count(it.item_id) AS n FROM tags t "
        "LEFT JOIN item_tags it ON it.tag=t.tag GROUP BY t.tag ORDER BY t.is_preset DESC, n DESC, t.tag")]''',
    '''        (SELECT count(*) FROM files WHERE status='done'), (SELECT count(*) FROM reviews WHERE profile_id=?1),
        (SELECT count(*) FROM queue WHERE profile_id=?1), (SELECT coalesce(sum(hours),0) FROM items WHERE in_library=1),
        (SELECT count(*) FROM items WHERE in_library=0 AND source NOT IN ('read','custom','orphan'))""",
                     (_pid(),)).fetchone()
    tags = [dict(r) for r in conn.execute(
        "SELECT t.tag, t.is_preset, t.polarity, count(it.item_id) AS n FROM tags t "
        "LEFT JOIN item_tags it ON it.tag=t.tag AND it.profile_id=? GROUP BY t.tag "
        "ORDER BY t.is_preset DESC, n DESC, t.tag", (_pid(),))]''')

# ---------------------------------------------------------------- AI document
rep('''    L = [f"<!-- abook:aidoc v{AIDOC_VERSION} · mode {mode} · generated {datetime.now():%Y-%m-%d %H:%M} · "''',
    '''    prof = conn.execute("SELECT name, slug FROM profiles WHERE id=?", (_pid(),)).fetchone()
    L = [f"<!-- abook:aidoc v{AIDOC_VERSION} · mode {mode} · profile {prof[1] if prof else _pid()} · "
         f"generated {datetime.now():%Y-%m-%d %H:%M} · "''')
rep('''          "- Не предлагай как новое то, что уже в §1 «Уже прочитано» или имеет отзыв (оц в §5).",''',
    '''          "- Не предлагай как новое то, что уже в §1 «Уже прочитано», названо в анкете (§1) или имеет отзыв (оц в §5).",''')
rep('''          "- §1 PROFILE — вкус словами. §2 TASTE — «Сейчас в фокусе», дрейф вкуса, средние (все / свежее — "
          "взвешенные по давности) по разделам/авторам/чтецам, теги, топ/антитоп.",''',
    '''          "- §1 PROFILE — вкус словами: бриф/анкета слушателя и профиль, составленный ИИ. §2 TASTE — «Сейчас в "
          "фокусе», дрейф вкуса, средние (все / свежее — взвешенные по давности) по разделам/авторам/чтецам, "
          "теги, топ/антитоп. §2a — последние рекомендации ИИ (Claude): учитывай, но не повторяй без причины.",''')
rep('''    # §1 PROFILE
    L += ["# §1 PROFILE"]
    for para in [p.strip() for p in re.split(r"\\n+", brief["profile"]) if p.strip()]:
        L.append(f"- {para}")
    if brief["read"]:
        L.append("- Уже прочитано (список): " + "; ".join(
            (f"{r['author']} — «{r['title']}»" if r["author"] else f"«{r['title']}»")
            + (f" ({r['note']})" if r["note"] else "") for r in brief["read"]))
    if brief["narrators"]:
        L.append(f"- Предпочитаемые чтецы: {brief['narrators']}")
    L.append("")
''', '''    # §1 PROFILE (the brief belongs to the default profile; every profile: questionnaire + AI profile)
    L += [f"# §1 PROFILE (профиль «{prof[0] if prof else '?'}»)"]
    if _pid() == DEFAULT_PROFILE_ID:
        for para in [p.strip() for p in re.split(r"\\n+", brief["profile"]) if p.strip()]:
            L.append(f"- {para}")
        if brief["read"]:
            L.append("- Уже прочитано (список): " + "; ".join(
                (f"{r['author']} — «{r['title']}»" if r["author"] else f"«{r['title']}»")
                + (f" ({r['note']})" if r["note"] else "") for r in brief["read"]))
        if brief["narrators"]:
            L.append(f"- Предпочитаемые чтецы: {brief['narrators']}")
    if AI:
        L += AI.aidoc_profile_lines(conn, lite)
    L.append("")
''')
rep('''    # §3 REVIEWS
    L += ["# §3 REVIEWS"]''',
    '''    # §2a AI recommendations
    if AI:
        L += AI.aidoc_ai_lines(conn, lite)

    # §3 REVIEWS
    L += ["# §3 REVIEWS"]''')

# ---------------------------------------------------------------- outputs per profile
rep('''def refresh_outputs(conn, reason=""):
    """Called after EVERY change (review save/delete/restore, queue, sync): regenerate the AI
    documents on D: atomically, write .reviews.json on D:, the home copy, a timestamped snapshot,
    the daily DB snapshot and the cloud copy. D: failures never fail the save."""
    with _WRITE_LOCK:
        warnings = []
        full = build_aidoc(conn, lite=False)
        lite = build_aidoc(conn, lite=True)
        blob = json.dumps(export_reviews_obj(conn), ensure_ascii=False, indent=2) + "\\n"
        OUT_STATUS["aidoc"] = {m: {"chars": len(t), "bytes": len(t.encode("utf-8")),
                                   "tokens": int(len(t) / 3.5)} for m, t in (("full", full), ("lite", lite))}''',
    '''_ALL_PROFILES_REASONS = {"sync", "startup", "rebuild", "get", "aidoc"}


def refresh_outputs(conn, reason=""):
    """Called after EVERY change (review save/delete/restore, queue, sync, questionnaire, AI run):
    regenerate the AI documents on D: atomically — of the current profile, or of every profile after
    a sync/startup/rebuild — write .reviews.json on D: (all profiles), the home copy, a timestamped
    snapshot, the daily DB snapshot and the cloud copy. D: failures never fail the save."""
    with _WRITE_LOCK:
        warnings = []
        cur = _pid()
        pids = _profile_ids(conn) if reason in _ALL_PROFILES_REASONS else [cur]
        if cur not in pids:
            pids.insert(0, cur)
        docs = {}
        for p in pids:
            with _profile_ctx(p):
                docs[p] = (build_aidoc(conn, lite=False), build_aidoc(conn, lite=True))
        full, lite = docs[cur]
        blob = json.dumps(AI.export_all(conn) if AI else export_reviews_obj(conn),
                          ensure_ascii=False, indent=2) + "\\n"
        for p, (f_, l_) in docs.items():
            OUT_STATUS["aidoc_p"][p] = {m: {"chars": len(t), "bytes": len(t.encode("utf-8")),
                                            "tokens": int(len(t) / 3.5)} for m, t in (("full", f_), ("lite", l_))}
        OUT_STATUS["aidoc"] = OUT_STATUS["aidoc_p"][cur]''')
rep('''            _atomic_write_text(OUT_DIR / AIDOC_NAME, full, mkdir=False)
            _atomic_write_text(OUT_DIR / AIDOC_LITE_NAME, lite, mkdir=False)
            _atomic_write_text(OUT_DIR / D_REVIEWS_NAME, blob, mkdir=False)
            _atomic_write_text(OUT_DIR / LIBRARY_CSV_NAME, library_csv(conn), mkdir=False)''',
    '''            for p, (f_, l_) in docs.items():
                fn, ln = _aidoc_names(conn, p)
                _atomic_write_text(OUT_DIR / fn, f_, mkdir=False)
                _atomic_write_text(OUT_DIR / ln, l_, mkdir=False)
            _atomic_write_text(OUT_DIR / D_REVIEWS_NAME, blob, mkdir=False)
            with _profile_ctx(DEFAULT_PROFILE_ID):   # library.csv on D: = the default profile's view
                _atomic_write_text(OUT_DIR / LIBRARY_CSV_NAME, library_csv(conn), mkdir=False)''')
rep('''                _atomic_write_text(cloud / "reviews.json", blob)
                _atomic_write_text(cloud / AIDOC_NAME, full)''',
    '''                _atomic_write_text(cloud / "reviews.json", blob)
                if DEFAULT_PROFILE_ID in docs:
                    _atomic_write_text(cloud / AIDOC_NAME, docs[DEFAULT_PROFILE_ID][0])''')
rep('''    d = {k: v for k, v in OUT_STATUS.items() if k != "warnings"}''',
    '''    d = {k: v for k, v in OUT_STATUS.items() if k not in ("warnings", "aidoc_p")}
    d["aidoc"] = OUT_STATUS["aidoc_p"].get(_pid()) or OUT_STATUS["aidoc"]''')
rep('''def backups_info():''', '''def backups_info(names=None):''')
rep('''            "aidoc": f(OUT_DIR / AIDOC_NAME), "aidoc_lite": f(OUT_DIR / AIDOC_LITE_NAME),''',
    '''            "aidoc": f(OUT_DIR / (names or (AIDOC_NAME, AIDOC_LITE_NAME))[0]),
            "aidoc_lite": f(OUT_DIR / (names or (AIDOC_NAME, AIDOC_LITE_NAME))[1]),''')

# ---------------------------------------------------------------- HTTP
rep('''    def _conn(self):
        conn = db_connect()
        with contextlib.suppress(Exception):''',
    '''    def _conn(self):
        conn = db_connect()
        _PROFILE.id = _resolve_profile(conn, self.headers.get("X-Abook-Profile")
                                       or (parse_qs(urlparse(self.path).query).get("profile") or [""])[0])
        with contextlib.suppress(Exception):''')
rep('''        if u.path in ("/", "/index.html"):
            return self._send(200, REVIEW_HTML, "text/html; charset=utf-8")''',
    '''        if u.path in ("/", "/index.html"):
            return self._send(200, _review_html(), "text/html; charset=utf-8")''')
rep('''            if p == "/api/backups":
                return self._json(backups_info())''',
    '''            if p == "/api/backups":
                return self._json(backups_info(_aidoc_names(conn, _pid())))''')
rep('''                base = "БИБЛИОТЕКА_ДЛЯ_ИИ" + ("_lite" if lite else "")
                return self._attach(text, "text/markdown; charset=utf-8", f"{base}_{day}.md",
                                    f"BIBLIOTEKA_DLYA_II{'_lite' if lite else ''}_{day}.md")''',
    '''                base = _aidoc_names(conn, _pid())[1 if lite else 0][:-3]
                return self._attach(text, "text/markdown; charset=utf-8", f"{base}_{day}.md",
                                    f"BIBLIOTEKA_DLYA_II{base[len('БИБЛИОТЕКА_ДЛЯ_ИИ'):]}_{day}.md")''')
rep('''            if p == "/api/export/library.csv":
                return self._attach(library_csv(conn), "text/csv; charset=utf-8", f"библиотека_{day}.csv", f"library_{day}.csv")
            return self._json({"error": "not found"}, 404)''',
    '''            if p == "/api/export/library.csv":
                return self._attach(library_csv(conn), "text/csv; charset=utf-8", f"библиотека_{day}.csv", f"library_{day}.csv")
            if AI and p.startswith(("/api/profiles", "/api/questionnaire", "/api/ai/")):
                return AI.handle_get(self, conn, p, arg)
            return self._json({"error": "not found"}, 404)''')
rep('''                return self._json({"ok": True, **open_in_windows(dict(rows), what, bool(payload.get("dry")))})
            return self._json({"error": "not found"}, 404)''',
    '''                return self._json({"ok": True, **open_in_windows(dict(rows), what, bool(payload.get("dry")))})
            if AI and p.startswith(("/api/profiles", "/api/questionnaire", "/api/ai/")):
                return AI.handle_post(self, conn, p, payload)
            return self._json({"error": "not found"}, 404)''')
rep('''def cmd_review(args):
    _configure_db_paths(args)
    conn = db_connect()
    res = sync_db(conn, force=True)
    out = refresh_outputs(conn, "startup")''',
    '''_HTML_CACHE = {}


def _review_html():
    if "html" not in _HTML_CACHE:
        html = REVIEW_HTML
        if AI:
            html = AI.inject_html(html)
        else:   # without the module: drop the markers and the AI tab
            for m in ("/*AI:CSS*/", "<!--AI:RAIL-->", "<!--AI:VIEWS-->", "/*AI:JS*/"):
                html = html.replace(m, "")
        _HTML_CACHE["html"] = html
    return _HTML_CACHE["html"]


def cmd_review(args):
    _configure_db_paths(args)
    conn = db_connect()
    res = sync_db(conn, force=True)
    if AI:
        AI.startup(conn)
        _review_html()   # fail at startup, not on the first page load
    out = refresh_outputs(conn, "startup")''')

# ---------------------------------------------------------------- SPA (markers + small edits)
rep('''@media (prefers-reduced-motion:reduce){*{transition:none!important}}
</style></head>''', '''@media (prefers-reduced-motion:reduce){*{transition:none!important}}
/*AI:CSS*/</style></head>''')
rep('''  <nav class="nav" id="nav">''', '''  <!--AI:RAIL-->
  <nav class="nav" id="nav">''')
rep('''    <button data-v="next">Что дальше</button>''', '''    <button data-v="next">Что дальше</button>
    <button data-v="anketa">Анкета <small id="c-anketa"></small></button>''')
rep('''  <div class="list" id="nxList"></div>''', '''  <div id="nxAi"></div>
  <div class="list" id="nxList"></div>''')
rep('''</section>
</main>''', '''</section>
<!--AI:VIEWS-->
</main>''')
rep('''async function api(p,o){const r=await fetch(p,o);''',
    '''let PROFILE=0;try{PROFILE=+localStorage.getItem('abook.profile')||0}catch(e){}
async function api(p,o){o=Object.assign({},o);o.headers=Object.assign({'X-Abook-Profile':String(PROFILE)},o.headers||{});const r=await fetch(p,o);''')
rep('''const r=await fetch('/api/aidoc?mode='+mode);''', '''const r=await fetch('/api/aidoc?mode='+mode+'&profile='+PROFILE);''')
rep('''const r=await fetch('/api/aidoc?mode='+mode+'&inline=1');''', '''const r=await fetch('/api/aidoc?mode='+mode+'&inline=1&profile='+PROFILE);''')
rep('''({reviews:loadReviews,queue:loadQueue,next:loadNext,''',
    '''({reviews:loadReviews,queue:loadQueue,next:()=>{loadNext();loadAiPinned()},anketa:loadAnketa,''')
rep('''(async()=>{paintMode();await refreshMeta();paintMode();const h=location.hash.slice(1);''',
    '''/*AI:JS*/
(async()=>{paintMode();await loadProfiles();await refreshMeta();paintMode();const h=location.hash.slice(1);''')
rep('''else if(['reviews','queue','next','stats','library','check','export'].includes(h))show(h,true);else show('rate',true)})();''',
    '''else if(['reviews','queue','next','anketa','stats','library','check','export'].includes(h))show(h,true);else if(needsOnboarding())show('anketa',true);else show('rate',true)})();''')


def main():
    src, dst = sys.argv[1], sys.argv[2]
    s = open(src, encoding="utf-8").read()
    bad = []
    for old, new, cnt in R:
        n = s.count(old)
        if n != cnt:
            bad.append((n, old[:120]))
            continue
        s = s.replace(old, new)
    if bad:
        for n, o in bad:
            print(f"MISMATCH ({n}x): {o!r}", file=sys.stderr)
        sys.exit(1)
    ast.parse(s)
    open(dst, "w", encoding="utf-8").write(s)
    print(f"ok: {len(R)} replacements -> {dst}")


if __name__ == "__main__":
    main()
