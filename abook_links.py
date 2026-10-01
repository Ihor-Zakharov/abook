"""abook_links — «карта связей» библиотеки и ИИ-консультант с памятью для вкладки «Найти» (`abook review`).

Карта связей. Для каждой книги (в библиотеке + свои/«уже прочитано») один раз извлекаются глубинные признаки —
не жанр: темы, идеи, мотивы, эмоциональный тон, приём/структура повествования, «на что цепляет», тип героя,
масштаб (+ жанр/медиа/эпоха — только чтобы видеть, где «мост» перепрыгивает в другой жанр). Считается пачками
по 25 книг за вызов `claude -p --model sonnet` без инструментов, в фоне по кнопке; результат — таблица
book_features (кэш по подписи автор|название|описание: изменилась книга — пересчитается; новые — «досчитать»).
Словарь признаков держится общим: в каждую пачку передаются уже употреблённые формулировки. Связи книга↔книга —
взвешенное пересечение признаков с IDF (stdlib, без зависимостей): редкий общий мотив весит больше частой темы.

Консультант. Чат по активному профилю: история в chat_sessions/chat_messages, «память консультанта» —
consultant_memory (короткие факты о вкусе; Claude обновляет их в каждом ответе — поле memory схемы, без
отдельного вызова; факты, поправленные пользователем, Claude не удаляет; «не интересно» у рекомендации — тоже факт).
Контекст ответа: lite-файл для ИИ профиля (анкета, профиль от ИИ, отзывы с весами, каталог с id), память,
«карта связей» (признаки любимых книг, готовые мосты в другие жанры, словарь самых связующих признаков),
история разговора. Модель — Opus (`claude -p`, как в abook_ai), WebSearch/WebFetch — только проверить, есть ли
запись вне библиотеки. Ответ по JSON-схеме: текст + рекомендации «рядом» и «мосты» (цепочка «любимая X →
признак → Y»), регулятор «ближе ↔ дальше» и режим «удиви меня». Только stdlib.
"""
import contextlib
import hashlib
import json
import math
import re
import threading
import time
import os

import abook_find as F

A = None
AI = None


def _bind():
    global A, AI
    A, AI = F.A, F.AI


MAP_MODEL = os.environ.get("ABOOK_MAP_MODEL", "sonnet")
CHAT_MODEL = os.environ.get("ABOOK_CHAT_MODEL", "opus")
MAP_BATCH = 25
MAP_TIMEOUT = int(os.environ.get("ABOOK_MAP_TIMEOUT", "420"))
CHAT_TIMEOUT = int(os.environ.get("ABOOK_CHAT_TIMEOUT", "360"))
MAP_SEC_PER_CALL = 40            # оценка для UI: пачка из 25 книг у Sonnet ≈ 25–40 с (замер 30.09)
FACETS = [("themes", "темы", 1.0), ("ideas", "идеи", 1.2), ("motifs", "мотивы", 1.0), ("tone", "тон", 0.6),
          ("form", "приём", 0.8), ("hook", "цепляет", 1.0), ("hero", "герой", 0.8), ("scale", "масштаб", 0.4)]
FW = {k: w for k, _, w in FACETS}
FL = {k: lab for k, lab, _ in FACETS}
DISTANCE = [("ближе", "рядом с запросом: 1 мост из 5, в соседний жанр"),
            ("рядом", "2 моста из 5, можно в другой жанр той же эпохи"),
            ("дальше", "3 моста из 5: другой жанр, эпоха или медиа (радиоспектакль, нон-фикшн, пьеса, поэзия)"),
            ("совсем далеко", "4 моста из 5: совсем другой жанр/медиа, о котором слушатель, скорее всего, не думал")]


def _now():
    return A.now_iso()


_s, _line, _nt = F._s, F._line, F._nt


def _tag(s):
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()\[\]{}.,:;!?…/\\|_*#+=~]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" -")[:48]


def _tkey(tag):
    """Ключ совпадения признаков: основы слов (6 букв) — «одиночество» = «одиночества»."""
    return " ".join(w[:6] for w in tag.split() if w)


# ------------------------------------------------------------------ карта связей: данные

def map_books(conn):
    return A.get_items(conn, where="i.in_library=1 OR i.custom=1", full=True)


def _sig(it):
    return hashlib.sha1("|".join([it["author"] or "", it["title"] or "", it.get("about") or it.get("note") or "",
                                  it.get("why") or ""]).encode()).hexdigest()[:12]


def _stored(conn):
    out = {}
    for r in conn.execute("SELECT item_id, sig, features FROM book_features"):
        with contextlib.suppress(Exception):
            out[r[0]] = (r[1], json.loads(r[2]))
    return out


_MJOB = {"job": None}
_MLOCK = threading.Lock()


def map_status(conn):
    _bind()
    books = map_books(conn)
    st = _stored(conn)
    have = sum(1 for b in books if b["id"] in st and st[b["id"]][0] == _sig(b))
    stale = sum(1 for b in books if b["id"] in st and st[b["id"]][0] != _sig(b))
    missing = len(books) - have - stale
    todo = missing + stale
    calls = math.ceil(todo / MAP_BATCH) if todo else 0
    j = _MJOB["job"]
    job = None
    if j and not j.get("done"):
        job = {k: j.get(k) for k in ("phase", "batch", "batches", "done_books", "todo_books", "errors")}
        job["elapsed"] = round(time.time() - j["t0"], 1)
    last = j and j.get("done") and {k: j.get(k) for k in ("status", "error", "done_books", "errors", "finished")}
    idx = index(conn)
    top = sorted(idx["df"].items(), key=lambda kv: -kv[1])
    top = [{"label": idx["label"][k], "facet": idx["facet"][k], "n": n} for k, n in top if n >= 3][:18]
    return {"total": len(books), "have": have, "stale": stale, "missing": missing, "todo": todo, "calls": calls,
            "minutes": math.ceil(calls * MAP_SEC_PER_CALL / 60) if calls else 0, "batch": MAP_BATCH,
            "model": MAP_MODEL, "job": job, "last": last or None, "top": top, "claude": F.claude_ok()}


FEAT_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["books"], "properties": {"books": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["id"] + [k for k, _, _ in FACETS] + ["genre", "medium", "era"],
                               "properties": {"id": {"type": "string"},
                                              **{k: {"type": "array", "items": {"type": "string"}} for k, _, _ in FACETS},
                                              "genre": {"type": "string"}, "medium": {"type": "string"},
                                              "era": {"type": "string"}}}}}}


def _vocab(conn, per=30):
    cnt = {k: {} for k, _, _ in FACETS}
    for _, (_, f) in _stored(conn).items():
        for k in cnt:
            for t in f.get(k) or []:
                cnt[k][t] = cnt[k].get(t, 0) + 1
    return {k: [t for t, _ in sorted(v.items(), key=lambda kv: -kv[1])[:per]] for k, v in cnt.items()}


def _feat_prompt(conn, batch):
    voc = _vocab(conn)
    vl = [f"- {FL[k]} ({k}): " + ", ".join(v) for k, v in voc.items() if v]
    rows = []
    for b in batch:
        about = _line(b.get("about") or b.get("note"), 260)
        why = _line(b.get("why"), 160)
        rows.append(f"{b['id']} | {b['author'] or '?'} — «{b['title']}» | {b['section']} | {b.get('kind') or b.get('format') or ''}"
                    + (f" | {about}" if about else "") + (f" | для слушателя: {why}" if why else ""))
    return "\n\n".join([
        "Ты строишь «карту связей» личной аудиобиблиотеки: для каждой книги ниже извлеки ГЛУБИННЫЕ признаки — не "
        "жанр и не сюжет, а то, по чему книги разных жанров, эпох и форм перекликаются друг с другом.",
        "Поля (каждое — массив коротких формулировок по-русски, 1–3 слова, строчными, без имён героев и названий):\n"
        "- themes: 3–5 тем (напр. «вина», «одиночество», «власть и контроль», «память»);\n"
        "- ideas: 2–4 идеи/вопроса (напр. «реальность ненадёжна», «прогресс без морали», «цена бессмертия»);\n"
        "- motifs: 2–4 мотива/образа (напр. «машина наказания», «петля времени», «город-лабиринт», «двойник»);\n"
        "- tone: 1–3 эмоциональных тона (напр. «мрачный», «ироничный», «меланхоличный», «тревожный»);\n"
        "- form: 1–3 приёма/структуры повествования (напр. «ненадёжный рассказчик», «дневник», «рамочная история», "
        "«нарастающий абсурд»);\n"
        "- hook: 1–3 «на что цепляет» (напр. «загадка», «интеллектуальная игра», «катарсис», «напряжение»);\n"
        "- hero: 1–2 типа героя (напр. «маленький человек против системы», «одержимый гений», «наблюдатель»);\n"
        "- scale: 1 масштаб (напр. «камерный», «общество», «человечество», «космос/вечность»);\n"
        "- genre — жанр одним-двумя словами; medium — аудиокнига|радиоспектакль|рассказ|пьеса|нон-фикшн|игровая "
        "вселенная; era — эпоха написания («XIX век», «1960-е», «современность»).",
        "Переиспользуй уже принятые формулировки из словаря ниже, когда они подходят по смыслу (так книги свяжутся); "
        "новую вводи, только если ни одна не подходит. Если книгу не знаешь — опирайся на описание, признаков меньше.",
        "Словарь (самые частые формулировки):\n" + ("\n".join(vl) if vl else "- пока пуст"),
        "Книги (id | автор — название | раздел | вид | описание):\n" + "\n".join(rows),
        f"Верни ровно {len(batch)} записей books, id копируй точно. Ответ — только JSON по схеме."])


def start_map(conn, only_missing=True, max_batches=None):
    _bind()
    if not F.claude_ok():
        raise ValueError("Не найден Claude Code CLI (`claude`)")
    with _MLOCK:
        j = _MJOB["job"]
        if j and not j.get("done"):
            raise ValueError("Карта связей уже строится")
        books = map_books(conn)
        st = _stored(conn)
        todo = [b for b in books if not (b["id"] in st and st[b["id"]][0] == _sig(b))] if only_missing else books
        if not todo:
            raise ValueError("Карта связей уже построена — новых книг нет")
        batches = [todo[i:i + MAP_BATCH] for i in range(0, len(todo), MAP_BATCH)]
        if max_batches:                 # для проверок: только первые N пачек
            batches = batches[:max(1, int(max_batches))]
            todo = [b for bt in batches for b in bt]
        job = F.new_job(batch=0, batches=len(batches), done_books=0, todo_books=len(todo), errors=[], status="running")
        _MJOB["job"] = job
    threading.Thread(target=_map_worker, args=(job, batches), daemon=True, name="abook-map").start()
    return {"ok": True, "calls": len(batches), "books": len(todo)}


