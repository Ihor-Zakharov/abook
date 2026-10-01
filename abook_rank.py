"""abook_rank — модель вкуса профиля и ранжирование рекомендаций «Найти» (foryou и кандидаты консультанта).

Вкус — не одно среднее, а несколько граней. Сигналы профиля (`signals`):
  • профиль от ИИ (ai_runs initial/refresh): «любите» — каждый тег отдельная грань (+), «лучше избегать» — штраф (−),
    оси вкуса и «как вы слушаете» — в реранк (длина, ИИ-голос);
  • анкета: понравившиеся книги (+, вес от оценки), не понравившиеся (−), фильмы/сериалы/игры, жанры, интересы,
    свободный текст и бриф (как тексты), «что ещё нужно знать» (extra: avoid_authors — жёсткий фильтр, avoid_topics —
    штраф, darkness/where/hours — в реанк);
  • отзывы с оценкой и свежестью (A.review_weights), «бросил» — минус;
  • память консультанта (вкус +, «не нравится» −, «не интересно» — исключение и лёгкий минус);
  • реакции на советы в чате (rec_feedback: like +, dislike −, read — только «уже знакомо»), действуют сразу.
Книга из анкеты, которая есть в библиотеке/каталоге, берётся вектором записи (с аннотацией), иначе — текстом.

Демон векторов (abook_vec, op «rank») группирует положительные сигналы в 2–6 центроидов (взвешенный k-means по
косинусу), для каждой записи считает z-оценку близости к каждой грани (z — по всему каталогу, так грани сравнимы)
и к каждому отдельному сигналу (kNN), минус близость к «не моё». Дальше — двухэтапный отбор (`rank`):
  recall — топ вкуса по всему каталогу + гибрид по запросу + мосты карты связей + «качественные» (канон) —
  несколько сотен записей; реранк одной формулой W (вкус, запрос, качество, мост, доступность, полнота, язык,
  длительность, тон) → одна строка на произведение, разнообразие по граням.

Качество книги (`quality`): канон Wikidata (число статей Википедии о произведении — одним SPARQL-запросом на
диапазон, без поштучного обхода), рейтинги knigavuhe (лайки/дизлайки, оценка) и Open Library (средняя и число
оценок) — лениво для топа выдачи, вежливо (≈ 1 запрос/с), кэш в qual_ratings; популярность (просмотры/скачивания
записи). Рейтинги сглаживаются байесовски: мало оценок → к средней площадки. Fantlab и LiveLib из этой машины
не открываются (01.10.2026: fantlab — таймаут TCP, livelib — нет ответа).

Признаки карты связей для нескачанных: топ-кандидаты, которые часто попадают в выдачу, лениво получают
book_features (id «w<id>») той же пачкой Sonnet, что и abook_links, не больше одной пачки на запрос, в фоне.

Только stdlib (numpy — в демоне). Переменные: ABOOK_RANK_FEATS=0 — не досчитывать признаки; ABOOK_RANK_NET=0 —
не ходить за рейтингами; ABOOK_RANK_FEAT_GAP — сек между пачками признаков (по умолчанию 600).
"""
import contextlib
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request

import abook_vec as V

UA = "abook-rank/0.1 (personal audiobook library; polite, cached)"
NET = os.environ.get("ABOOK_RANK_NET") != "0" and os.environ.get("ABOOK_FIND_NO_NET") != "1"
FEATS_ON = os.environ.get("ABOOK_RANK_FEATS") != "0"
FEAT_GAP = int(os.environ.get("ABOOK_RANK_FEAT_GAP", "600"))
RATE_TTL_DAYS = 30
SQL = """
CREATE TABLE IF NOT EXISTS rec_feedback(id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL,
  author TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', item_id TEXT, src_key TEXT,
  verdict TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS rec_feedback_p ON rec_feedback(profile_id, id);
CREATE TABLE IF NOT EXISTS qual_canon(qid TEXT PRIMARY KEY, sitelinks INTEGER NOT NULL, ru TEXT NOT NULL DEFAULT '',
  uk TEXT NOT NULL DEFAULT '', en TEXT NOT NULL DEFAULT '', authors TEXT NOT NULL DEFAULT '[]', fetched TEXT);
CREATE TABLE IF NOT EXISTS qual_ratings(kind TEXT NOT NULL, ref TEXT NOT NULL, source TEXT NOT NULL, rating REAL,
  votes INTEGER, pop INTEGER, url TEXT NOT NULL DEFAULT '', fetched TEXT, PRIMARY KEY(kind, ref, source));
CREATE TABLE IF NOT EXISTS rank_hits(kind TEXT NOT NULL, ref TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0, last TEXT,
  PRIMARY KEY(kind, ref));
"""

# Веса реранка. qual/meta/author/knn подобраны простой сеткой по leave-one-out на 6 профилях (docs/NOTES.md,
# «Модель вкуса и ранжирование»): плато MRR при qual 1,5–2,5 — взята середина; остальные — по смыслу.
W = {"taste": 1.0, "knn": 0.3, "neg": 0.5, "query": 1.2, "qual": 0.5, "bridge": 0.3, "access": 0.1,
     "complete": 0.08, "lang": 0.12, "dur": 0.12, "tone": 0.1, "junk": 0.6, "meta": 0.8, "author": 0.25,
     "qgate": 0.5}


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())


def _F():
    import abook_find as F   # noqa: PLC0415
    return F


def _C():
    import abook_catalog as C   # noqa: PLC0415
    return C


@contextlib.contextmanager
def _wtx(conn):
    """Запись одной транзакцией под общим замком сервера (база открыта в autocommit — без BEGIN каждая строка
    была бы своей транзакцией)."""
    lock = getattr(getattr(_F(), "A", None), "_WRITE_LOCK", None) or contextlib.nullcontext()
    with lock:
        if conn.in_transaction:
            yield
            return
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def migrate(conn):
    conn.executescript(SQL)
    conn.commit()


def _ensure(conn):
    if not getattr(_ensure, "done", None) == V._db_path(conn):
        with contextlib.suppress(sqlite3.OperationalError):
            migrate(conn)
            _ensure.done = V._db_path(conn)


# ======================================================================================== реакции на советы

VERDICTS = ("like", "dislike", "read")


def feedback_add(conn, pid, p):
    """POST /api/find/feedback {verdict: like|dislike|read, author, title, item_id?, src_key?}. Повторная реакция на
    ту же книгу заменяет прежнюю. Вкус пересчитывается на следующем запросе (кэш сбрасывается сразу)."""
    _ensure(conn)
    v = str(p.get("verdict") or "")
    if v not in VERDICTS:
        raise ValueError("verdict: like | dislike | read")
    a, t = str(p.get("author") or "").strip()[:200], str(p.get("title") or "").strip()[:300]
    iid, sk = str(p.get("item_id") or "").strip()[:200] or None, str(p.get("src_key") or "").strip()[:300] or None
    if not t and not iid and not sk:
        raise ValueError("нужно title, item_id или src_key")
    F = _F()
    with _wtx(conn):
        for r in conn.execute("SELECT id, author, title, item_id, src_key FROM rec_feedback WHERE profile_id=?", (pid,)).fetchall():
            if (iid and r[3] == iid) or (sk and r[4] == sk) or (t and F.same_book(a, t, r[1], r[2])):
                conn.execute("DELETE FROM rec_feedback WHERE id=?", (r[0],))
        conn.execute("INSERT INTO rec_feedback(profile_id, author, title, item_id, src_key, verdict, created) "
                     "VALUES(?,?,?,?,?,?,?)", (pid, a, t, iid, sk, v, _now()))
    _PROFILE.pop(pid, None)
    return {"ok": True, "verdict": v}


def feedback_list(conn, pid):
    _ensure(conn)
    return [dict(zip(("author", "title", "item_id", "src_key", "verdict", "created"), r)) for r in conn.execute(
        "SELECT author, title, item_id, src_key, verdict, created FROM rec_feedback WHERE profile_id=? ORDER BY id DESC "
        "LIMIT 400", (pid,))]


# ======================================================================================== сигналы профиля

_PROFILE = {}         # pid -> (sig, profile)


def _ai_profile(conn, pid):
    r = conn.execute("SELECT result FROM ai_runs WHERE profile_id=? AND kind IN ('initial','refresh') AND status='done' "
                     "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    with contextlib.suppress(Exception):
        return (json.loads(r[0]) or {}).get("profile") or {}
    return {}


def _hours_pref(q, ai):
    """(мин, макс) часов из анкеты: extra.hours, prefs.length, «как вы слушаете» ИИ. None — без предпочтения."""
    ex = (q.get("extra") or {}).get("hours") or ""
    m = {"до 3": (0.2, 3), "3–10": (3, 10), "10–20": (10, 20), "больше 20": (20, 80)}
    if ex in m:
        return m[ex]
    lens = " ".join((q.get("prefs") or {}).get("length") or [])
    lo, hi = [], []
    for txt, a, b in (("корот", 0.2, 2), ("сред", 2, 10), ("длин", 10, 40), ("любое", 0.2, 80)):
        if txt in lens:
            lo.append(a)
            hi.append(b)
    if lo:
        return min(lo), max(hi)
    s = (ai.get("listening_context") or "") + " " + " ".join(f"{x.get('axis')} {x.get('value')}" for x in ai.get("taste_axes") or [])
    m2 = re.search(r"(\d+)\s*[–-]\s*(\d+)\s*ч", s)
    return (float(m2.group(1)), float(m2.group(2))) if m2 else None


def _darkness(q, ai):
    """−1 (светлое) … +1 (чем мрачнее, тем лучше); 0 — без предпочтения."""
    d = (q.get("extra") or {}).get("darkness") or ((q.get("worldview") or {}).get("dark") or {}).get("v") or ""
    d = d.lower()
    if "светл" in d:
        return -1.0
    if "чем мрачнее" in d:
        return 1.0
    if "мрачное" in d:
        return 0.5
    ax = " ".join(f"{x.get('axis')} {x.get('value')}" for x in ai.get("taste_axes") or []).lower()
    return 0.8 if "мрачн" in ax and ("максим" in ax or "чем мрачнее" in ax) else 0.0


def _entries(lst):
    return [e for e in lst or [] if isinstance(e, dict) and (e.get("title") or e.get("id"))]


def _strip_titles(text, titles):
    for t in titles:
        if t:
            text = re.sub(re.escape(t), " ", text, flags=re.I)
    return text


def signals(conn, pid, answers=None, hide=()):
    """Все сигналы вкуса профиля -> {pos, neg: [{key?, text?, w, label, src}], known, avoid_authors, hours, dark,
    langs, bedtime, ai_voice_bad, sig}. answers/hide — подмена анкеты и скрытые книги (для офлайн-оценки)."""
    _ensure(conn)
    F = _F()
    A, AI = F.A, F.AI
    q = answers if answers is not None else (AI.get_questionnaire(conn, pid)["answers"] if AI else {})
    ai = _ai_profile(conn, pid)
    hide_t = [h for h in hide if h]
    pos, neg = [], []

    def add(lst, w, label, src, key=None, text=None):
        if key or (text and text.strip()):
            lst.append({"key": key, "text": (text or "").strip()[:400], "w": round(float(w), 3), "label": label[:80], "src": src})

    # профиль от ИИ: «любите» — отдельные грани, «лучше избегать» — штраф (сильнейший сигнал, если есть)
    for t in ai.get("loves") or []:
        add(pos, 1.0, str(t), "ИИ: любите", text=_strip_titles(str(t), hide_t))
    for t in ai.get("avoid") or []:
        if not re.search(r"озвуч|\d+\s*\+?\s*ч|час", str(t), re.I):     # голос и длина — в реранке, не в векторе
            add(neg, 0.8, str(t), "ИИ: избегать", text=str(t))
    for x in ai.get("taste_axes") or []:
        add(pos, 0.35, f"{x.get('axis')}: {x.get('value')}", "ИИ: ось", text=_strip_titles(f"{x.get('axis')}: {x.get('value')}", hide_t))
    # анкета: книги (запись библиотеки/каталога — вектором с аннотацией, иначе текстом)
    authors = []                     # (имя, вес): любимый автор целиком +1, автор понравившейся книги +0,5, нелюбимый −
    for k, sign in (("books_liked", 1), ("books_disliked", -1)):
        for e in _entries(q.get(k)):
            rt = e.get("rating")
            w = 0.9 if rt is None else max(0.3, abs((float(rt) - 5) / 5)) * 1.1
            hint = " ".join(e.get("why") or []) + (" " + e["comment"] if e.get("comment") else "")
            if e.get("kind") == "author":            # анкета: «любимый/нелюбимый автор» — title = имя автора
                name = e.get("title") or ""
                if name in hide_t:
                    continue
                authors.append((name, 1.0 * sign))
                add(pos if sign > 0 else neg, w, f"автор: {name}", "анкета: автор", text=f"книги автора {name}. {hint}")
                continue
            lab = f"{e.get('author') or ''} — {e.get('title') or e.get('id')}".strip(" —")
            key = _book_key(conn, e.get("id"), e.get("author") or "", e.get("title") or "")
            add(pos if sign > 0 else neg, w, lab, "анкета", key=key, text=lab + (". " + hint if hint.strip() else ""))
            if e.get("author"):
                authors.append((e["author"], 0.5 if sign > 0 else -0.4))
    for k, lab, w in (("films", "фильм", 0.35), ("series", "сериал", 0.35), ("games", "игра", 0.2)):
        for e in _entries(q.get(k)):
            rt = e.get("rating")
            sign = -1 if (rt is not None and rt <= 4) else 1
            add(pos if sign > 0 else neg, w, f"{lab}: {e.get('title')}", "анкета", text=f"{lab} «{e.get('title')}» {e.get('comment') or ''}")
    p = q.get("prefs") or {}
    for g in (p.get("genres") or []):
        add(pos, 0.3, f"жанр: {g}", "анкета", text=f"жанр: {g}")
    if p.get("genres_text"):
        add(pos, 0.3, p["genres_text"], "анкета", text=p["genres_text"])
    it = q.get("interests") or {}
    if it.get("text"):
        add(pos, 0.12, it["text"], "анкета: интересы", text=it["text"])
    ex = q.get("extra") or {}
    if ex.get("text"):
        add(pos, 0.4, ex["text"], "анкета: ещё", text=_strip_titles(ex["text"], hide_t))
    for t in ex.get("avoid_topics") or []:
        add(neg, 0.8, f"тема: {t}", "анкета: избегать", text=str(t))
    for qa in ex.get("qa") or []:
        if isinstance(qa, dict) and qa.get("a"):
            add(pos, 0.25, f"{qa.get('q')}: {qa.get('a')}", "анкета: вопрос", text=f"{qa.get('q') or ''} {qa.get('a')}")
    if q.get("brief"):          # «Основной»: бриф вместо анкеты — по предложениям, без строки «Уже прочитано»
        b = re.sub(r"Уже прочитано[^\n]*", " ", q["brief"])
        for s in re.split(r"(?<=[.!?;])\s+|\n+", _strip_titles(b, hide_t)):
            if len(s.strip()) >= 25:
                add(pos, 0.45, s.strip()[:60], "бриф", text=s)
    # отзывы: (оценка − средняя) · свежесть; «бросил» — минус
    revs = []
    with contextlib.suppress(Exception), A._profile_ctx(pid):
        revs = [r for r in A._joined_reviews(conn) if r["status"] != "want" and r["overall"] is not None]
        wts, _ = A.review_weights(revs) if revs else ({}, [])
    if revs:
        mean = sum(r["overall"] for r in revs) / len(revs)
        for r in revs:
            if r["item_id"] in hide:
                continue
            d = (r["overall"] - mean) / 5.0 + (0.15 if r["overall"] >= 8 else 0)
            if r["status"] == "dropped":
                d = min(d, -0.4)
            w = d * wts.get(r["item_id"], (1.0, 0))[0] * 1.2
            lab = f"{r['author']} — {r['title']}"
            if w > 0.05:
                add(pos, w, lab, f"отзыв {r['overall']}/10", key=("item", r["item_id"]), text=lab)
            elif w < -0.05:
                add(neg, -w, lab, f"отзыв {r['overall']}/10", key=("item", r["item_id"]), text=lab)
    # память консультанта
    mem = []
    if V._has_table(conn, "consultant_memory"):
        mem = [dict(zip(("fact", "kind", "author", "title", "item_id"), r)) for r in conn.execute(
            "SELECT fact, kind, author, title, item_id FROM consultant_memory WHERE profile_id=?", (pid,))]
    for m in mem:
        if m["kind"] == "taste":
            add(pos, 0.5, m["fact"], "память", text=m["fact"])
        elif m["kind"] == "dislike":
            add(neg, 0.6, m["fact"], "память", text=m["fact"])
        elif m["kind"] == "not_interested" and (m["title"] or m["fact"]):
            add(neg, 0.3, m["title"] or m["fact"], "не интересно", key=_book_key(conn, m["item_id"], m["author"], m["title"]),
                text=f"{m['author']} — {m['title']}" if m["title"] else m["fact"])
    # реакции на советы
    fbs = feedback_list(conn, pid)
    for f in fbs:
        if f["verdict"] == "read":
            continue
        lab = f"{f['author']} — {f['title']}".strip(" —")
        key = _book_key(conn, f["item_id"], f["author"], f["title"], f["src_key"])
        add(pos if f["verdict"] == "like" else neg, 0.8, lab, "реакция 👍" if f["verdict"] == "like" else "реакция 👎", key=key, text=lab)
    # что уже знакомо (не советовать) и жёсткие фильтры
    known = []
    for k in ("books_liked", "books_disliked"):
        for e in _entries(q.get(k)):
            if e.get("kind") == "author":
                continue
            kn = {"id": e.get("id"), "author": e.get("author") or "", "title": e.get("title") or ""}
            m = _SERIES.search(kn["title"])
            if m:                  # «відьмак, всі томи» — знакомы все книги цикла: префикс названия + автор
                kn["series"] = _atoks(kn["title"][:m.start()])[:1]
            known.append(kn)
    for r in revs:
        known.append({"id": r["item_id"], "author": r["author"], "title": r["title"]})
    if AI and answers is None:
        with contextlib.suppress(Exception):
            known += [{"id": k.get("id"), "author": k["author"], "title": k["title"]} for k in AI.known_books(conn, pid)]
    elif pid == getattr(A, "DEFAULT_PROFILE_ID", 1):
        with contextlib.suppress(Exception):
            known += [{"id": r["id"], "author": r["author"], "title": r["title"]} for r in A.load_brief().get("read") or []]
    known += [{"id": f["item_id"], "author": f["author"], "title": f["title"], "src_key": f["src_key"]}
              for f in fbs if f["verdict"] in ("read", "dislike")]
    known += [{"id": m["item_id"], "author": m["author"], "title": m["title"]} for m in mem
              if m["kind"] == "not_interested" and m["title"]]
    known = [k for k in known if not any(k.get("title") and F.same_book("", h, "", k["title"]) for h in hide_t)
             and k.get("id") not in hide]
    langw = None
    if AI and hasattr(AI, "lang_weights") and answers is None:
        with contextlib.suppress(Exception):
            langw = AI.lang_weights(conn, pid)
    if not langw:                   # та же формула, что abook_ai.lang_weights (для подменённой анкеты и без модуля)
        main, en = p.get("lang_main") or "both", p.get("en_level") or "немного"
        langw = {"ru": 15, "uk": 15, "en": {"немного": 3, "охотно": 8, "нет": -10}.get(en, 3)}
        if main in ("ru", "uk"):
            langw["uk" if main == "ru" else "ru"] = 10
    where = " ".join(ex.get("where") or []) + " " + " ".join(p.get("listen") or [])
    avoid_txt = " ".join(ai.get("avoid") or []).lower()
    for r in revs:
        if r["overall"] >= 8 and r["author"]:
            authors.append((r["author"], 0.4))
        elif r["overall"] <= 3 and r["author"]:
            authors.append((r["author"], -0.3))
    return {"pos": pos, "neg": neg, "known": known, "avoid_authors": [a for a in ex.get("avoid_authors") or [] if a],
            "authors": authors,
            "hours": _hours_pref(q, ai), "dark": _darkness(q, ai), "langw": langw,
            "bedtime": "перед сном" in where, "ai_voice_bad": bool(re.search(r"\bии\b|ии-|\bai\b", avoid_txt)),
            "loves": [str(x) for x in ai.get("loves") or []], "avoid": [str(x) for x in ai.get("avoid") or []]}


_BK = {}


def _book_key(conn, iid, author, title, src_key=None):
    """(kind, ref) записи с вектором: id библиотеки → item; src_key → src; иначе произведение каталога по
    скелету названия и автору (abook_catalog._title_key/_author_toks). None — нет такой записи."""
    if iid and conn.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
        return ("item", iid)
    if src_key and V._has_table(conn, "src_items"):
        r = conn.execute("SELECT id, work_id FROM src_items WHERE source_id=?", (src_key,)).fetchone()
        if r:
            return ("work", str(r[1])) if r[1] else ("src", str(r[0]))
    if not title:
        return None
    ck = (V._db_path(conn), author, title)
    if ck in _BK:
        return _BK[ck]
    out = None
    with contextlib.suppress(Exception):
        C = _C()
        tk = C._title_key(title)
        at = C._author_toks(author)
        if tk and V._has_table(conn, "works"):
            best = None
            for wid, wk, wa, nr in conn.execute("SELECT id, wkey, author, n_records FROM works WHERE wkey LIKE ?", ("%|" + tk,)):
                ok = (not at) or (at & C._author_toks(wa)) or (wk.split("|")[0] in at)
                if ok and (best is None or nr > best[1]):
                    best = (wid, nr)
            if best:
                out = ("work", str(best[0]))
        if not out:
            F = _F()
            for r in conn.execute("SELECT id, author, title FROM items WHERE in_library=1 OR custom=1"):
                if F.same_book(author, title, r[1], r[2]):
                    out = ("item", r[0])
                    break
    _BK[ck] = out
    return out


def profile(conn, pid):
    """Сигналы профиля с кэшем по составу (анкета, ai_runs, отзывы, память, реакции)."""
    parts = []
    for sql in ("SELECT updated FROM questionnaire WHERE profile_id=?", "SELECT max(id) FROM ai_runs WHERE profile_id=?",
                "SELECT count(*), max(updated) FROM consultant_memory WHERE profile_id=?",
                "SELECT count(*), max(id) FROM rec_feedback WHERE profile_id=?"):
        with contextlib.suppress(sqlite3.Error):
            parts.append(tuple(conn.execute(sql, (pid,)).fetchone() or ()))
    with contextlib.suppress(Exception):
        F = _F()
        with F.A._profile_ctx(pid):
            parts.append(len(F.A.all_reviews(conn)))
    sig = json.dumps(parts, default=str)
    hit = _PROFILE.get(pid)
    if hit and hit[0] == sig and time.time() - hit[2] < 1800:
        return hit[1]
    pr = signals(conn, pid)
    _PROFILE[pid] = (sig, pr, time.time())
    return pr


# ======================================================================================== качество

def _get(url, timeout=20, accept="application/json"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _sparql(q, timeout=70):
    return json.loads(_get("https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"}),
                           timeout=timeout, accept="application/sparql-results+json"))["results"]["bindings"]