def cancel_map():
    j = _MJOB["job"]
    if not j or j.get("done"):
        return False
    F.cancel_job(j)
    return True


def _map_worker(job, batches):
    conn = A.db_connect()
    try:
        for i, batch in enumerate(batches, 1):
            job["batch"] = i
            F.phase(job, f"Пачка {i} из {len(batches)}: {len(batch)} книг → Claude {MAP_MODEL}")
            data, meta, err = F.run_claude(_feat_prompt(conn, batch), FEAT_SCHEMA, job, MAP_MODEL, tools=(),
                                           timeout=MAP_TIMEOUT, budget=1.5, who="Claude")
            if data is None:
                job["errors"].append(f"пачка {i}: {err}")
                if len(job["errors"]) >= 3 and not job["done_books"]:
                    raise RuntimeError(err)
                continue
            by = {b["id"]: b for b in batch}
            rows = []
            for r in data.get("books") or []:
                iid = str(r.get("id") or "").strip(" []")
                if iid not in by:
                    continue
                f = {k: [t for t in dict.fromkeys(_tag(x) for x in (r.get(k) or []) if _tag(x))][:6] for k, _, _ in FACETS}
                f.update(genre=_s(r.get("genre"), 60), medium=_s(r.get("medium"), 40), era=_s(r.get("era"), 40))
                rows.append((iid, _sig(by[iid]), json.dumps(f, ensure_ascii=False), MAP_MODEL, _now()))
            with A._WRITE_LOCK, A._tx(conn):
                conn.executemany("INSERT OR REPLACE INTO book_features(item_id,sig,features,model,created) VALUES(?,?,?,?,?)", rows)
            job["done_books"] += len(rows)
            if len(rows) < len(batch):
                job["errors"].append(f"пачка {i}: без признаков {len(batch) - len(rows)} книг")
        job["status"] = "done"
    except F.Cancelled:
        job["status"], job["error"] = "cancelled", "остановлено"
    except Exception as e:
        job["status"], job["error"] = "error", f"{type(e).__name__}: {e}"[:300]
    finally:
        job["done"] = True
        job["finished"] = _now()
        _IDX.clear()
        conn.close()


# ------------------------------------------------------------------ карта связей: индекс и соседи

_IDX = {}


def index(conn):
    """{items: id -> {key: facet}, df, idf, label, facet, meta: id -> {genre, medium, era}} — кэш до изменения таблицы."""
    sig = tuple(conn.execute("SELECT count(*), max(created) FROM book_features").fetchone())
    if _IDX.get("sig") == sig:
        return _IDX["v"]
    items, df, label, facet, meta = {}, {}, {}, {}, {}
    for iid, (_, f) in _stored(conn).items():
        keys = {}
        for k, _, w in FACETS:
            for t in f.get(k) or []:
                kk = _tkey(t)
                if kk and (kk not in keys or FW[keys[kk]] < w):
                    keys[kk] = k
                    label.setdefault(kk, t)
                    facet.setdefault(kk, k)
        items[iid] = keys
        meta[iid] = {"genre": f.get("genre") or "", "medium": f.get("medium") or "", "era": f.get("era") or ""}
        for kk in keys:
            df[kk] = df.get(kk, 0) + 1
    n = max(1, len(items))
    idf = {k: math.log((n + 1) / (d + 0.5)) for k, d in df.items()}
    v = {"items": items, "df": df, "idf": idf, "label": label, "facet": facet, "meta": meta, "n": len(items)}
    _IDX.update(sig=sig, v=v)
    return v


def neighbors(idx, iid, k=12, pool=None):
    mine = idx["items"].get(iid)
    if not mine:
        return []
    out = []
    for other, keys in idx["items"].items():
        if other == iid or (pool is not None and other not in pool):
            continue
        shared = []
        for kk in mine.keys() & keys.keys():
            if idx["df"].get(kk, 0) < 2:
                continue
            c = max(FW[mine[kk]], FW[keys[kk]]) * idx["idf"][kk]
            shared.append((c, kk))
        if not shared:
            continue
        shared.sort(reverse=True)
        out.append({"id": other, "score": round(sum(c for c, _ in shared), 2),
                    "shared": [{"label": idx["label"][kk], "facet": FL[idx["facet"][kk]], "w": round(c, 2)}
                               for c, kk in shared[:4]]})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


def _far(idx, a, b, items):
    """Мост в другой жанр/медиа/раздел?"""
    ma, mb = idx["meta"].get(a, {}), idx["meta"].get(b, {})
    sa = (items.get(a) or {}).get("section", "").split("/")[0]
    sb = (items.get(b) or {}).get("section", "").split("/")[0]
    return bool((ma.get("genre") and mb.get("genre") and _nt(ma["genre"])[:6] != _nt(mb["genre"])[:6])
                or (ma.get("medium") and mb.get("medium") and ma["medium"] != mb["medium"]) or (sa and sb and sa != sb))


def links_payload(conn, iid):
    _bind()
    idx = index(conn)
    own = idx["items"].get(iid)
    st = _stored(conn).get(iid)
    if not own:
        return {"id": iid, "ready": False, "map": {"have": idx["n"]}}
    nb = neighbors(idx, iid, k=16)
    items = {i["id"]: i for i in A.get_items(conn, ids=[x["id"] for x in nb] + [iid])}
    groups = {}
    for x in nb:
        it = items.get(x["id"])
        if not it:
            continue
        g = x["shared"][0]
        gg = groups.setdefault(g["label"], {"label": g["label"], "facet": g["facet"], "score": 0, "books": []})
        gg["score"] += x["score"]
        also = [s["label"] for s in x["shared"][1:3]]
        gg["books"].append({"id": it["id"], "author": it["author"], "title": it["title"], "has_file": it["has_file"],
                            "rstatus": it["rstatus"], "overall": it["overall"], "score": x["score"], "also": also,
                            "far": _far(idx, iid, it["id"], items)})
    gl = sorted(groups.values(), key=lambda g: -g["score"])[:6]
    for g in gl:
        g["books"] = g["books"][:4]
        g["score"] = round(g["score"], 1)
    f = st[1] if st else {}
    feats = [{"facet": FL[k], "tags": f.get(k) or []} for k, _, _ in FACETS if f.get(k)]
    return {"id": iid, "ready": True, "groups": gl, "features": feats,
            "meta": {k: f.get(k, "") for k in ("genre", "medium", "era")}}


# ------------------------------------------------------------------ память консультанта

MEM_KINDS = {"taste": "вкус", "dislike": "не нравится", "context": "контекст", "not_interested": "не интересно"}
MEM_MAX_AUTO = 80


def memory_list(conn, pid):
    return [dict(r) for r in conn.execute("SELECT id, fact, kind, source, author, title, item_id, created, updated "
                                          "FROM consultant_memory WHERE profile_id=? ORDER BY id", (pid,))]


def _dup(a, b):
    ta, tb = F._nt(a), F._nt(b)
    if ta == tb:
        return True
    x = {ta[i:i + 3] for i in range(len(ta) - 2)}
    y = {tb[i:i + 3] for i in range(len(tb) - 2)}
    return 2 * len(x & y) / ((len(x) + len(y)) or 1) >= 0.8


def memory_op(conn, pid, p):
    op = p.get("op")
    now = _now()
    with A._WRITE_LOCK, A._tx(conn):
        if op == "add":
            fact = _s(p.get("fact"), 300)
            if not fact:
                raise ValueError("Пустой факт")
            kind = p.get("kind") if p.get("kind") in MEM_KINDS else "taste"
            conn.execute("INSERT INTO consultant_memory(profile_id,fact,kind,source,created,updated) VALUES(?,?,?,'user',?,?)",
                         (pid, fact, kind, now, now))
        elif op == "edit":
            fact = _s(p.get("fact"), 300)
            if not fact:
                raise ValueError("Пустой факт — удалите его крестиком")
            conn.execute("UPDATE consultant_memory SET fact=?, source='user', updated=? WHERE id=? AND profile_id=?",
                         (fact, now, int(p.get("id") or 0), pid))
        elif op == "delete":
            conn.execute("DELETE FROM consultant_memory WHERE id=? AND profile_id=?", (int(p.get("id") or 0), pid))
        elif op == "dismiss":
            a, t = _s(p.get("author"), 200), _s(p.get("title"), 300)
            if not t:
                raise ValueError("Нет названия")
            for r in conn.execute("SELECT id, author, title FROM consultant_memory WHERE profile_id=? AND kind='not_interested'", (pid,)):
                if F.same_book(r["author"], r["title"], a, t):
                    break
            else:
                why = _s(p.get("why"), 160)
                conn.execute("INSERT INTO consultant_memory(profile_id,fact,kind,source,author,title,item_id,created,updated)"
                             " VALUES(?,?,'not_interested','user',?,?,?,?,?)",
                             (pid, f"Не интересно: {(a + ' — ') if a else ''}«{t}»" + (f" ({why})" if why else ""), a, t,
                              _s(p.get("item_id"), 160) or None, now, now))
        else:
            raise ValueError("Неизвестная операция")
    return {"memory": memory_list(conn, pid)}


def _apply_memory(conn, pid, sid, mem, notes):
    if not isinstance(mem, dict):
        return 0, 0
    cur = memory_list(conn, pid)
    added = removed = 0
    now = _now()
    with A._WRITE_LOCK, A._tx(conn):
        auto_ids = {m["id"] for m in cur if m["source"] == "auto"}
        for rid in mem.get("remove") or []:
            with contextlib.suppress(TypeError, ValueError):
                if int(rid) in auto_ids:
                    conn.execute("DELETE FROM consultant_memory WHERE id=? AND profile_id=?", (int(rid), pid))
                    removed += 1
                else:
                    notes.append(f"память: факт #{rid} поправлен вами — не удаляю")
        facts = [m["fact"] for m in cur]
        for x in (mem.get("add") or [])[:5]:
            fact = _s((x or {}).get("fact") if isinstance(x, dict) else x, 300)
            if not fact or any(_dup(fact, f) for f in facts):
                continue
            kind = (x.get("kind") if isinstance(x, dict) else "") or "taste"
            kind = kind if kind in ("taste", "dislike", "context") else "taste"
            conn.execute("INSERT INTO consultant_memory(profile_id,fact,kind,source,session_id,created,updated)"
                         " VALUES(?,?,?,'auto',?,?,?)", (pid, fact, kind, sid, now, now))
            facts.append(fact)
            added += 1
        n = conn.execute("SELECT count(*) FROM consultant_memory WHERE profile_id=? AND source='auto'", (pid,)).fetchone()[0]
        if n > MEM_MAX_AUTO:
            conn.execute("DELETE FROM consultant_memory WHERE id IN (SELECT id FROM consultant_memory WHERE profile_id=? "
                         "AND source='auto' ORDER BY id LIMIT ?)", (pid, n - MEM_MAX_AUTO))
    return added, removed


# ------------------------------------------------------------------ консультант: контекст

_CH = {"type": "object", "additionalProperties": False, "required": ["from", "feature", "to"],
       "properties": {"from": {"type": "string"}, "feature": {"type": "string"}, "to": {"type": "string"}}}
CHAT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reply", "recs", "memory", "followups"],
    "properties": {
        "reply": {"type": "string"},
        "recs": {"type": "array", "maxItems": 10, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["id", "author", "title", "kind", "why", "chain", "medium", "confidence"],
            "properties": {"id": {"type": "string"}, "author": {"type": "string"}, "title": {"type": "string"},
                           "kind": {"type": "string", "enum": ["close", "bridge"]}, "why": {"type": "string"},
                           "chain": _CH, "medium": {"type": "string"},
                           "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}},
        "memory": {"type": "object", "additionalProperties": False, "required": ["add", "remove"],
                   "properties": {"add": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["fact", "kind"],
                       "properties": {"fact": {"type": "string"},
                                      "kind": {"type": "string", "enum": ["taste", "dislike", "context"]}}}},
                       "remove": {"type": "array", "items": {"type": "integer"}}}},
        "followups": {"type": "array", "maxItems": 4, "items": {"type": "string"}}}}


CHAT_FORMAT = """ФОРМАТ ОТВЕТА (важнее любых упоминаний «JSON по схеме» выше):
Сначала reply — сам ответ слушателю в Markdown (абзацы, **жирный**, короткие списки — по делу; книги из recs отдельным \
списком не перечисляй: они покажутся карточками под ответом, достаточно назвать главные в тексте). Он печатается \
слушателю по мере того, как ты пишешь, поэтому начинай сразу с сути.
Затем ОТДЕЛЬНОЙ строкой ровно `<<<DATA` и после неё один JSON-объект без поля reply:
{"recs": [{"id","author","title","kind":"close|bridge","why","chain":{"from","feature","to"},"medium","confidence"}],
 "memory": {"add": [{"fact","kind":"taste|dislike|context"}], "remove": [id]}, "followups": ["…"]}
После JSON ничего не пиши."""
DATA_MARK = "<<<DATA"


def _anchors(conn, pid, lib):
    """Любимое слушателя: отзывы ≥ 7 (прослушано/слушаю), понравившееся из анкеты, «уже прочитано» брифа."""
    out, seen = [], set()
    with A._profile_ctx(pid):
        revs = A._joined_reviews(conn)
    for r in sorted(revs, key=lambda r: -(r["overall"] or 0)):
        if (r["overall"] or 0) >= 7 and r["item_id"] not in seen:
            seen.add(r["item_id"])
            out.append((r["item_id"], f"отзыв {r['overall']}/10"))
    if AI:
        q = AI.get_questionnaire(conn, pid)["answers"]
        for e in q.get("books_liked") or []:
            iid = e.get("id")
            if not iid:
                hit = next((i for i in lib.values() if F.same_book(e.get("author") or "", e.get("title") or "", i["author"], i["title"])), None)
                iid = hit["id"] if hit else None
            if iid and iid not in seen:
                seen.add(iid)
                out.append((iid, "анкета: понравилось"))
    for it in lib.values():
        if it["custom"] and it["source"] == "read" and it["id"] not in seen and pid == F.A.DEFAULT_PROFILE_ID:
            seen.add(it["id"])
            out.append((it["id"], "уже прочитано (бриф)"))
    return out[:14]


def links_context(conn, pid, lib, excluded, short=False):
    """Текст «КАРТА СВЯЗЕЙ» для промпта: признаки любимых книг, готовые мосты, связующие признаки.
    short — есть граф ассоциаций (abook_assoc): мосты дал он, здесь только признаки якорей, 2 моста, 20 признаков."""
    idx = index(conn)
    if not idx["n"]:
        return "КАРТА СВЯЗЕЙ: ещё не построена (мосты ищи сам, по своему знанию книг)."
    anchors = [(a, why) for a, why in _anchors(conn, pid, lib) if a in idx["items"]]
    st = _stored(conn)
    L = [f"КАРТА СВЯЗЕЙ (глубинные признаки {idx['n']} книг; мост = общий редкий признак у книг разных жанров/медиа):"]
    pool = {i for i in lib if i not in excluded and lib[i]["in_library"]}
    for a, why in anchors:
        f = st.get(a, (None, {}))[1]
        it = lib.get(a) or {}
        L.append(f"◆ [{a}] {it.get('author') or '?'} — «{it.get('title') or a}» ({why}; {f.get('genre') or '?'}, "
                 f"{f.get('medium') or '?'}): " + "; ".join(f"{FL[k]}: {', '.join(f.get(k) or [])}" for k, _, _ in FACETS if f.get(k)))
        nb = neighbors(idx, a, k=24, pool=pool)
        far = [x for x in nb if _far(idx, a, x["id"], lib)][:2 if short else 4]
        near = [] if short else [x for x in nb if x not in far][:2]
        for tag, lst in (("мост", far), ("рядом", near)):
            for x in lst:
                o = lib.get(x["id"]) or {}
                m = idx["meta"].get(x["id"], {})
                L.append(f"   {tag} → [{x['id']}] {o.get('author') or '?'} — «{o.get('title') or x['id']}» ({m.get('genre') or '?'}, "
                         f"{m.get('medium') or '?'}, {m.get('era') or '?'}) через: " + ", ".join(s["label"] for s in x["shared"][:3]))
    top = sorted(idx["df"].items(), key=lambda kv: -kv[1])
    tl = [f"{idx['label'][k]} ({n})" for k, n in top if n >= 3][:20 if short else 45]
    if tl:
        L.append("Самые связующие признаки библиотеки (сколько книг): " + ", ".join(tl))
    return "\n".join(L)


_CHAT_RULES = """Правила:
1. reply — ответ живым человеческим языком на «вы», по делу, 2–8 предложений; не пересказывай анкету. Если вопрос не \
про подбор (например, о книге или авторе) — ответь, recs можно не давать.
2. recs — сколько сказано в «СКОЛЬКО КНИГ» ниже (0, если вопрос не о подборе). id — точно из списка КАНДИДАТЫ, КАРТЫ СВЯЗЕЙ (первое поле строки \
до «|») или АССОЦИАЦИЙ (последнее в скобках); «s123» — запись каталога источников, нет на диске, id как есть; иначе id="" и книга ВНЕ обоих списков (author и title точно, по-русски). Каталожные книги предпочтительнее, \
но мост вне библиотеки тоже хорош — его можно скачать одной кнопкой.
3. НИКОГДА не рекомендуй то, что в «УЖЕ ЗНАКОМО» и «НЕ ИНТЕРЕСНО» (и другие издания/переводы/радиоверсии тех же \
произведений). Не повторяй книги, уже предложенные в этом разговоре, если слушатель не просит.
4. kind="close" — рядом с запросом (тот же жанр/настроение). kind="bridge" — МОСТ: книга другого жанра, эпохи или \
медиа, связанная с запросом или с любимой книгой слушателя через конкретный глубинный признак. Для моста chain \
обязателен: from — любимая книга/фильм слушателя или сам запрос, feature — общий признак (из «КАРТЫ СВЯЗЕЙ» или тема из «АССОЦИАЦИЙ», если \
есть), to — эта книга; why — почему связь работает и чем книга неожиданна. Для close chain можно пустыми строками.
5. Сколько мостов — по регулятору ниже. «Удиви меня» — хотя бы 3 моста в неожиданные жанры/медиа (пьеса, \
радиоспектакль, нон-фикшн, поэзия, игровая вселенная, классика другой эпохи), но каждый с честной цепочкой.
6. Это слушают: учитывай длину, язык (ru → uk → en), чтеца, ИИ-озвучку, скачано ли (ст=✓ лучше).
7. medium — аудиокнига|радиоспектакль|рассказ|пьеса|нон-фикшн|…; confidence 0..1 — насколько вероятно, что зайдёт.
8. memory — обнови «память консультанта»: add — 0–3 НОВЫХ коротких факта о вкусе/обстоятельствах слушателя, которые \
следуют из ЕГО слов в этом разговоре (не из твоих советов; не дублируй имеющиеся); remove — id фактов, которые \
слушатель опроверг. Нечего — пустые массивы.
9. followups — 2–4 коротких варианта следующего вопроса от лица слушателя.
10. WebSearch/WebFetch — только чтобы проверить, есть ли полная аудиозапись книги вне библиотеки (не больше 4 обращений).
11. Всё по-русски."""


RAG_N = int(os.environ.get("ABOOK_CHAT_CANDS", "40"))      # 0 — по-старому: весь §5 CATALOG в промпт


def _drop_catalog(doc):
    """Вырезать из lite-файла §5 CATALOG (строки библиотеки) и §7 INDEX (автор/чтец → id — без каталога не нужен);
    §5b OUTSIDE и остальное остаются."""
    i = doc.find("# §5 CATALOG")
    j = doc.find("## §5b OUTSIDE", i)
    if i >= 0 and j >= 0:
        doc = doc[:i] + doc[j:]
    i = doc.find("# §7 INDEX")
    if i >= 0:
        j = doc.find("\n# §", i + 5)
        doc = doc[:i] + (doc[j + 1:] if j >= 0 else "")
    return doc