QLEVER = "https://qlever.dev/api/wikidata"
_QL_PFX = ("PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
           "PREFIX wikibase: <http://wikiba.se/ontology#> PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> ")
# литературное произведение, письменное произведение, сборник рассказов, пьеса, роман, рассказ, повесть
_QL_CLASSES = "wd:Q7725634 wd:Q47461344 wd:Q1279564 wd:Q25379 wd:Q8261 wd:Q49084 wd:Q149537"


def fetch_canon_qlever(conn, lo=2, log=print):
    """Канон через QLever (зеркало Wikidata Фрайбургского университета): весь список одним запросом на язык, ≈ 8 с,
    без лимита 1 запрос/мин, который бывает у WDQS. Фильтр по числу статей — локально (сравнение чисел в QLever
    01.10.2026 работало неверно: FILTER(?sl >= 70) не находил «Дюну» с 77). -> сколько произведений."""
    rows = {}
    for lang in ("ru", "uk"):
        q = (_QL_PFX + "SELECT ?w ?sl ?l ?en ?an WHERE { VALUES ?c { " + _QL_CLASSES + " } ?w wdt:P31 ?c . "
             "?w wikibase:sitelinks ?sl . ?w rdfs:label ?l . FILTER(LANG(?l) = \"" + lang + "\") "
             "OPTIONAL { ?w rdfs:label ?en . FILTER(LANG(?en) = \"en\") } "
             "OPTIONAL { ?w wdt:P50 ?a . ?a rdfs:label ?an . FILTER(LANG(?an) = \"" + lang + "\" || LANG(?an) = \"en\") } }")
        txt = _get(QLEVER + "?" + urllib.parse.urlencode({"query": q}), timeout=240, accept="text/tab-separated-values")
        n = 0
        for line in txt.split("\n")[1:]:
            f = line.split("\t")
            if len(f) < 3:
                continue
            m = re.search(r"\d+", f[1])
            sl = int(m.group(0)) if m else 0
            if sl < lo:
                continue
            qid = f[0].strip("<>").rsplit("/", 1)[-1]

            def lit(x):
                m2 = re.match(r'^"(.*)"@[\w-]+$', x.strip())
                return m2.group(1).replace('\\"', '"') if m2 else ""
            r = rows.setdefault(qid, {"sl": sl, "ru": "", "uk": "", "en": "", "a": set()})
            r[lang] = r[lang] or lit(f[2])
            if len(f) > 3 and f[3]:
                r["en"] = r["en"] or lit(f[3])
            if len(f) > 4 and f[4]:
                a = lit(f[4])
                if a:
                    r["a"].add(a)
            n += 1
        log(f"qlever {lang}: {n} строк, произведений {len(rows)}")
    if not rows:
        return 0
    with _wtx(conn):
        conn.execute("DELETE FROM qual_canon")
        conn.executemany("INSERT INTO qual_canon(qid, sitelinks, ru, uk, en, authors, fetched) VALUES(?,?,?,?,?,?,?)",
                         [(q, r["sl"], r["ru"], r["uk"], r["en"], json.dumps(sorted(r["a"]), ensure_ascii=False), _now())
                          for q, r in rows.items()])
    _Q.clear()
    return len(rows)


def refresh_canon(conn, log=print):
    """Канон: QLever, при неудаче — WDQS диапазонами. Затем сопоставление с каталогом (match_canon)."""
    try:
        n = fetch_canon_qlever(conn, log=log)
    except Exception as e:
        log(f"qlever: {e} — пробую WDQS")
        n = 0
    if not n:
        n = fetch_canon(conn, log=log)
    return n, match_canon(conn)