def rag_context(conn, pid, text, lib, excluded, lctx):
    """≈ RAG_N кандидатов вместо §5 CATALOG (abook_vec: гибрид по сообщению + вкус + мосты карты связей + нескачанный
    каталог источников). Каждый с готовой строкой «line». None — по-старому (выключено или упало)."""
    if RAG_N <= 0:
        return None
    try:
        import abook_vec as V   # noqa: PLC0415
        bridges = [b for b in re.findall(r"→ \[([^\]]+)\]", lctx) if b in lib]
        cands = V.rag_candidates(conn, pid, text, lib, excluded, bridges, n=RAG_N)
        have = {c["ref"] for c in cands if c["kind"] == "item"}
        if len(cands) < RAG_N:          # мало нашлось (векторов нет, запрос не о книгах) — добор: скачанное без отзыва
            with A._profile_ctx(pid):
                rev = set(A.all_reviews(conn))
            pool = [i for i in lib.values() if i["in_library"] and i["id"] not in excluded and i["id"] not in have
                    and i["id"] not in rev]
            pool.sort(key=lambda i: (not i.get("start_here"), not i.get("has_file"), i["section"], i["author"]))
            cands += [{**c, "why": "добор"} for c in V.describe(conn, [("item", i["id"]) for i in pool[:RAG_N - len(cands)]])]
        st = _stored(conn)
        feats = {k: v[1] for k, v in st.items()}
        for c in cands:
            c["line"] = V.cand_line(c, feats)
        return cands
    except Exception as e:
        A.log(f"WARN: abook_links: кандидаты для консультанта: {e} — отдаю весь каталог")
        return None


def build_chat_prompt(conn, pid, sid, text, distance, surprise):
    prof = conn.execute("SELECT name FROM profiles WHERE id=?", (pid,)).fetchone()
    with A._profile_ctx(pid):
        doc = A.build_aidoc(conn, lite=True)
        libl = A.get_items(conn, where="i.in_library=1 OR i.custom=1")
    lib = {i["id"]: i for i in libl}
    known = AI.known_books(conn, pid) if AI else []
    tbrief = ""
    with contextlib.suppress(Exception):            # реакции «читал» — в «уже знакомо»; сводка модели вкуса
        import abook_rank as R   # noqa: PLC0415
        known += [{"id": f["item_id"], "author": f["author"], "title": f["title"], "how": "реакция на совет: читал"}
                  for f in R.feedback_list(conn, pid) if f["verdict"] == "read"]
        tbrief = R.taste_brief(conn, pid)
    mem = memory_list(conn, pid)
    noint = [m for m in mem if m["kind"] == "not_interested"]
    excluded = AI._known_ids(conn, known, [i for i in libl if i["in_library"]]) if AI else set()
    for m in noint:
        for it in libl:
            if (m.get("item_id") and it["id"] == m["item_id"]) or F.same_book(m["author"], m["title"], it["author"], it["title"]):
                excluded.add(it["id"])
    kl = [f"- {('[' + k['id'] + '] ') if k.get('id') and k['id'] in lib else ''}{(k['author'] + ' — ') if k['author'] else ''}"
          f"«{k['title']}» ({k['how']})" for k in known]
    ml = [f"- #{m['id']} [{MEM_KINDS.get(m['kind'], m['kind'])}{', от вас' if m['source'] == 'user' else ''}] {m['fact']}"
          for m in mem if m["kind"] != "not_interested"]
    mem_ids, summary, recent = [], "", None
    with contextlib.suppress(Exception):          # память слоями (abook_memory): факты под вопрос + резюме разговора
        import abook_memory as MEM   # noqa: PLC0415
        ml, mem_ids = MEM.select_facts(conn, pid, text)
        summary, recent = MEM.session_context(conn, sid)
        if recent and recent[-1].startswith("СЛУШАТЕЛЬ: ") and _line(text, 800) in recent[-1]:
            recent = recent[:-1]                  # новое сообщение идёт отдельным разделом
    hist = conn.execute("SELECT role, text, data FROM chat_messages WHERE session_id=? AND status='done' ORDER BY id DESC LIMIT 12",
                        (sid,)).fetchall()[::-1]
    hl = []
    for r in hist:
        if r["role"] == "user":
            hl.append(f"СЛУШАТЕЛЬ: {_line(r['text'], 800)}")
        else:
            d = json.loads(r["data"] or "{}")
            titles = "; ".join(f"{x.get('author') or ''} — «{x.get('title')}» ({'мост' if x.get('kind') == 'bridge' else 'рядом'})"
                               for x in d.get("recs") or [])
            hl.append(f"КОНСУЛЬТАНТ: {_line(r['text'], 700)}" + (f" [советы: {titles}]" if titles else ""))
    dist = max(0, min(3, int(distance or 0)))
    actx, asrc = "", {}
    with contextlib.suppress(Exception):          # граф ассоциаций (abook_assoc): мосты якорей по всему каталогу
        import abook_assoc as AS   # noqa: PLC0415
        actx, asrc = AS.chat_block(conn, pid, lib, excluded, known, extra=_anchors(conn, pid, lib))
    lctx = links_context(conn, pid, lib, excluded, short=bool(actx))
    cands = rag_context(conn, pid, text, lib, excluded, lctx)
    if cands is not None:
        doc = _drop_catalog(doc)
        cand_block = ("КАНДИДАТЫ (§5 CATALOG целиком не передаётся: локальный поиск уже отобрал книги под это сообщение — "
                      "по смыслу запроса, по вкусу слушателя и мостам карты связей). Строка: id | автор — название | часы | "
                      "чтец | пометки | откуда. id без «s» — книга библиотеки; «s123» — запись из каталога источников, "
                      "НЕТ НА ДИСКЕ (её можно скачать одной кнопкой) — для неё в recs id=\"s123\" как есть. Советуй прежде "
                      "всего из кандидатов и карты связей; книгу вне обоих списков — с id=\"\".\n"
                      + "\n".join(c["line"] for c in cands))
    knob = f"Регулятор «ближе ↔ дальше»: «{DISTANCE[dist][0]}» — {DISTANCE[dist][1]}." + \
        (" Включён режим «УДИВИ МЕНЯ»: запрос слушателя — лишь отправная точка, прыгай смело." if surprise else "")
    if recent is not None:                        # рабочая память разговора вместо 12 реплик целиком
        hl = recent
    sections = [
        ("rules", f"Ты — личный консультант по аудиокнигам, который помнит слушателя (профиль «{prof[0] if prof else '?'}»). "
         "Твоя фишка — ассоциативные «мосты»: ты находишь книги совсем других жанров, эпох и форм, которые связаны с "
         "тем, что человек любит, через глубинный признак (тема, мотив, приём, тон, тип героя), и объясняешь цепочку.\n\n"
         + _CHAT_RULES),
        ("profile", "=== ФАЙЛ БИБЛИОТЕКИ (lite): анкета и профиль, отзывы с весами, прошлые советы ИИ"
         + (" (§5 CATALOG заменён списком КАНДИДАТЫ ниже)" if cands is not None else ", §5 CATALOG") + " ===\n" + doc
         + "\n=== КОНЕЦ ФАЙЛА ==="),
        ("known", "УЖЕ ЗНАКОМО (прослушано/брошено/в анкете/прочитано — не предлагать):\n" + ("\n".join(kl) if kl else "- (пока ничего)")
         + "\n\nНЕ ИНТЕРЕСНО (слушатель отказался — не предлагать):\n"
         + ("\n".join(f"- {m['fact']}" for m in noint) if noint else "- ничего")),
        ("links", lctx + ("\n\n" + tbrief if tbrief else "")),
        ("assoc", actx),
        ("memory", "ПАМЯТЬ О СЛУШАТЕЛЕ (самое важное и относящееся к этому сообщению; #id — для memory.remove):\n"
         + ("\n".join(ml) if ml else "- пока пусто")),
        ("candidates", cand_block if cands is not None else ""),
        ("summary", ("РАННЕЕ В ЭТОМ РАЗГОВОРЕ (кратко):\n" + summary) if summary else ""),
        ("history", "РАЗГОВОР ДО ЭТОГО:\n" + ("\n".join(hl) if hl else "- это начало разговора")),
        ("message", knob + "\n\n" + f"НОВОЕ СООБЩЕНИЕ СЛУШАТЕЛЯ: «{text}»\n\n"
         + ("Напоминание: id только из КАНДИДАТОВ, «КАРТЫ СВЯЗЕЙ», «АССОЦИАЦИЙ» или пустой" if cands is not None else
            "Напоминание: id только из §5 CATALOG или пустой")
         + "; не из «УЖЕ ЗНАКОМО»/«НЕ ИНТЕРЕСНО»; мосты — с цепочкой; ответ — JSON по схеме.")]
    budget = None
    try:
        import abook_memory as MEM   # noqa: PLC0415
        prompt, budget = MEM.fit(sections)        # стабильное — первым (кэш Claude), изменчивое — последним
    except Exception:
        prompt = "\n\n".join(t for _, t in sections if t)
    return prompt, {"lib": lib, "excluded": excluded, "known": known, "noint": noint, "mem_ids": mem_ids, "budget": budget,
                    "src": {**asrc, **{c["id"]: c for c in cands or [] if c["kind"] == "src"}}}


def build_incognito_prompt(conn, sid, text, distance, surprise):
    """Инкогнито: ни анкеты, ни отзывов, ни памяти, ни карты вкуса — только каталог (гибридный поиск по сообщению)
    и этот разговор. Память по итогам не обновляется."""
    libl = A.get_items(conn, where="i.in_library=1")
    lib = {i["id"]: i for i in libl}
    cands = []
    with contextlib.suppress(Exception):
        import abook_vec as V   # noqa: PLC0415
        cands = V.hybrid(conn, text, k=40, scope="all")["items"]
        for c in cands:
            c["line"] = V.cand_line(c)
    hist = conn.execute("SELECT role, text FROM chat_messages WHERE session_id=? AND status='done' ORDER BY id DESC LIMIT 12",
                        (sid,)).fetchall()[::-1]
    hl = [("СЛУШАТЕЛЬ: " if r["role"] == "user" else "КОНСУЛЬТАНТ: ") + _line(r["text"], 700) for r in hist]
    dist = max(0, min(3, int(distance or 0)))
    prompt = "\n\n".join([
        "Ты — консультант по аудиокнигам. Режим ИНКОГНИТО: ты ничего не знаешь о слушателе, кроме этого разговора; "
        "не ссылайся на его прошлые вкусы. Умеешь ассоциативные «мосты» в другие жанры, эпохи и формы.",
        _CHAT_RULES.replace("memory — обнови", "memory — ВСЕГДА пустые массивы (инкогнито); не обновляй"),
        f"Регулятор «ближе ↔ дальше»: «{DISTANCE[dist][0]}» — {DISTANCE[dist][1]}."
        + (" Включён режим «УДИВИ МЕНЯ»." if surprise else ""),
        "КАНДИДАТЫ (локальный поиск по сообщению; id без «s» — книга библиотеки, «s123» — запись каталога источников, "
        "нет на диске, в recs id как есть; книгу вне списка — с id=\"\"):\n" + ("\n".join(c["line"] for c in cands) or "- нет"),
        "РАЗГОВОР ДО ЭТОГО:\n" + ("\n".join(hl) if hl else "- это начало разговора"),
        f"НОВОЕ СООБЩЕНИЕ СЛУШАТЕЛЯ: «{text}»"])
    return prompt, {"lib": lib, "excluded": set(), "known": [], "noint": [],
                    "src": {c["id"]: c for c in cands if c.get("kind") == "src"}}


def _sess_incognito(conn, sid):
    r = conn.execute("SELECT incognito FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    return bool(r and r[0])


def chat_migrate(conn):
    """Колонка инкогнито у разговоров; инкогнито-разговоры старше суток удаляются."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(chat_sessions)")}
    with A._WRITE_LOCK, A._tx(conn):
        if "incognito" not in cols:
            conn.execute("ALTER TABLE chat_sessions ADD COLUMN incognito INTEGER NOT NULL DEFAULT 0")
        old = [r[0] for r in conn.execute("SELECT id FROM chat_sessions WHERE incognito=1 AND updated < strftime('%Y-%m-%dT%H:%M:%S','now','-1 day')")]
        for sid in old:
            conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))


def validate_recs(data, ctx, notes, prev_titles):
    out = []
    for r in (data.get("recs") or [])[:10]:
        if not isinstance(r, dict):
            continue
        iid = re.sub(r"^[\s\[`'\"]+|[\s\]`'\".,]+$", "", str(r.get("id") or ""))
        a, t = _s(r.get("author"), 200), _s(r.get("title"), 300)
        srcs = ctx.get("src") or {}
        sc = srcs.get(iid) or (srcs.get("s" + iid) if iid.isdigit() else None)
        if not sc and t and srcs and not (iid and iid in ctx["lib"]):
            sc = next((c for c in srcs.values() if F.same_book(a, t, c["author"], c["title"])), None)
        if sc:            # запись каталога источников (нет на диске): вне библиотеки, но с конкретной записью
            iid, a, t = "", sc["author"] or a, sc["title"] or t
        it = ctx["lib"].get(iid) if iid else None
        if iid and not it:
            it = next((i for i in ctx["lib"].values() if F.same_book(a, t, i["author"], i["title"])), None)
            notes.append(f"id [{iid}] нет в каталоге" + (f" → по названию [{it['id']}]" if it else " — считаю книгой вне библиотеки"))
        if not it and t:
            it = next((i for i in ctx["lib"].values() if i["in_library"] and F.same_book(a, t, i["author"], i["title"])), None)
        if it:
            if it["id"] in ctx["excluded"]:
                notes.append(f"убрано «{it['title']}»: уже знакомо или «не интересно»")
                continue
            a, t, iid = it["author"], it["title"], it["id"]
        else:
            iid = ""
            if not t:
                continue
            hit = next((k for k in ctx["known"] if F.same_book(k["author"], k["title"], a, t)), None) or \
                next((m for m in ctx["noint"] if F.same_book(m["author"], m["title"], a, t)), None)
            if hit:
                notes.append(f"убрано «{t}»: уже знакомо или «не интересно»")
                continue
        if any(F.same_book(a, t, pa, pt) for pa, pt in prev_titles):
            notes.append(f"«{t}» уже предлагалась в этом разговоре")
        ch = r.get("chain") if isinstance(r.get("chain"), dict) else {}
        chain = {k: _s(ch.get(k), 200) for k in ("from", "feature", "to")}
        kind = "bridge" if r.get("kind") == "bridge" and chain["feature"] else "close"
        try:
            conf = min(1.0, max(0.0, float(r.get("confidence"))))
        except (TypeError, ValueError):
            conf = None
        out.append({"id": iid, "author": a, "title": t, "kind": kind, "why": _s(r.get("why"), 1400),
                    "chain": chain if kind == "bridge" else None, "medium": _s(r.get("medium"), 60), "confidence": conf})
        if sc and not it:     # скачивание именно этой записи: POST /api/find/download {catalog_key: src_key}
            out[-1].update(src_key=sc["src_key"], url=sc["url"], platform=sc.get("platform") or "",
                           reader=sc.get("reader") or "", hours=sc.get("hours"), availability=sc.get("availability"))
    return out


# ------------------------------------------------------------------ консультант: запуск

_CJOBS = {}
_CLOCK = threading.Lock()


def chat_send(conn, pid, sid, text, distance=1, surprise=False, reuse=False, incognito=False, count=0):
    """reuse=True — «перегенерировать»: последняя реплика слушателя уже в разговоре, новая не пишется."""
    _bind()
    if not getattr(chat_migrate, "ok", False):
        chat_migrate(conn)
        chat_migrate.ok = True
    text = _s(text, 2000)
    if not text:
        raise ValueError("Напишите, что хочется послушать")
    if not _llm_ok():
        raise ValueError("Не найден CLI выбранного ИИ (claude или agy) — консультант недоступен")
    with _CLOCK:
        if pid in _CJOBS:
            raise ValueError("Консультант ещё отвечает — подождите или отмените")
    now = _now()
    with A._WRITE_LOCK, A._tx(conn):
        if sid:
            if not conn.execute("SELECT 1 FROM chat_sessions WHERE id=? AND profile_id=?", (sid, pid)).fetchone():
                sid = None
        if not sid:
            sid = conn.execute("INSERT INTO chat_sessions(profile_id,title,created,updated,incognito) VALUES(?,?,?,?,?)",
                               (pid, _line(text, 70), now, now, 1 if incognito else 0)).lastrowid
        conn.execute("UPDATE chat_sessions SET updated=? WHERE id=?", (now, sid))
        if not reuse:
            conn.execute("INSERT INTO chat_messages(session_id,role,text,status,created,meta) VALUES(?,'user',?,'done',?,?)",
                         (sid, text, now, json.dumps({"distance": distance, "surprise": bool(surprise), "count": count})))
        mid = conn.execute("INSERT INTO chat_messages(session_id,role,text,status,created) VALUES(?,'assistant','','running',?)",
                           (sid, now)).lastrowid
    if not reuse:
        with contextlib.suppress(Exception):
            import abook_memory as MEM   # noqa: PLC0415
            MEM.log_event(conn, pid, "реплика", text, incognito=_sess_incognito(conn, sid))
    job = F.new_job(pid=pid, sid=sid, mid=mid, text=text, distance=int(distance or 0), surprise=bool(surprise),
                    reuse=bool(reuse), live="", count=max(0, min(10, int(count or 0))))
    with _CLOCK:
        _CJOBS[pid] = job
    threading.Thread(target=_chat_worker, args=(job,), daemon=True, name=f"abook-chat-{pid}").start()
    return {"ok": True, "session_id": sid, "message_id": mid}


def stream_claude(prompt, job, model, tools=(), timeout=360, budget=3.0, who="Claude"):
    """Как F.run_claude, но без --json-schema и с потоком: текст ответа до строки <<<DATA копится в job["live"]
    (UI опрашивает /api/find/chat/live и печатает его по мере генерации), JSON после неё разбирается в конце.
    -> (data | None, meta, error | None); data = {"reply": markdown, **JSON}."""
    import abook_llm as LLM   # noqa: PLC0415
    if LLM.provider() == "agy":
        data, meta, err = LLM.run(prompt, job, model, timeout=timeout, stream=True)
        if data is None:
            return None, meta, err
        full = data["text"]
        if DATA_MARK in full:
            reply, tail = full.split(DATA_MARK, 1)
            d = F.parse_json_loose(tail) or {}
        else:
            d = F.parse_json_loose(full)
            reply = (d or {}).get("reply") if isinstance(d, dict) else full
            d = d if isinstance(d, dict) else {}
        return {**d, "reply": (d.get("reply") or reply or "").strip()}, meta, None
    import subprocess   # noqa: PLC0415
    tl = ",".join(tools)
    cmd = [F.CLAUDE_BIN, "-p", "--model", model, "--output-format", "stream-json", "--verbose",
           "--include-partial-messages", "--safe-mode", "--no-session-persistence", "--tools", tl]
    if tools:
        cmd += ["--allowedTools", tl]
    cmd += ["--disallowedTools", F.DENY, "--permission-mode", "dontAsk", "--max-budget-usd", str(budget)]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(F.workdir()), env=F._clean_env(), start_new_session=True)
    except OSError as e:
        return None, {"seconds": 0}, f"{who} не запустился: {e}"
    job["procs"].add(proc)
    final, err_tail, buf, n = {}, [], [""], {"search": 0, "fetch": 0}

    def feed():
        with contextlib.suppress(Exception):
            proc.stdin.write(prompt.encode("utf-8"))
        with contextlib.suppress(Exception):
            proc.stdin.close()

    def read_out():
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", "replace"))
            except Exception:
                continue
            t = ev.get("type")
            if t == "stream_event":
                se = ev.get("event") or {}
                if se.get("type") == "message_start":      # новый ход модели (после поиска) — пишет ответ заново
                    buf[0] = ""
                elif se.get("type") == "content_block_delta" and (se.get("delta") or {}).get("type") == "text_delta":
                    buf[0] += se["delta"].get("text") or ""
                    if not job.get("streaming"):
                        job["streaming"] = True
                        F.phase(job, "Пишет ответ")
                    job["live"] = buf[0].split(DATA_MARK, 1)[0].rstrip("<").rstrip()
            elif t == "assistant":
                for c in (ev.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        name, inp = c.get("name"), c.get("input") or {}
                        if name == "WebSearch":
                            n["search"] += 1
                            F.event(job, "search", inp.get("query") or "", who)
                            F.phase(job, "Проверяю в интернете: " + _line(inp.get("query"), 80))
                        elif name == "WebFetch":
                            n["fetch"] += 1
                            F.event(job, "fetch", inp.get("url") or "", who)
            elif t == "result":
                final.update(ev)

    def read_err():
        for raw in proc.stderr:
            err_tail.append(raw.decode("utf-8", "replace").rstrip())
            del err_tail[:-20]

    ths = [threading.Thread(target=f, daemon=True) for f in (feed, read_out, read_err)]
    for th in ths:
        th.start()
    reason = None
    while proc.poll() is None:
        if job.get("cancel"):
            reason = "cancel"
        elif time.time() > t0 + timeout:
            reason = "timeout"
        if reason:
            F.kill(proc)
            break
        time.sleep(0.2)
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)
    for th in ths[1:]:
        th.join(timeout=5)
    job["procs"].discard(proc)
    meta = {"who": who, "model": model, "seconds": round(time.time() - t0, 1), "rc": proc.returncode,
            "cost_usd": final.get("total_cost_usd"), "turns": final.get("num_turns"), "stream": True, **n}
    if reason == "cancel" or job.get("cancel"):
        raise F.Cancelled()
    if reason == "timeout":
        return None, meta, f"{who}: нет ответа за {timeout // 60} мин"
    if not final:
        tail = " / ".join(x for x in err_tail[-3:] if x)
        return None, meta, f"{who} завершился без результата (код {proc.returncode}){': ' + tail[:300] if tail else ''}"
    if final.get("is_error") or final.get("subtype") not in (None, "success"):
        return None, meta, f"{who}: {final.get('subtype')}: {_line(final.get('result'), 300)}"
    full = final.get("result") or buf[0]
    if DATA_MARK in full:
        reply, tail = full.split(DATA_MARK, 1)
        data = F.parse_json_loose(tail) or {}
    else:                                   # модель забыла разделитель — может, весь ответ JSON
        data = F.parse_json_loose(full)
        reply = (data or {}).get("reply") if isinstance(data, dict) else full
        data = data if isinstance(data, dict) else {}
    data = {**data, "reply": (data.get("reply") or reply or "").strip()}
    return data, meta, None


def live_payload(pid):
    with _CLOCK:
        job = _CJOBS.get(pid)
    if not job:
        return {"job": None}
    return {"job": {"phase": job["phase"], "elapsed": round(time.time() - job["t0"], 1), "session_id": job["sid"],
                    "message_id": job["mid"], "text": job.get("live") or "", "events": list(job["events"])[-3:]}}


def chat_regen(conn, pid, sid):
    """«Перегенерировать»: убрать последний ответ и спросить заново той же репликой."""
    _bind()
    u = conn.execute("SELECT id, text, meta FROM chat_messages WHERE session_id=? AND role='user' ORDER BY id DESC LIMIT 1",
                     (sid,)).fetchone()
    if not u:
        raise ValueError("Нечего повторять")
    with _CLOCK:
        if pid in _CJOBS:
            raise ValueError("Консультант ещё отвечает")
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("DELETE FROM chat_messages WHERE session_id=? AND id>?", (sid, u["id"]))
    mt = json.loads(u["meta"] or "{}")
    return chat_send(conn, pid, sid, u["text"], mt.get("distance") or 0, mt.get("surprise"), reuse=True, count=mt.get("count") or 0)


def chat_edit(conn, pid, sid, mid, text, distance=0, surprise=False, count=0):
    """Правка своей реплики: она и всё после неё уходит, разговор продолжается с исправленного текста."""
    _bind()
    with _CLOCK:
        if pid in _CJOBS:
            raise ValueError("Консультант ещё отвечает")
    if not conn.execute("SELECT 1 FROM chat_messages m JOIN chat_sessions s ON s.id=m.session_id WHERE m.id=? AND "
                        "m.session_id=? AND s.profile_id=? AND m.role='user'", (mid, sid, pid)).fetchone():
        raise ValueError("Сообщение не найдено")
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("DELETE FROM chat_messages WHERE session_id=? AND id>=?", (sid, mid))
    return chat_send(conn, pid, sid, text, distance, surprise, count=count)


def chat_rename(conn, pid, sid, title):
    title = _line(title, 80)
    if not title:
        raise ValueError("Пустое название")
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("UPDATE chat_sessions SET title=? WHERE id=? AND profile_id=?", (title, sid, pid))
    return {"ok": True}


def chat_cancel(pid):
    with _CLOCK:
        job = _CJOBS.get(pid)
    if not job:
        return False
    F.cancel_job(job)
    return True


def _chat_worker(job):
    conn = A.db_connect()
    pid, sid, mid = job["pid"], job["sid"], job["mid"]
    status, err, data_out, notes, meta = "error", None, None, [], {}
    try:
        A._PROFILE.id = pid
        F.phase(job, "Собираю контекст: профиль, отзывы, память, карта связей")
        incog = _sess_incognito(conn, sid)
        meta["incognito"] = incog
        prompt, ctx = (build_incognito_prompt(conn, sid, job["text"], job["distance"], job["surprise"]) if incog else
                       build_chat_prompt(conn, pid, sid, job["text"], job["distance"], job["surprise"]))
        meta["prompt_chars"] = len(prompt)
        if ctx.get("budget"):
            meta["budget"] = ctx["budget"]
        F.phase(job, "ИИ думает")
        meta["regen"] = bool(job.get("reuse"))
        n = job.get("count") or 0
        count_rule = (f"СКОЛЬКО КНИГ: ровно {n} в recs (если слушатель просит совет)." if n else
                      "СКОЛЬКО КНИГ: авто — столько, сколько действительно сильных попаданий (1–7); лучше 3 точных, чем 7 средних.")
        data, m, e = stream_claude(prompt + "\n\n" + count_rule + "\n\n" + CHAT_FORMAT, job, CHAT_MODEL, F.WEB_TOOLS, timeout=CHAT_TIMEOUT, budget=3.0)
        meta.update(m)
        if data is None:
            raise RuntimeError(e)
        prev = []
        for r in conn.execute("SELECT data FROM chat_messages WHERE session_id=? AND role='assistant' AND status='done' "
                              "AND id<?", (sid, mid)):
            for x in (json.loads(r[0] or "{}").get("recs") or []):
                prev.append((x.get("author") or "", x.get("title") or ""))
        recs = validate_recs(data, ctx, notes, prev)
        added, removed = (0, 0) if incog else _apply_memory(conn, pid, sid, data.get("memory"), notes)
        if not incog and ctx.get("mem_ids"):
            with contextlib.suppress(Exception):
                import abook_memory as MEM   # noqa: PLC0415
                MEM.touch(conn, ctx["mem_ids"])
        data_out = {"recs": recs, "followups": [_s(x, 200) for x in (data.get("followups") or []) if _s(x)][:4],
                    "memory": {"added": added, "removed": removed}, "notes": notes,
                    "distance": job["distance"], "surprise": job["surprise"]}
        reply = _s(data.get("reply"), 6000)
        status = "done"
    except F.Cancelled:
        status, err, reply = "cancelled", "отменено", ""
    except Exception as e:
        status, err, reply = "error", str(e)[:400], ""
    finally:
        try:
            meta["seconds"] = round(time.time() - job["t0"], 1)
            with A._WRITE_LOCK, A._tx(conn):
                conn.execute("UPDATE chat_messages SET text=?, data=?, status=?, error=?, meta=? WHERE id=?",
                             (reply, json.dumps(data_out, ensure_ascii=False) if data_out else None, status, err,
                              json.dumps(meta, ensure_ascii=False), mid))
                conn.execute("UPDATE chat_sessions SET updated=? WHERE id=?", (_now(), sid))
        except Exception as ex:
            A.log(f"WARN: abook_links: ответ консультанта не сохранён: {ex}")
        finally:
            with _CLOCK:
                _CJOBS.pop(pid, None)
            conn.close()


def _enrich_rec(conn, r, queue):
    it = None
    if r.get("id"):
        x = A.get_items(conn, ids=[r["id"]])
        it = x[0] if x else None
    if not it and r.get("title"):
        lm = F.library_match(conn, r.get("author"), r["title"])
        it = lm["item"] if lm and lm["item"]["in_library"] else None
    r["item"] = it
    r["dl"] = None
    for e in queue:
        if F.same_book(r.get("author") or "", r.get("title") or "", e.get("author") or "", e.get("title") or ""):
            r["dl"] = {"state": e["state"], "key": e["key"], "item_id": e["item_id"], "k": e.get("k"), "n": e.get("n"),
                       "pct": e.get("pct")}
            break
    return r


def _llm_provider():
    import abook_llm as LLM   # noqa: PLC0415
    return LLM.provider()


def _llm_ok():
    import abook_llm as LLM   # noqa: PLC0415
    return LLM.available()[LLM.provider()]


def _llm_label():
    import abook_llm as LLM   # noqa: PLC0415
    return ("Gemini " + LLM.model_label(CHAT_MODEL)) if LLM.provider() == "agy" else "Claude " + CHAT_MODEL


def chat_payload(conn, pid, sid=None):
    if not getattr(chat_migrate, "ok", False):
        chat_migrate(conn)
        chat_migrate.ok = True
    sessions = [dict(r) for r in conn.execute(
        "SELECT s.id, s.title, s.created, s.updated, s.incognito, (SELECT count(*) FROM chat_messages m WHERE m.session_id=s.id "
        "AND m.role='user') AS n FROM chat_sessions s WHERE s.profile_id=? ORDER BY s.updated DESC LIMIT 80", (pid,))]
    if sid and not any(s["id"] == sid for s in sessions):
        r = conn.execute("SELECT id FROM chat_sessions WHERE id=? AND profile_id=?", (sid, pid)).fetchone()
        sid = r[0] if r else None
    if sid is None and sessions:
        sid = sessions[0]["id"]
    msgs = []
    if sid:
        queue = F.queue_payload()
        acts = _act_for(conn, pid)
        fbs = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='rec_feedback'").fetchone():
            fbs = [dict(r) for r in conn.execute("SELECT author, title, item_id, verdict FROM rec_feedback WHERE profile_id=? "
                                                 "ORDER BY rowid DESC LIMIT 300", (pid,))]
        for r in conn.execute("SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", (sid,)):
            d = dict(r)
            d["data"] = json.loads(d["data"]) if d["data"] else None
            d["meta"] = json.loads(d["meta"]) if d["meta"] else None
            if d["data"]:
                d["data"]["recs"] = [_attach_fb(_attach_acts(_enrich_rec(conn, x, queue), acts), fbs) for x in d["data"].get("recs") or []]
            msgs.append(d)
    with _CLOCK:
        job = _CJOBS.get(pid)
    j = None
    if job:
        j = {"phase": job["phase"], "elapsed": round(time.time() - job["t0"], 1), "session_id": job["sid"],
             "text": job.get("live") or "",
             "events": list(job["events"])[-6:]}
    return {"sessions": sessions, "session_id": sid, "messages": msgs, "job": j, "memory": memory_list(conn, pid),
            "distance": [d for d, _ in DISTANCE], "claude": _llm_ok(), "model": _llm_label(), "provider": _llm_provider()}


# ------------------------------------------------------------------ совет одной кнопкой: «в очередь» / «в Telegram»
# Книга скачана — действие сразу. Есть в каталоге, но не скачана — её запись встаёт в загрузки, действие ждёт
# окончания. Вне библиотеки — поиск с auto (однозначная полная запись качается сама), действие ждёт загрузки;
# неоднозначно или ничего — состояние «choose»: UI ведёт в «Найти» к этому поиску. Отложенные действия — таблица
# rec_actions, их доводит фоновый поток (переживает перезапуск сервера: поток стартует при первом обращении к чату).

ACT_SQL = """CREATE TABLE IF NOT EXISTS rec_actions(id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL,
  action TEXT NOT NULL, author TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, item_id TEXT, search_id INTEGER,
  dl_key TEXT, state TEXT NOT NULL, message TEXT, created TEXT, updated TEXT)"""
ACT_LIVE = ("search", "download")
_AWAKE = threading.Event()
_ATHREAD = None
_ALOCK = threading.Lock()
_SEEN = {}            # id действия → когда его поиск закончился без автозагрузки


def _act_table(conn):
    if not getattr(_act_table, "ok", False):
        with A._WRITE_LOCK:
            conn.execute(ACT_SQL)
            conn.commit()
        _act_table.ok = True


def _apply_now(conn, pid, action, iid):
    """Книга скачана: сделать действие. Возвращает (state, message)."""
    A._PROFILE.id = pid
    if action == "get":
        return "done", "скачано"
    if action == "queue":
        if iid not in A.get_queue(conn):
            A.queue_op(conn, {"op": "add", "item_id": iid})
        return "done", "в очереди"
    TG = A._g.get("TG")
    if not TG:
        return "failed", "Telegram недоступен"
    j = TG.start_send(iid)
    if j.get("error"):
        return "failed", j["error"]
    return "done", "в TG-очереди" + (f" · №{j['position']}" if j.get("position") else "")


def rec_action(conn, pid, p):
    _bind()
    _act_table(conn)
    action = p.get("action") if p.get("action") in ("tg", "get") else "queue"   # get — только скачать
    a, t = _s(p.get("author"), 200), _s(p.get("title"), 300)
    iid = _s(p.get("item_id"), 200)
    it = (A.get_items(conn, ids=[iid]) or [None])[0] if iid else None
    if not it and t:
        lm = F.library_match(conn, a, t)
        it = lm["item"] if lm and lm["item"]["in_library"] else None
    if not it and not t:
        raise ValueError("Нет книги")
    if it:
        a, t, iid = it["author"], it["title"], it["id"]
    sk = _s(p.get("src_key"), 200)
    old = conn.execute("SELECT id FROM rec_actions WHERE profile_id=? AND action=? AND state IN ('search','download') "
                       "AND (item_id=? OR (? = '' AND title=?) OR (dl_key<>'' AND dl_key=?))",
                       (pid, action, iid or "", sk, t, sk or "-")).fetchone()
    if old:
        return {"ok": True, "state": "waiting", "message": "уже ждёт загрузки"}
    sid = key = None
    if it and it["has_file"] and action == "get":
        return {"ok": True, "state": "done", "message": "Уже на диске", "item_id": iid}
    if it and it["has_file"]:
        state, msg = _apply_now(conn, pid, action, iid)
        if state == "done":
            msg = "Добавлено в очередь" if action == "queue" else "Telegram: " + msg
        return {"ok": state == "done", "state": state, "message": msg, "item_id": iid}
    if it and _members_only(conn, it):           # запись каталога только для спонсоров — ищем другую
        it = None
    src_key = _s(p.get("src_key"), 200)
    if not it and src_key:                      # совет из каталога источников — качаем именно эту запись
        import abook_catalog as C   # noqa: PLC0415
        r = C.enqueue_row(conn, src_key)
        if r.get("error"):
            raise ValueError(r["error"])
        key, state = r.get("key"), "download"
        msg = "Скачиваю эту запись" + {"tg": ", потом — в Telegram", "queue": ", потом — в очередь"}.get(action, "")
        now = _now()
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute("INSERT INTO rec_actions(profile_id,action,author,title,item_id,search_id,dl_key,state,message,"
                         "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                         (pid, action, a, t, None, None, key, state, msg, now, now))
        _act_kick()
        return {"ok": True, "state": state, "message": msg}
    if it:
        if action == "queue":                   # в очередь слушать можно и до скачивания
            _apply_now(conn, pid, "queue", iid)
        key = F.enqueue_catalog(conn, iid)["key"]
        state = "download"
        msg = "Скачиваю" + {"queue": " · уже в очереди", "tg": ", потом — в Telegram"}.get(action, "")
    else:
        sid = F.start_search(conn, pid, f"{a} — {t}" if a else t, auto=True)
        state, msg = "search", "Ищу полную запись"
    now = _now()
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("INSERT INTO rec_actions(profile_id,action,author,title,item_id,search_id,dl_key,state,message,"
                     "created,updated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, action, a, t, iid or None, sid, key, state, msg, now, now))
    _act_kick()
    return {"ok": True, "state": state, "message": msg, "search_id": sid}


def _members_only(conn, it):
    with contextlib.suppress(Exception):
        import abook_catalog as C   # noqa: PLC0415
        full = A.get_items(conn, ids=[it["id"]], full=True)
        urls = (full[0].get("urls") or []) if full else []
        return bool(urls) and C.availability(urls[0], conn) == "members"
    return False


# ------------------------------------------------------------------ жалоба на источник
# «Только для спонсоров», «неполная», «не та книга», «ИИ-голос/плохое качество», «не скачивается», «другое».
# Запись помечается сразу: в каталоге (members / полнота 0), в поиске (assess отсеивает ссылку с пометкой
# «вы пожаловались»), в «Ссылке» не выдаётся. Для скачанной книги — по желанию поиск другой записи.
REPORT_REASONS = {"members": "только для спонсоров", "partial": "неполная — часть книги", "wrong": "не та книга",
                  "quality": "ИИ-голос или плохое качество", "broken": "не скачивается", "other": "другое"}
_REPORTED = None


def _rep_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS source_reports(id INTEGER PRIMARY KEY, profile_id INTEGER, url TEXT,
      src_key TEXT, item_id TEXT, author TEXT, title TEXT, reason TEXT NOT NULL, note TEXT, created TEXT)""")