def fetch_canon(conn, lo=3, log=print):
    """Канон Wikidata: литературные произведения (P31 Q7725634) с ярлыком ru или uk и ≥ lo статьями Википедии.
    WDQS — диапазонами по числу статей: таймаут (504) — диапазон делится пополам, 429 (лимит, бывает 1 запрос/мин) —
    ждём Retry-After и повторяем. Каждый диапазон сохраняется сразу. Ярлыки авторов — API wbgetentities (50 за
    запрос, ≈ 1/с; у него свой лимит, мягче WDQS)."""
    import urllib.error   # noqa: PLC0415
    _ensure(conn)
    todo, total, tries = [(lo, 6), (6, 10), (10, 20), (20, 40), (40, 80), (80, 100000)], 0, 0
    while todo:
        a, b = todo.pop(0)
        q = ("SELECT ?w ?sl ?ru ?uk ?en ?a WHERE { ?w wdt:P31 wd:Q7725634; wikibase:sitelinks ?sl. "
             f"FILTER(?sl >= {a} && ?sl < {b}) "
             "OPTIONAL{?w rdfs:label ?ru FILTER(lang(?ru)='ru')} OPTIONAL{?w rdfs:label ?uk FILTER(lang(?uk)='uk')} "
             "FILTER(BOUND(?ru)||BOUND(?uk)) OPTIONAL{?w rdfs:label ?en FILTER(lang(?en)='en')} OPTIONAL{?w wdt:P50 ?a} }")
        try:
            res = _sparql(q)
            tries = 0
        except urllib.error.HTTPError as e:
            if e.code == 429 and tries < 8:
                tries += 1
                wait = int(e.headers.get("Retry-After") or 65)
                log(f"wikidata {a}-{b}: 429, жду {wait} с")
                todo.insert(0, (a, b))
                time.sleep(min(300, wait + 2))
                continue
            res = None
        except Exception:
            res = None
        if res is None:
            if b - a > 1 and b < 100000:
                m = (a + b) // 2
                todo[:0] = [(a, m), (m, b)]
            elif b >= 100000:
                todo[:0] = [(a, a * 2), (a * 2, b)]
            log(f"wikidata {a}-{b}: не вышло — делю диапазон")
            time.sleep(5)
            continue
        rows = {}
        for x in res:
            qid = x["w"]["value"].rsplit("/", 1)[-1]
            r = rows.setdefault(qid, {"sl": int(x["sl"]["value"]), "ru": "", "uk": "", "en": "", "a": set()})
            for k in ("ru", "uk", "en"):
                if k in x:
                    r[k] = x[k]["value"]
            if "a" in x:
                r["a"].add(x["a"]["value"].rsplit("/", 1)[-1])
        with _wtx(conn):
            conn.executemany("INSERT OR REPLACE INTO qual_canon(qid, sitelinks, ru, uk, en, authors, fetched) VALUES(?,?,?,?,?,?,?)",
                             [(q, r["sl"], r["ru"], r["uk"], r["en"], json.dumps(sorted(r["a"])), _now()) for q, r in rows.items()])
        total += len(rows)
        log(f"wikidata {a}-{b}: {len(rows)} произведений, всего {total}")
        time.sleep(2)
    fetch_canon_authors(conn, log)
    _Q.clear()
    return total


def fetch_canon_authors(conn, log=print):
    """В qual_canon.authors сначала лежат QID авторов; здесь они заменяются ярлыками ru/uk/en (wbgetentities)."""
    rows = [(q, json.loads(a or "[]")) for q, a in conn.execute("SELECT qid, authors FROM qual_canon")]
    qids = sorted({a for _, au in rows for a in au if re.fullmatch(r"Q\d+", a)})
    names = {}
    for i in range(0, len(qids), 50):
        url = ("https://www.wikidata.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "wbgetentities", "ids": "|".join(qids[i:i + 50]), "props": "labels", "languages": "ru|uk|en",
             "format": "json"}))
        for attempt in range(3):
            try:
                ents = json.loads(_get(url)).get("entities") or {}
                for q, e in ents.items():
                    names[q] = sorted({v["value"] for v in (e.get("labels") or {}).values()})
                break
            except Exception as e:
                log(f"wbgetentities: {e}")
                time.sleep(10 * (attempt + 1))
        time.sleep(0.7)
        if i % 1000 == 0:
            log(f"авторы: {i}/{len(qids)}")
    with _wtx(conn):
        conn.executemany("UPDATE qual_canon SET authors=? WHERE qid=?", [
            (json.dumps(sorted({n for a in au for n in (names.get(a) or ([] if re.fullmatch(r"Q\d+", a) else [a]))}),
                        ensure_ascii=False), q) for q, au in rows])
    return len(names)


def _akey(name):
    """Ключ автора для «известен ли автор»: фамилия целиком + первая буква имени (скелеты согласных для этого
    слишком грубы: «Аудиокнига36» совпадал с настоящими авторами). «Фамилия, Имя» и «Имя Фамилия» — одинаково."""
    C = _C()
    s = re.sub(r"\([^)]*\)|[\d\[\]{}«»\"]", " ", str(name or ""))
    if "," in s:
        a, b = s.split(",", 1)
        s = b + " " + a
    ws = [C.norm(w) for w in re.split(r"[\s.]+", s) if w]
    ws = [w for w in ws if w and w.isalpha()]
    if len(ws) < 2 or len(ws[-1]) < 3:
        return None
    return ws[-1] + "|" + ws[0][0]


def match_canon(conn):
    """Сопоставить канон с произведениями каталога и книгами библиотеки -> qual_ratings source='wikidata'
    (pop = число статей). Название — скелет abook_catalog._title_key (ru/uk/en); автор — пересечение скелетов;
    без автора — только длинное название и ≥ 10 статей. Автор канона без совпавшего названия — source='author'."""
    _ensure(conn)
    C = _C()
    idx, afame = {}, {}
    for qid, sl, ru, uk, en, au in conn.execute("SELECT qid, sitelinks, ru, uk, en, authors FROM qual_canon"):
        at = set()
        for a in json.loads(au or "[]"):
            at |= C._author_toks(a)
        for t in {ru, uk, en} - {""}:
            tk = C._title_key(t)
            if tk:
                idx.setdefault(tk, []).append((at, sl, qid, len(t.split())))
        for a in json.loads(au or "[]"):
            k = _akey(a)
            if k:
                afame[k] = max(afame.get(k, 0), sl)
    rows = []

    def one(kind, ref, author, titles):
        at = C._author_toks(author)
        best = None
        for t in titles:
            for cat, sl, qid, nw in idx.get(C._title_key(t), ()):
                if (at and cat and at & cat) or (not at and nw >= 2 and sl >= 10):
                    if not best or sl > best[0]:
                        best = (sl, qid)
        if best:
            rows.append((kind, ref, "wikidata", None, None, best[0], f"https://www.wikidata.org/wiki/{best[1]}", _now()))
        elif at:
            fame = afame.get(_akey(author), 0)
            if fame >= 3:
                rows.append((kind, ref, "author", None, None, fame, "", _now()))

    if V._has_table(conn, "works"):
        for wid, a, t, alts in conn.execute("SELECT id, author, title, alt_titles FROM works"):
            with contextlib.suppress(Exception):
                one("work", str(wid), a, [t] + json.loads(alts or "[]")[:4])
    for iid, a, t in conn.execute("SELECT id, author, title FROM items WHERE in_library=1 OR custom=1"):
        one("item", iid, a, [t])
    with _wtx(conn):
        conn.execute("DELETE FROM qual_ratings WHERE source IN ('wikidata','author')")
        conn.executemany("INSERT OR REPLACE INTO qual_ratings(kind, ref, source, rating, votes, pop, url, fetched) "
                         "VALUES(?,?,?,?,?,?,?,?)", rows)
    _Q.clear()
    return {"wikidata": sum(r[2] == "wikidata" for r in rows), "author": sum(r[2] == "author" for r in rows)}


def _kv_rating(author, title):
    """knigavuhe: поиск → страница книги → лайки/дизлайки, оценка (schema.org), просмотры. None — не нашли."""
    C = _C()
    html = _get("https://knigavuhe.org/search/?q=" + urllib.parse.quote(f"{author} {title}".strip()[:120]), accept="text/html")
    tk, at = C._title_key(title), C._author_toks(author)
    for m in re.finditer(r'<div class="bookkitem">(.*?)(?=<div class="bookkitem">|<div class="pn_)', html, re.S):
        blk = m.group(1)
        href = re.search(r'href="(/book/[^"#]+)"', blk)
        name = re.search(r'class="bookkitem_name">\s*(.*?)</a>', blk, re.S)
        auth = " ".join(re.findall(r'href="/author/[^"]+">([^<]+)</a>', blk))
        if not href or not name:
            continue
        nm = re.sub(r"<[^>]+>", "", name.group(1)).strip()
        if C._title_key(nm) != tk or (at and auth and not (at & C._author_toks(auth))):
            continue
        views = re.search(r'-views"></span>\s*<span[^>]*>([\d\s\xa0]+)<', blk)
        time.sleep(1)
        page = _get("https://knigavuhe.org" + href.group(1), accept="text/html")
        lk = re.search(r'id="book_likes_count">(\d+)', page)
        dl = re.search(r'id="book_dislikes_count">(\d+)', page)
        return {"likes": int(lk.group(1)) if lk else 0, "dislikes": int(dl.group(1)) if dl else 0,
                "views": int(re.sub(r"\D", "", views.group(1))) if views else None, "url": "https://knigavuhe.org" + href.group(1)}
    return None