def _url_key(u):
    u = (u or "").strip()
    m = re.search(r"(?:v=|youtu\.be/|list=)([\w-]{6,})", u)
    return m.group(1) if m else re.sub(r"^https?://(www\.)?|[?#].*$|/$", "", u)


def reported_urls(conn=None):
    """Ключи ссылок, на которые жаловались (кэш в памяти; сбрасывается при новой жалобе)."""
    global _REPORTED
    if _REPORTED is None:
        own = conn is None
        conn = conn or A.db_connect()
        try:
            _rep_table(conn)
            _REPORTED = {_url_key(r[0]): r[1] for r in conn.execute("SELECT url, reason FROM source_reports WHERE url<>''")}
        finally:
            if own:
                conn.close()
    return _REPORTED


def is_reported(url):
    with contextlib.suppress(Exception):
        _bind()
        r = reported_urls().get(_url_key(url))
        return REPORT_REASONS.get(r) if r else None
    return None


def report_source(conn, pid, p):
    global _REPORTED
    _bind()
    reason = p.get("reason") if p.get("reason") in REPORT_REASONS else "other"
    url, key, iid = _s(p.get("url"), 600), _s(p.get("src_key"), 200), _s(p.get("item_id"), 200)
    if not url and iid:                      # книга библиотеки: жалоба на её собственную запись
        full = A.get_items(conn, ids=[iid], full=True)
        url = ((full[0].get("urls") or [""])[0]) if full else ""
    if not url and key:
        r = conn.execute("SELECT url FROM src_items WHERE source_id=?", (key,)).fetchone()
        url = r[0] if r else ""
    if not (url or iid):
        raise ValueError("Не на что жаловаться: нет ссылки")
    with A._WRITE_LOCK, A._tx(conn):
        _rep_table(conn)
        conn.execute("INSERT INTO source_reports(profile_id,url,src_key,item_id,author,title,reason,note,created) "
                     "VALUES(?,?,?,?,?,?,?,?,?)", (pid, url, key, iid, _s(p.get("author"), 200), _s(p.get("title"), 300),
                                                   reason, _s(p.get("note"), 500), _now()))
        if url and conn.execute("SELECT 1 FROM sqlite_master WHERE name='src_items'").fetchone():
            if reason == "members":
                conn.execute("UPDATE src_items SET availability='members' WHERE url=?", (url,))
            elif reason in ("partial", "wrong", "broken"):
                conn.execute("UPDATE src_items SET complete_score=0, complete_notes=? WHERE url=?",
                             ("жалоба: " + REPORT_REASONS[reason], url))
    _REPORTED = None
    with contextlib.suppress(Exception):
        import abook_memory as MEM   # noqa: PLC0415
        MEM.log_event(conn, pid, "жалоба", f"{_s(p.get('author'), 200)} — «{_s(p.get('title'), 300)}»: {REPORT_REASONS[reason]}"
                      + (f" ({_s(p.get('note'), 300)})" if p.get("note") else ""))
    out = {"ok": True, "message": "Спасибо — запись больше не предлагается (" + REPORT_REASONS[reason] + ")"}
    if p.get("find_other"):
        a, t = _s(p.get("author"), 200), _s(p.get("title"), 300)
        if t:
            out["search_id"] = F.start_search(conn, pid, f"{a} — {t}" if a else t, auto=False)
            out["message"] += " · ищу другую запись"
    return out


def best_link(conn, iid="", author="", title=""):
    """Ссылка на источник без скачивания: своя запись книги, если она не только для спонсоров, иначе лучшая
    открытая запись из каталога источников."""
    _bind()
    if iid:
        full = A.get_items(conn, ids=[iid], full=True)
        if full:
            author, title = full[0]["author"], full[0]["title"]
            urls = full[0].get("urls") or []
            if urls and not _members_only(conn, full[0]) and not is_reported(urls[0]):
                return {"url": urls[0], "source": "запись библиотеки", "parts": len(urls)}
    with contextlib.suppress(Exception):
        import abook_catalog as C   # noqa: PLC0415
        for x in C.search(conn, f"{author} {title}".strip(), limit=8)[0]:
            if x.get("availability") != "members" and not x.get("drop") and not is_reported(x.get("link") or x.get("url")):
                return {"url": x.get("link") or x.get("url"), "source": x.get("platform") or x.get("source"),
                        "duration": x.get("duration")}
    return {"url": None}


def _act_kick():
    global _ATHREAD
    with _ALOCK:
        if not (_ATHREAD and _ATHREAD.is_alive()):
            _ATHREAD = threading.Thread(target=_act_worker, daemon=True, name="abook-rec-actions")
            _ATHREAD.start()
    _AWAKE.set()