def _ol_rating(title, author):
    """Open Library search.json: средняя оценка и число оценок произведения (английские ярлыки из канона)."""
    q = urllib.parse.urlencode({"title": title, "author": author, "fields": "key,title,author_name,ratings_average,"
                                "ratings_count,want_to_read_count", "limit": 3})
    for d in json.loads(_get("https://openlibrary.org/search.json?" + q)).get("docs") or []:
        if d.get("ratings_count"):
            return {"avg": d["ratings_average"], "n": d["ratings_count"], "url": "https://openlibrary.org" + d["key"]}
    return None


def fetch_ratings(conn, keys, max_n=20, log=lambda *_: None):
    """Рейтинги knigavuhe и Open Library для произведений (kind work|item) — только тех, что ещё не спрашивали
    (или старше RATE_TTL_DAYS). Вежливо: ≈ 1 запрос/с, промах тоже кэшируется. -> сколько спросили."""
    if not NET:
        return 0
    _ensure(conn)
    have = {(k, r, s) for k, r, s in conn.execute(
        "SELECT kind, ref, source FROM qual_ratings WHERE source IN ('knigavuhe','openlibrary') AND fetched > ?",
        (time.strftime("%Y-%m-%d", time.gmtime(time.time() - RATE_TTL_DAYS * 86400)),))}
    n = 0
    for kind, ref in keys:
        if n >= max_n:
            break
        info = _key_info(conn, kind, ref)
        if not info or not info["title"]:
            continue
        rows = []
        if (kind, ref, "knigavuhe") not in have:
            try:
                r = _kv_rating(info["author"], info["title"])
            except Exception as e:
                log(f"knigavuhe {info['title']}: {e}")
                r = "err"
            if r != "err":
                rows.append((kind, ref, "knigavuhe", (r["likes"] / max(1, r["likes"] + r["dislikes"])) if r else None,
                             (r["likes"] + r["dislikes"]) if r else None, r and r["views"], (r or {}).get("url") or "", _now()))
            n += 1
            time.sleep(1)
        en = info.get("en")
        if en and (kind, ref, "openlibrary") not in have:
            with contextlib.suppress(Exception):
                r = _ol_rating(en[0], en[1])
                rows.append((kind, ref, "openlibrary", r and r["avg"], r and r["n"], None, (r or {}).get("url") or "", _now()))
            n += 1
            time.sleep(1)
        if rows:
            with _wtx(conn):
                conn.executemany("INSERT OR REPLACE INTO qual_ratings(kind, ref, source, rating, votes, pop, url, fetched) "
                                 "VALUES(?,?,?,?,?,?,?,?)", rows)
            for r in rows:
                _Q.pop((V._db_path(conn), kind, ref), None)
    return n


def _key_info(conn, kind, ref):
    if kind == "work" and V._has_table(conn, "works"):
        r = conn.execute("SELECT author, title FROM works WHERE id=?", (int(ref),)).fetchone()
    elif kind == "item":
        r = conn.execute("SELECT author, title FROM items WHERE id=?", (ref,)).fetchone()
    else:
        r = conn.execute("SELECT author, coalesce(nullif(work,''), title) FROM src_items WHERE id=?", (int(ref),)).fetchone()
    if not r:
        return None
    out = {"author": V._tidy(r[0]), "title": V._tidy(r[1])}
    q = conn.execute("SELECT url FROM qual_ratings WHERE kind=? AND ref=? AND source='wikidata'", (kind, ref)).fetchone()
    if q:
        c = conn.execute("SELECT en, authors FROM qual_canon WHERE qid=?", (q[0].rsplit("/", 1)[-1],)).fetchone()
        if c and c[0]:
            au = [a for a in json.loads(c[1] or "[]") if re.fullmatch(r"[A-Za-z .'\-]+", a)]
            out["en"] = (c[0], au[0] if au else "")
    return out


_Q = {}
_JUNK = re.compile(r"\b(78rpm|33rpm|vinyl|music|album|songs?|rock|jazz|folk|pop|idm|ambient|electronic|experimental|"
                   r"noise|glitch|downtempo|choral|opera|classical|melodiya|kirtan|yoga|iskcon|bhakti|lecture|sermons?|"
                   r"church|islam|podcast|news|radio reception|radio vk)\b|музык|песн|естрад|лекци|проповед|новост|"
                   r"подкаст|катха|бхакти|кришна|христиан|йог|вірш[іи] під|концерт|альбом|молитв|библи|bible|богослов|благовест|"
                   r"foundation_|семинар|вебинар", re.I)
_BOOK = re.compile(r"audiobook|librivox|literature|аудиокниг|аудіокниг|роман|рассказ|оповідан|повест|повість|"
                   r"фантаст|фэнтез|фентез|детектив|триллер|трилер|ужас|мистик|спектакл|драма|poetry|поэз|стих|сказк|"
                   r"приключ|классик|проза|антиутоп|постапок", re.I)


def quality_bulk(conn, keys):
    """[(kind, ref)] -> {key: {q, canon, rating, votes, pop, book, src}} — 0..1, байесовски сглаженный рейтинг."""
    out, need = {}, []
    dbp = V._db_path(conn)
    for k in keys:
        hit = _Q.get((dbp, k[0], k[1]))
        if hit is not None:
            out[k] = hit
        else:
            need.append(k)
    if not need:
        return out
    _ensure(conn)
    rat = {}
    for i in range(0, len(need), 400):
        ch = need[i:i + 400]
        cond = " OR ".join("(kind=? AND ref=?)" for _ in ch)
        for kind, ref, src, rating, votes, pop in conn.execute(
                f"SELECT kind, ref, source, rating, votes, pop FROM qual_ratings WHERE {cond}", [x for k in ch for x in k]):
            rat.setdefault((kind, ref), {})[src] = (rating, votes, pop)
    meta = _meta_bulk(conn, need)
    for k in need:
        r = rat.get(k, {})
        m = meta.get(k, {})
        canon = 0.0
        if "wikidata" in r:
            canon = min(1.0, math.log1p(r["wikidata"][2] or 0) / math.log1p(60))
        elif "author" in r:
            canon = 0.45 * min(1.0, math.log1p(r["author"][2] or 0) / math.log1p(60))
        parts = []                                   # (сглаженная оценка 0..1, вес)
        if r.get("knigavuhe") and r["knigavuhe"][1]:
            p, n = r["knigavuhe"][0], r["knigavuhe"][1]
            sm = (p * n + 0.86 * 15) / (n + 15)     # средняя доля лайков на knigavuhe ≈ 0,86; 15 голосов — «сила» приора
            parts.append((max(0.0, min(1.0, (sm - 0.6) / 0.4)), min(1.0, n / 50)))
        if r.get("openlibrary") and r["openlibrary"][1]:
            a, n = r["openlibrary"][0], r["openlibrary"][1]
            sm = (a * n + 3.8 * 8) / (n + 8)
            parts.append((max(0.0, min(1.0, (sm - 3.0) / 2.0)), min(1.0, n / 30)))
        rating = (sum(p * w for p, w in parts) / sum(w for _, w in parts)) if parts and sum(w for _, w in parts) else None
        views = max([x for x in (m.get("views"), (r.get("knigavuhe") or (0, 0, None))[2]) if x] or [0])
        pop = min(1.0, math.log1p(views) / math.log1p(500000)) if views else 0.0
        book = m.get("book", 0.7)
        q = 0.12 + 0.45 * canon + 0.12 * pop + 0.31 * (rating if rating is not None else 0.42)
        out[k] = _Q[(dbp, k[0], k[1])] = {"q": round(q, 3), "canon": round(canon, 3), "rating": rating and round(rating, 3),
                                         "pop": round(pop, 3), "book": book}
    return out


def _meta_bulk(conn, keys):
    """Книжность (теги/жанр/длительность) и просмотры лучшей записи: {key: {book, views}}."""
    out = {}
    wids = [int(r) for k, r in keys if k == "work"]
    sids = [int(r) for k, r in keys if k == "src"]
    rows = []
    if wids and V._has_table(conn, "works"):
        for i in range(0, len(wids), 500):
            ch = wids[i:i + 500]
            rows += [("work", str(r[0])) + tuple(r[1:]) for r in conn.execute(
                f"SELECT w.id, w.genre, group_concat(s.tags, ','), group_concat(s.genre, ','), max(s.views), max(s.duration_s), "
                f"group_concat(s.src, ','), w.title || ' ' || w.author FROM works w LEFT JOIN src_items s ON s.work_id=w.id WHERE w.id IN "
                f"({','.join('?' * len(ch))}) GROUP BY w.id", ch)]
    if sids:
        rows += [("src", str(r[0])) + tuple(r[1:]) for r in conn.execute(
            f"SELECT id, genre, tags, genre, views, duration_s, src, title || ' ' || author FROM src_items WHERE id IN ({','.join('?' * len(sids))})", sids)]
    for kind, ref, g1, tags, g2, views, dur, srcs, title in rows:
        txt = " ".join(x or "" for x in (g1, tags, g2))
        junk, bk = bool(_JUNK.search(txt)), bool(_BOOK.search(txt))
        yt = bool(srcs) and not set((srcs or "").split(",")) <= {"archive"}
        book = 1.0 if (bk and not junk) or yt else (0.25 if junk and not bk else (0.6 if junk else 0.55))
        if dur and dur < 600 and not yt:
            book *= 0.6
        if re.search(r"voice of korea|выпуск|эфир|\bновости\b", (title or "") + " " + txt, re.I):
            book *= 0.4
        out[(kind, ref)] = {"book": round(book, 2), "views": views}
    for k in keys:
        if k[0] == "item":
            out[k] = {"book": 1.0, "views": None}
    return out