def _act_step(conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM rec_actions WHERE state IN ('search','download')")]
    if not rows:
        return False
    queue = F.queue_payload(conn)
    for r in rows:
        st, msg, key, iid = r["state"], r["message"], r["dl_key"], r["item_id"]
        if st == "search":
            s = conn.execute("SELECT status, result FROM find_searches WHERE id=?", (r["search_id"],)).fetchone()
            e = next((x for x in queue if x.get("search_id") == r["search_id"]), None)
            if e:
                st, key, iid, msg = "download", e["key"], e["item_id"], "Скачиваю"
            elif not s or s["status"] in ("error", "cancelled"):
                st, msg = "failed", "поиск не удался"
            elif s["status"] == "done":
                res = json.loads(s["result"] or "{}")
                lib = res.get("library") or {}
                if lib.get("state") == "downloaded" and (lib.get("item") or {}).get("id"):
                    iid = lib["item"]["id"]
                    st, msg = _apply_now(conn, r["profile_id"], r["action"], iid)
                elif time.time() - _SEEN.setdefault(r["id"], time.time()) > 12:   # автозагрузка так и не встала
                    st, msg = "choose", "есть варианты — выберите запись" if res.get("candidates") else "полной записи не нашлось"
        if st == "download":
            e = next((x for x in queue if x["key"] == key), None)
            if not e:
                st, msg = "failed", "загрузка пропала из очереди"
            elif e["state"] == "done" and e.get("has_file"):
                iid = e["item_id"]
                st, msg = _apply_now(conn, r["profile_id"], r["action"], iid)
            elif e["state"] in ("error", "cancelled"):
                m = e.get("message") or e["state"]
                st, msg = "failed", "только для спонсоров канала — нужна другая запись" if "members-only" in m else "загрузка: " + m
        if (st, msg, key, iid) != (r["state"], r["message"], r["dl_key"], r["item_id"]):
            with A._WRITE_LOCK, A._tx(conn):
                conn.execute("UPDATE rec_actions SET state=?, message=?, dl_key=?, item_id=?, updated=? WHERE id=?",
                             (st, msg, key, iid, _now(), r["id"]))
    return True


def _act_worker():
    conn = A.db_connect()
    try:
        while True:
            try:
                if not _act_step(conn):
                    return
            except Exception as ex:
                A.log(f"WARN: abook_links: отложенное действие: {ex}")
            _AWAKE.wait(4)
            _AWAKE.clear()
    finally:
        conn.close()


def _act_for(conn, pid):
    _act_table(conn)
    rows = [dict(r) for r in conn.execute("SELECT * FROM rec_actions WHERE profile_id=? ORDER BY id DESC LIMIT 200", (pid,))]
    if any(r["state"] in ACT_LIVE for r in rows):
        _act_kick()
    return rows


def _attach_fb(r, fbs):
    r["fb"] = next((f["verdict"] for f in fbs if (r.get("id") and f["item_id"] == r["id"])
                    or F.same_book(f["author"] or "", f["title"] or "", r.get("author") or "", r.get("title") or "")), None)
    return r


def _attach_acts(r, acts):
    r["act"] = {}
    for x in acts:
        if x["action"] in r["act"]:
            continue
        if (r.get("id") and x["item_id"] == r["id"]) or F.same_book(x["author"], x["title"], r.get("author") or "", r.get("title") or ""):
            r["act"][x["action"]] = {k: x[k] for k in ("state", "message", "search_id", "item_id")}
    return r


# ------------------------------------------------------------------ HTTP

def handle_get(h, conn, p, arg):
    _bind()
    pid = A._pid()
    if p == "/api/find/chat":
        return h._json(chat_payload(conn, pid, int(arg("session") or 0) or None))
    if p == "/api/find/link":
        return h._json(best_link(conn, arg("id") or "", arg("author") or "", arg("title") or ""))
    if p == "/api/llm":
        import abook_llm as LLM   # noqa: PLC0415
        return h._json(LLM.status())
    if p == "/api/setup":
        import abook_setup as SU   # noqa: PLC0415
        return SU.handle_get(h, conn)
    if p == "/api/sync":
        import abook_sync as SY   # noqa: PLC0415
        return h._json(SY.status())
    if p == "/api/find/chat/live":
        return h._json(live_payload(pid))
    if p == "/api/find/map":
        return h._json(map_status(conn))
    if p == "/api/find/links":
        return h._json(links_payload(conn, arg("id")))
    if p in ("/api/find/assoc", "/api/find/assoc/status"):       # граф ассоциаций — abook_assoc.py
        import abook_assoc as AS   # noqa: PLC0415
        return AS.handle_get(h, conn, p, arg)
    if p == "/api/find/memory":
        return h._json({"memory": memory_list(conn, pid)})
    if p in ("/api/find/hybrid", "/api/find/foryou", "/api/find/vec/status", "/api/find/feedback",
             "/api/find/quality/status"):     # векторы и гибрид — abook_vec.py, модель вкуса — abook_rank.py
        import abook_vec as V   # noqa: PLC0415
        return V.handle_get(h, conn, p, arg, pid)
    return h._json({"error": "not found"}, 404)


def handle_post(h, conn, p, payload):
    _bind()
    pid = A._pid()
    if p == "/api/find/chat":
        return h._json(chat_send(conn, pid, int(payload.get("session_id") or 0) or None, payload.get("text"),
                                 payload.get("distance") or 0, payload.get("surprise"), incognito=bool(payload.get("incognito")),
                                 count=payload.get("count") or 0))
    if p == "/api/llm":
        import abook_llm as LLM   # noqa: PLC0415
        return h._json(LLM.set_provider(str(payload.get("provider") or "")))
    if p == "/api/setup":
        import abook_setup as SU   # noqa: PLC0415
        return SU.handle_post(h, conn, payload)
    if p == "/api/sync":
        import abook_sync as SY   # noqa: PLC0415
        return h._json(SY.sync(conn, create=payload.get("op") == "enable"))
    if p == "/api/find/vault":
        import abook_vault as VT   # noqa: PLC0415
        return h._json(VT.import_memory(conn, pid) if payload.get("op") == "import" else VT.export(conn, pid))
    if p == "/api/find/report":
        return h._json(report_source(conn, pid, payload))
    if p == "/api/find/act":
        return h._json(rec_action(conn, pid, payload))
    if p == "/api/find/chat/regen":
        return h._json(chat_regen(conn, pid, int(payload.get("session_id") or 0)))
    if p == "/api/find/chat/edit":
        return h._json(chat_edit(conn, pid, int(payload.get("session_id") or 0), int(payload.get("message_id") or 0),
                                 payload.get("text"), payload.get("distance") or 0, payload.get("surprise"),
                                 payload.get("count") or 0))
    if p == "/api/find/chat/rename":
        return h._json(chat_rename(conn, pid, int(payload.get("session_id") or 0), payload.get("title")))
    if p == "/api/find/chat/cancel":
        return h._json({"ok": chat_cancel(pid)})
    if p == "/api/find/chat/delete":
        sid = int(payload.get("session_id") or 0)
        with A._WRITE_LOCK, A._tx(conn):
            if conn.execute("SELECT 1 FROM chat_sessions WHERE id=? AND profile_id=?", (sid, pid)).fetchone():
                conn.execute("DELETE FROM chat_messages WHERE session_id=?", (sid,))
                conn.execute("DELETE FROM chat_sessions WHERE id=?", (sid,))
        return h._json({"ok": True})
    if p == "/api/find/memory":
        return h._json(memory_op(conn, pid, payload))
    if p == "/api/find/feedback":
        with contextlib.suppress(Exception):
            import abook_vec as V   # noqa: PLC0415
            V.foryou_reset(pid)                    # реакция меняет вкус — «Для вас» пересчитать
        with contextlib.suppress(Exception):
            import abook_memory as MEM   # noqa: PLC0415
            v = {"like": "нравится", "dislike": "не моё", "read": "уже читал", "none": "снял отметку"}.get(payload.get("verdict"), "")
            MEM.log_event(conn, pid, "реакция", f"{_s(payload.get('author'), 200)} — «{_s(payload.get('title'), 300)}»: {v}")
    if p == "/api/find/feedback" and payload.get("verdict") == "none":   # снять реакцию (повторное нажатие)
        a_, t_, iid_ = _s(payload.get("author"), 200), _s(payload.get("title"), 300), _s(payload.get("item_id"), 200)
        with A._WRITE_LOCK, A._tx(conn):
            for r in conn.execute("SELECT id, author, title, item_id FROM rec_feedback WHERE profile_id=?", (pid,)).fetchall():
                if (iid_ and r[3] == iid_) or (t_ and F.same_book(a_, t_, r[1] or "", r[2] or "")):
                    conn.execute("DELETE FROM rec_feedback WHERE id=?", (r[0],))
        with contextlib.suppress(Exception):
            import abook_rank as R   # noqa: PLC0415
            R._PROFILE.pop(pid, None)
        return h._json({"ok": True, "verdict": None})
    if p == "/api/find/feedback":          # реакция на совет 👍/👎/«читал» — модель вкуса (abook_rank.py)
        import abook_rank as R   # noqa: PLC0415
        return R.handle_post(h, conn, p, payload, pid)
    if p == "/api/find/map":
        if payload.get("op") == "cancel":
            return h._json({"ok": cancel_map()})
        return h._json(start_map(conn, only_missing=payload.get("all") is not True, max_batches=payload.get("max_batches")))
    return h._json({"error": "not found"}, 404)