def quality_status(conn):
    _ensure(conn)
    return {"canon": conn.execute("SELECT count(*) FROM qual_canon").fetchone()[0],
            "by_source": dict(conn.execute("SELECT source, count(*) FROM qual_ratings GROUP BY source").fetchall())}


# ======================================================================================== ранжирование

def _anchors(pr):
    """Сигналы -> якоря для демона: [{key|text, w, sign, i}]."""
    out = []
    for sign, lst in ((1, pr["pos"]), (-1, pr["neg"])):
        for i, s in enumerate(lst):
            out.append({"key": list(s["key"]) if s.get("key") else None, "text": s.get("text") or s["label"],
                        "w": s["w"], "sign": sign, "label": s["label"],
                        "facet": s["src"] in ("ИИ: любите", "анкета: автор", "память", "анкета: ещё")})
    return out


def _lang_score(lang, langw):
    """Язык записи по весам abook_ai.lang_weights (ru и uk на равных, en «немного»): 0..1 от лучшего языка."""
    lang = (lang or "").split(",")[0].strip().lower()[:2]
    mx = max(1, max(langw.values()))
    if lang in langw:
        return max(0.0, langw[lang]) / mx
    return 0.6 if not lang else 0.2


def _dur_fit(h, pref):
    if not h:
        return 0.55
    if not pref:
        return 0.8 if 0.5 <= h <= 30 else 0.5
    lo, hi = pref
    if lo <= h <= hi:
        return 1.0
    d = (lo / h) if h < lo else (h / hi)
    return max(0.0, 1.0 - 0.45 * math.log2(d))


_DARK = re.compile(r"мрачн|жесток|кровав|ужас|маньяк|убийц|убийств|насили|смерт|кошмар|безысход|тьм|страх|хоррор|horror", re.I)
_LIGHT = re.compile(r"добр|светл|юмор|уютн|смешн|весёл|весел|сказк|тепл|романтич", re.I)
_AIVOICE = re.compile(r"\bИИ\b|нейросет|AI[- ]?(voice|озвуч)|синтез", re.I)


def _cards(conn, keys):
    """describe + для произведений — поля лучшей открытой записи (src_key, url, часы, чтец, доступ, полнота)."""
    cards = {(c["kind"], c["ref"]): c for c in V.describe(conn, keys)}
    wids = [int(r) for k, r in keys if k == "work"]
    if wids and V._has_table(conn, "works"):
        for i in range(0, len(wids), 500):
            ch = wids[i:i + 500]
            for r in conn.execute(
                    f"SELECT w.id, w.n_public, w.langs, w.annotation, w.duration_s, w.readers, s.source_id, s.url, s.platform, "
                    f"s.availability, s.downloadable, s.complete_score, s.reader, s.duration_s, s.lang, s.title, s.id, w.genre "
                    f"FROM works w LEFT JOIN src_items s ON s.id=w.best_record WHERE w.id IN ({','.join('?' * len(ch))})", ch):
                c = cards.get(("work", str(r[0])))
                if not c:
                    continue
                c.update(n_public=r[1], lang=(r[14] or r[2] or ""), about=V._clip(r[3], 240), hours=V._hours(r[13] or r[4]),
                         reader=r[12] or (r[5] or "").split(",")[0], src_key=r[6], url=r[7], platform=r[8],
                         availability=r[9] or "unknown", downloadable=bool(r[10]) if r[10] is not None else True,
                         complete=r[11], raw_title=r[15], best_src=r[16], genre=r[17])
    sids = [int(r) for k, r in keys if k == "src"]
    if sids:
        for r in conn.execute(f"SELECT id, complete_score, annotation, work_id FROM src_items WHERE id IN ({','.join('?' * len(sids))})", sids):
            c = cards.get(("src", str(r[0])))
            if c:
                c.update(complete=r[1], about=V._clip(r[2], 240), work_id=r[3])
    return cards


def rank(conn, pid, text="", k=40, mode="foryou", pr=None, weights=None, hide=(), targets=None, recall_n=600,
         bridges=(), lib=None, exclude_ids=()):
    """Двухэтапный отбор. mode: foryou — только нескачанное (каталог источников + библиотека без файла);
    rag — всё, что можно советовать (скачанное тоже). -> {items:[карточка + score, parts, facet], facets, ms, ...}.
    targets — ключи, чей ранг вернуть (для офлайн-оценки), без исключения «знакомого» для них."""
    t0 = time.perf_counter()
    F = _F()
    w = {**W, **(weights or {})}
    pr = pr or profile(conn, pid)
    if not V.enabled():
        return {"items": [], "vec": False, "note": "нет векторов"}
    V.ensure_sync(conn)
    anchors = _anchors(pr)
    kinds = ["item", "work", "src"]
    extra = [list(t) for t in targets or []]
    r = V.call(conn, "rank", anchors=anchors, kinds=kinds, k=recall_n, extra=extra) if anchors else None
    sc = {}                       # key -> {taste, knn, neg, facet}
    facets = []
    if r:
        facets = r.get("facets") or []
        for h in r["hits"]:
            sc[(h[0], h[1])] = {"taste": h[2], "knn": h[3], "neg": h[4], "facet": h[5]}
    qrank = {}
    if text and text.strip():
        hy = V.hybrid(conn, text, k=80, scope="all")["items"]
        for n, c in enumerate(hy):
            qrank[(c["kind"], c["ref"])] = 1.0 / (1 + n / 8)
    for b in bridges:
        qrank.setdefault(("item", b), 0.0)
    # канон, которого нет в recall по вкусу (качество как отдельный канал)
    qk = []
    with contextlib.suppress(sqlite3.Error):
        qk = [(kd, rf) for kd, rf in conn.execute(
            "SELECT kind, ref FROM qual_ratings WHERE source='wikidata' ORDER BY pop DESC LIMIT 300")]
    aff_fn = _author_affinity(pr.get("authors") or [])
    ak = _author_keys(conn, aff_fn) if aff_fn else []       # все произведения любимых авторов — тоже в recall
    missing = [x for x in list(qrank) + qk + ak if x not in sc]
    if missing and anchors:
        r2 = V.call(conn, "rank", anchors=anchors, kinds=kinds, k=0, extra=[list(x) for x in missing])
        for h in (r2 or {}).get("hits") or []:
            sc[(h[0], h[1])] = {"taste": h[2], "knn": h[3], "neg": h[4], "facet": h[5]}
    pool = list(dict.fromkeys(list(sc) + list(qrank) + ak))
    # src с произведением — под ключом произведения
    if any(x[0] == "src" for x in pool):
        sids = [int(x[1]) for x in pool if x[0] == "src"]
        wmap = {str(a): str(b) for a, b in conn.execute(
            f"SELECT id, work_id FROM src_items WHERE work_id IS NOT NULL AND id IN ({','.join('?' * len(sids))})", sids)}
        for x in [x for x in pool if x[0] == "src" and x[1] in wmap]:
            wk = ("work", wmap[x[1]])
            if wk not in sc and x in sc:
                sc[wk] = sc[x]
            if x in qrank:
                qrank[wk] = max(qrank.get(wk, 0), qrank[x])
            if targets and x in targets:
                targets = list(targets) + [wk]
        pool = list(dict.fromkeys(("work", wmap[x[1]]) if x[0] == "src" and x[1] in wmap else x for x in pool))
    cards = _cards(conn, pool)
    qual = quality_bulk(conn, pool)
    bridge = _bridge_scores(conn, pr, pool)
    tv = [s["taste"] for s in sc.values()] or [0.0]
    t_hi = sorted(tv)[-max(1, len(tv) // 50)]       # верх 2 % — «1»
    known = pr["known"]
    avoid = pr["avoid_authors"]
    lib_items = {}
    for iid, a, t, inl in conn.execute("SELECT id, author, title, in_library FROM items WHERE in_library=1 OR custom=1"):
        lib_items[iid] = (a, t, inl)
    has_file = {x[0] for x in conn.execute("SELECT DISTINCT item_id FROM files WHERE status='done' AND path_wsl != ''")}
    tset = set(map(tuple, targets or []))
    bset = set(bridges)
    C = _C()
    kn_ids = {kn["id"] for kn in known if kn.get("id")}
    kn_tk = {}
    for kn in known:
        if kn.get("title"):
            kn_tk.setdefault(C._title_key(kn["title"]), []).append(kn)
    kn_pre = {F._nt(kn["title"])[:5] for kn in known if kn.get("title")}
    av_toks = [C._author_toks(x) for x in avoid]

    series = [(kn["series"][0], _author_affinity([(kn["author"], 1.0)]) if kn["author"] else None)
              for kn in known if kn.get("series")]

    def is_known(key, a, t):
        if key[1] in kn_ids:
            return True
        for pre, af in series:
            tt = _atoks(t)
            if tt and tt[0][:5] == pre[:5] and (af is None or af(a) > 0):
                return True
        at = C._author_toks(a)
        for kn in kn_tk.get(C._title_key(t), ()):
            ka = C._author_toks(kn["author"])
            if not at or not ka or at & ka:
                return True
        return F._nt(t)[:5] in kn_pre and any(F.same_book(kn["author"], kn["title"], a, t) for kn in known if kn.get("title"))

    out = []
    for key in pool:
        c = cards.get(key)
        if not c or not (c.get("title") or "").strip():
            continue
        is_t = key in tset
        a, t = c.get("author") or "", c.get("title") or ""
        if not is_t:
            if c.get("availability") == "members" or (key[0] != "item" and not c.get("downloadable", True)):
                continue
            if key[0] != "item" and _irrelevant(c):
                continue
            if key[0] == "item":           # «уже прочитано»/свои (in_library=0) — заметки, а не книги для совета
                if not (lib_items.get(key[1]) or (0, 0, 0))[2] or (mode == "foryou" and key[1] in has_file):
                    continue
                if (lib is not None and key[1] not in lib) or key[1] in exclude_ids:
                    continue
            if is_known(key, a, t):
                continue
            if av_toks and any(x and x & C._author_toks(a) for x in av_toks):
                continue
        s = sc.get(key) or {"taste": min(tv), "knn": 0.0, "neg": 0.0, "facet": -1}
        ql = qual.get(key) or {"q": 0.3, "book": 0.7}
        about = (c.get("about") or "") + " " + (c.get("genre") or "")
        dark = len(_DARK.findall(about)) - len(_LIGHT.findall(about))
        tone = 0.0
        if pr["dark"] and about.strip():
            tone = max(-1.0, min(1.0, pr["dark"] * (0.4 * dark)))
        if pr.get("bedtime") and dark >= 2:
            tone -= 0.2
        aiv = bool(_AIVOICE.search((c.get("raw_title") or "") + " " + (c.get("reader") or "")))
        parts = {
            "taste": max(0.0, min(1.2, (s["taste"]) / max(0.5, t_hi))),
            "knn": max(0.0, min(1.2, s["knn"] / max(0.5, t_hi))),
            "neg": max(0.0, s["neg"] - 1.0) / 2.0,
            "query": qrank.get(key, 0.0),
            "qual": ql["q"],
            "bridge": max(bridge.get(key, 0.0), 0.6 if key[0] == "item" and key[1] in bset else 0.0),
            "access": 1.0 if (key[0] == "item" or c.get("availability") == "public") else 0.6,
            "complete": c.get("complete") if c.get("complete") is not None else (1.0 if key[0] == "item" else 0.6),
            "lang": _lang_score(c.get("lang"), pr["langw"]),
            "dur": _dur_fit(c.get("hours"), pr["hours"]),
            "tone": tone,
            "junk": 1.0 - ql.get("book", 0.7),
            "meta": (0.4 if a.strip() else 0) + (0.3 if c.get("hours") else 0) + (0.3 if (c.get("about") or "").strip() else 0),
            "author": aff_fn(a) if aff_fn else 0.0,
        }
        # личное (вкус, запрос, мост, автор) × «ворота» качества + аддитивная добавка качества и мелкие поправки:
        # чистая сумма с большим весом качества превращала выдачу в одинаковый для всех «канон», а без него —
        # в безымянные веб-романы, похожие на теги вкуса. Произведение «зайдёт И хорошее».
        pers = (w["taste"] * parts["taste"] + w["knn"] * parts["knn"] - w["neg"] * parts["neg"] + w["query"] * parts["query"]
                + w["bridge"] * parts["bridge"] + w["author"] * parts["author"])
        gate = 1.0 - w["qgate"] + w["qgate"] * min(1.0, ql["q"] / 0.85)
        score = (max(0.0, pers) * gate + min(0.0, pers) + w["qual"] * parts["qual"] + w["access"] * parts["access"]
                 + w["complete"] * parts["complete"] + w["lang"] * parts["lang"] + w["dur"] * parts["dur"]
                 + w["tone"] * parts["tone"] - w["junk"] * parts["junk"] + w["meta"] * parts["meta"]
                 - (0.15 if aiv and pr["ai_voice_bad"] else 0.05 * aiv))
        out.append({**c, "score": round(score, 4), "parts": {k2: round(v, 3) for k2, v in parts.items()},
                    "facet": s["facet"], "quality": ql, "ai_voice": aiv, "_t": is_t})
    out.sort(key=lambda x: -x["score"])
    # одна строка на книгу: библиотечная запись и произведение каталога — одна книга
    res, seen = [], {}
    for c in out:
        tk = C._title_key(c.get("title") or "") or (c.get("title") or "").lower()
        at = C._author_toks(c.get("author") or "")
        prev = seen.setdefault(tk, [])
        if any((not x or not at or x & at) for x in prev) and not c["_t"]:
            continue
        prev.append(at)
        res.append(c)
    ranks = {}
    if tset:
        for i, c in enumerate(res):
            if (c["kind"], c["ref"]) in tset and "first" not in ranks:
                ranks["first"] = i + 1
    lw = pr["langw"]
    en_cap = k if lw.get("en", 0) >= 0.5 * max(lw.values()) else (0 if lw.get("en", 0) <= 0 else max(1, k // 5))
    top = _diverse(res, k, en_cap) if not tset else res[:k]
    for c in top:
        c.pop("_t", None)
        f = c.get("facet")
        c["facet_label"] = facets[f]["label"] if isinstance(f, int) and 0 <= f < len(facets) else ""
    if mode != "eval":
        _note_hits(conn, top)
        _maybe_features(conn, top)
    return {"items": top, "facets": facets, "pool": len(pool), "rank": ranks.get("first"), "vec": True,
            "ms": round((time.perf_counter() - t0) * 1000, 1)}


_IRREL = re.compile(r"визуализац|трейлер|trailer|teaser|тизер|обзор|review|разбор|пересказ|краткое содержание|"
                    r"саундтрек|soundtrack|\bost\b|музыка из|стрим|stream|анонс|подкаст|podcast|лекци|интервью|"
                    r"реакция|reaction|gameplay|геймплей|летсплей|прохождение", re.I)


_SERIES = re.compile(r"[,(\s]+(?:все|всі|весь|вся|усі)\s+(?:томи|тома|книги|части|частини|цикл|серия|серію)\b|"
                     r"[,(\s]+(?:цикл|серия|серія)\b", re.I)


def _irrelevant(c):
    """Не аудиокнига или пустая запись: игровая визуализация, трейлер, обзор, музыка, стрим (по названию/каналу),
    короче 10 минут, без автора и почти без текста (номер вместо названия)."""
    t = " ".join(str(c.get(x) or "") for x in ("raw_title", "title", "channel"))
    if _IRREL.search(t):
        return True
    h = c.get("hours")
    if h is not None and h < 10 / 60:
        return True
    title = (c.get("title") or "").strip()
    if not (c.get("author") or "").strip():
        letters = len(re.findall(r"[^\W\d_]", title))
        if letters < 4 or len((c.get("about") or "").strip()) < 60:
            return True
    return False


def _atoks(name):
    C = _C()
    return [C.fold(w) for w in re.findall(r"[^\W\d_]{3,}", str(name or "").lower())]


def _author_affinity(authors):
    """[(имя, вес)] -> f(автор записи) -> сумма весов совпавших (фамилия: 5 первых букв после fold, короче — целиком)."""
    pats = []
    for name, wt in authors:
        toks = [t for t in _atoks(name) if len(t) >= 3]
        if toks:
            pats.append((max(toks, key=len), wt))      # самое длинное слово — почти всегда фамилия
    if not pats:
        return None

    def f(author):
        mine = _atoks(author)
        s = 0.0
        for t, wt in pats:
            if any((u[:5] == t[:5]) if len(t) >= 5 and len(u) >= 5 else u == t for u in mine):
                s += wt
        return max(-1.0, min(1.0, s))
    return f


_AK = {}


def _author_keys(conn, aff):
    """Произведения каталога и книги библиотеки любимых авторов (aff > 0). Кэш на состав works."""
    sig = (V._db_path(conn), conn.execute("SELECT count(*), max(id) FROM works").fetchone() if V._has_table(conn, "works") else 0)
    if _AK.get("sig") != sig:
        rows = []
        if V._has_table(conn, "works"):
            rows += [("work", str(r[0]), r[1]) for r in conn.execute("SELECT id, author FROM works WHERE author != ''")]
        rows += [("item", r[0], r[1]) for r in conn.execute("SELECT id, author FROM items WHERE in_library=1")]
        _AK.update(sig=sig, rows=rows)
    return [(k, r) for k, r, a in _AK["rows"] if aff(a) > 0][:400]


def _diverse(res, k, en_cap=None):
    """Разнообразие: не больше трети выдачи из одной грани вкуса, не больше 2 книг одного автора, английских —
    не больше en_cap (английский «немного» ≈ 1 из 5)."""
    out, per_f, per_a, rest = [], {}, {}, []
    cap = max(3, k // 3)
    n_en = 0
    for c in res:
        f, a = c.get("facet"), (c.get("author") or "").strip().lower()
        is_en = (c.get("lang") or "").lower().startswith("en")
        if is_en and en_cap is not None and n_en >= en_cap:
            continue
        if per_f.get(f, 0) >= cap or (a and per_a.get(a, 0) >= 2):
            rest.append(c)
            continue
        n_en += is_en
        per_f[f] = per_f.get(f, 0) + 1
        if a:
            per_a[a] = per_a.get(a, 0) + 1
        out.append(c)
        if len(out) >= k:
            return out
    return out + rest[:k - len(out)]


def _bridge_scores(conn, pr, keys):
    """Мост карты связей: max сила связи кандидата (с признаками) с любимой книгой профиля (с признаками), 0..1."""
    try:
        import abook_links as L   # noqa: PLC0415
        L._bind()
        idx = L.index(conn)
    except Exception:
        return {}
    if not idx["n"]:
        return {}
    fav = set()
    for s in pr["pos"]:
        k = s.get("key")
        if k:
            fid = k[1] if k[0] == "item" else ("w" + k[1] if k[0] == "work" else None)
            if fid in idx["items"]:
                fav.add(fid)
    if not fav:
        return {}
    out = {}
    for k in keys:
        fid = k[1] if k[0] == "item" else ("w" + k[1] if k[0] == "work" else None)
        if fid in idx["items"] and fid not in fav:
            nb = L.neighbors(idx, fid, k=1, pool=fav)
            if nb:
                out[k] = min(1.0, nb[0]["score"] / 12.0)
    return out


# ------------------------------------------------------------------ ленивые признаки и рейтинги для топа

_BG = {"feat": 0.0, "rate": 0.0, "busy": False}


def _note_hits(conn, top):
    with contextlib.suppress(sqlite3.Error):
        _ensure(conn)
        with _wtx(conn):
            conn.executemany("INSERT INTO rank_hits(kind, ref, n, last) VALUES(?,?,1,?) ON CONFLICT(kind, ref) "
                             "DO UPDATE SET n=n+1, last=excluded.last", [(c["kind"], c["ref"], _now()) for c in top[:40]])


def _maybe_features(conn, top):
    """Фоном, не чаще FEAT_GAP: рейтинги для топа (≤ 20 запросов) и одна пачка признаков карты связей (≤ 25 книг)
    для частых нескачанных кандидатов без признаков."""
    if _BG["busy"]:
        return
    dbp = V._db_path(conn)
    keys = [(c["kind"], c["ref"]) for c in top if c["kind"] in ("work", "item")]
    now = time.time()
    do_rate = NET and now - _BG["rate"] > 120
    do_feat = FEATS_ON and now - _BG["feat"] > FEAT_GAP and _F().claude_ok()
    if not (do_rate or do_feat):
        return
    _BG["busy"] = True

    def run():
        c2 = sqlite3.connect(dbp, timeout=30)
        c2.row_factory = sqlite3.Row
        try:
            if do_rate:
                _BG["rate"] = time.time()
                fetch_ratings(c2, keys, max_n=20)
            if do_feat:
                if feature_batch(c2, keys):
                    _BG["feat"] = time.time()
        except Exception as e:
            with contextlib.suppress(Exception):
                _F().A.log(f"WARN: abook_rank: фон: {e}")
        finally:
            c2.close()
            _BG["busy"] = False
    threading.Thread(target=run, daemon=True, name="abook-rank-bg").start()


def feature_batch(conn, keys, size=25, min_hits=2):
    """Одна пачка признаков карты связей (Sonnet, как abook_links) для нескачанных произведений: сначала те, что
    попадали в выдачу ≥ min_hits раз, добор — текущий топ. -> сколько книг получили признаки."""
    import abook_links as L   # noqa: PLC0415
    L._bind()
    F = _F()
    have = {r[0] for r in conn.execute("SELECT item_id FROM book_features")}
    freq = [f"w{r[0]}" for r in conn.execute("SELECT ref FROM rank_hits WHERE kind='work' AND n>=? ORDER BY n DESC, last DESC "
                                             "LIMIT 200", (min_hits,))]
    cur = [f"w{r}" for k, r in keys if k == "work"]
    ids = [x for x in dict.fromkeys(freq + cur) if x not in have][:size]
    if not ids:
        return 0
    batch = []
    for wid in ids:
        r = conn.execute("SELECT author, title, genre, annotation FROM works WHERE id=?", (int(wid[1:]),)).fetchone()
        if r:
            batch.append({"id": wid, "author": V._tidy(r[0]), "title": V._tidy(r[1]), "section": r[2] or "каталог источников",
                          "about": r[3] or "", "note": "", "why": "", "kind": ""})
    job = F.new_job(status="running")
    data, meta, err = F.run_claude(L._feat_prompt(conn, batch), L.FEAT_SCHEMA, job, L.MAP_MODEL, tools=(),
                                   timeout=L.MAP_TIMEOUT, budget=1.5, who="Claude")
    if data is None:
        raise RuntimeError(f"признаки: {err}")
    by = {b["id"]: b for b in batch}
    rows = []
    for x in data.get("books") or []:
        iid = str(x.get("id") or "").strip(" []")
        if iid not in by:
            continue
        f = {kk: [t for t in dict.fromkeys(L._tag(y) for y in (x.get(kk) or []) if L._tag(y))][:6] for kk, _, _ in L.FACETS}
        f.update(genre=F._s(x.get("genre"), 60), medium=F._s(x.get("medium"), 40), era=F._s(x.get("era"), 40))
        rows.append((iid, L._sig(by[iid]), json.dumps(f, ensure_ascii=False), L.MAP_MODEL, F.A.now_iso()))
    with _wtx(conn):
        conn.executemany("INSERT OR REPLACE INTO book_features(item_id,sig,features,model,created) VALUES(?,?,?,?,?)", rows)
    L._IDX.clear()
    _BG["last_feat_meta"] = {k: (meta or {}).get(k) for k in ("cost_usd", "duration_s", "usage") if (meta or {}).get(k) is not None}
    return len(rows)


# ------------------------------------------------------------------ компактно для промпта

def taste_brief(conn, pid, facets=None):
    """Сводка модели вкуса для промпта консультанта (≈ 300–600 символов): грани, «избегать», реакции."""
    pr = profile(conn, pid)
    L = []
    if facets:
        L.append("грани: " + "; ".join(f["label"] for f in facets[:6]))
    elif pr["loves"]:
        L.append("грани: " + "; ".join(pr["loves"][:7]))
    neg = [s["label"] for s in pr["neg"] if s["src"] in ("ИИ: избегать", "анкета: избегать", "реакция 👎", "память")]
    if neg:
        L.append("избегать: " + "; ".join(dict.fromkeys(neg[:8])))
    fb = feedback_list(conn, pid)
    likes = [f"{f['author']} — {f['title']}".strip(" —") for f in fb if f["verdict"] == "like"][:8]
    if likes:
        L.append("👍 на советы: " + "; ".join(likes))
    if pr["hours"]:
        L.append(f"длина: {pr['hours'][0]:g}–{pr['hours'][1]:g} ч")
    if pr["avoid_authors"]:
        L.append("авторы — нет: " + ", ".join(pr["avoid_authors"][:8]))
    return "МОДЕЛЬ ВКУСА (из анкеты, профиля ИИ, отзывов, памяти и реакций; кандидаты уже отранжированы по ней): " + \
        " | ".join(L) if L else ""


# ======================================================================================== HTTP

def handle_get(h, conn, p, arg, pid):
    if p == "/api/find/foryou":
        k = max(1, min(100, int(arg("k") or 20)))
        res = rank(conn, pid, arg("q") or "", k=k, mode="foryou")
        res["items"] = [{x: c.get(x) for x in ("kind", "ref", "id", "src_key", "author", "title", "reader", "hours", "lang",
                                              "platform", "url", "availability", "about", "score", "parts", "quality",
                                              "facet_label", "in_library", "has_file")} for c in res["items"]]
        res["k"] = k
        return h._json(res)
    if p == "/api/find/feedback":
        return h._json({"items": feedback_list(conn, pid)})
    if p == "/api/find/quality/status":
        return h._json(quality_status(conn))
    return None


def handle_post(h, conn, p, payload, pid):
    if p == "/api/find/feedback":
        try:
            return h._json(feedback_add(conn, pid, payload or {}))
        except ValueError as e:
            return h._json({"error": str(e)}, 400)
    return None


if __name__ == "__main__":
    import sys
    a = sys.argv
    c = sqlite3.connect(a[a.index("--db") + 1] if "--db" in a else str(V.HOME / "library.db"), timeout=30)
    c.row_factory = sqlite3.Row
    if "canon" in a:
        print(refresh_canon(c, log=lambda m: print(m, flush=True)))
    elif "authors" in a:
        print(fetch_canon_authors(c), match_canon(c))
    elif "match" in a:
        print(match_canon(c))
    elif "ratings" in a:          # прогрев: рейтинги для канона и книг известных авторов (≈ 2 запроса/книгу, 1/с)
        lim = int(a[a.index("--limit") + 1]) if "--limit" in a else 200
        ks = [(k, r) for k, r in c.execute("SELECT kind, ref FROM qual_ratings WHERE source IN ('wikidata','author') "
                                           "ORDER BY source='wikidata' DESC, pop DESC")]
        print(fetch_ratings(c, ks, max_n=lim, log=print))
    print(quality_status(c))
