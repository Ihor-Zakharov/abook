"""abook_catalog — «Каталог источников»: локальный индекс НЕскачанных аудиокниг из больших открытых источников,
чтобы поиск по ним был мгновенным. Иерархия поиска во вкладке «Найти»:
  L0 библиотека (abook_find.library_match) → L1 этот каталог (FTS5, миллисекунды) → L2 live-поиск по площадкам
  (abook_find._run_platforms) → L3 ИИ с WebSearch (Claude/Antigravity).

Что в индексе (таблица `src_items` в library.db + `src_fts`, FTS5 tokenize='trigram'):
  • YouTube-каналы из ~/abook/sources.json (по умолчанию — Олег Булдаков и «Шарков - Аудіокниги Українською»):
    yt-dlp `--flat-playlist -J` по /videos и /playlists. Заголовки «Автор - Название. Часть 1/2. Аудиокнига.
    Читает …» разбираются; части отдельными видео склеиваются в одну запись kind=parts (проверка непрерывности
    номеров). Только для спонсоров (`availability` = subscriber_only/premium_only/needs_auth в flat-записи, пометка
    «(спонсорський)» в названии плейлиста) хранится с availability=members и в выдачу не попадает. Если в flat-записи
    поля нет — availability=unknown, кандидат проверяется `-J` перед показом (probe_cached, кэш 7 дней).
  • Готовые манифесты (F-buldakov.json) — импорт без сети при старте.
  • knigavuhe.org и akniga.org — поиск по запросу на лету (их HTML-поиск), результат кэшируется в src_items,
    запрос — в src_queries (TTL 14 дней). knigavuhe: yt-dlp сайт не знает, но страница книги содержит
    `new BookPlayer(id, [треки])` с прямыми mp3 — их и отдаём в `abook get` (как файлы archive.org).
    akniga: плеер зашифрован (AES в JS), yt-dlp не берёт — только подсказка «есть такая запись», не скачивается.
  • Широкий каталог (Этап 2): полный вежливый обход knigavuhe (лента /new/), akniga (лента /index/ + sitemap для
    «дыр»; только ссылка), archive.org (scrape API: русские/украинские аудио + LibriVox) — метаданные, аннотация
    ≤ 400 символов (для векторов), курсор в src_crawls (возобновляемо), инкремент — «голова» ленты / publicdate.
    Каналы YouTube, которые ≥ 3 раз дали прошедшую проверку запись в живом поиске, сами добавляются (learn_channels).
  • Украинские источники: 20 каналов YouTube (lang=uk в sources.json; yt-dlp с youtube:lang=<lang>, иначе YouTube
    отдаёт автоперевод заголовков) и 4read.org (crawl_4read: sitemap -> карточки; mp3/HLS на reasd.org только с
    Referer 4read). Язык записи — lang_guess (і/ї/є/ґ во всём слове кириллицей, маркеры «аудіокнига», «читає»).
  • Произведения (works): записи склеиваются по скелету названия + автору (rebuild_works), src_items.work_id;
    поиск search_works (GET /api/find/catalog?group=work). CLI: python3 abook_catalog.py crawl --db <база>.
Краулинг — фоновый поток, по одному источнику, отменяемый (SIGTERM yt-dlp), с прогрессом (crawl_status).
Инкрементально: если 60 свежих видео канала уже все известны — полный список не тянется; иначе полный (≈ 30 с на
2000 видео). TTL источника — `ttl_days` в sources.json (3 дня).

Нормализация для матча: нижний регистр, ё→е, укр. і/ї→и, є→е, ґ→г, й→и, апострофы прочь. Запрос — слова ≥ 3
букв, длинные обрезаются до основы (окончания), AND по трёхграммам; ранжирование — доля слов запроса в
«автор + название», затем доступность и полнота.

Переменные: ABOOK_CATALOG_AUTO=0 — не краулить при старте сервера (в тестовом режиме и при ABOOK_FIND_NO_NET
не краулит и так); ABOOK_SOURCES=<файл> — другой sources.json.
"""
import contextlib
import functools
import hashlib
import html as _html
import json
import math
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import abook_find as F

PROBE_TTL = 7 * 86400
SITE_TTL = 14 * 86400
MEMBERS = ("subscriber_only", "premium_only", "needs_auth")
_SPONSOR = re.compile(r"спонсор|для спонсор|members only|only for members|для учасник|для участник", re.I)

DEFAULT_SOURCES = {
    "_about": ("Источники «Каталога источников» (abook_catalog.py). youtube: каналы, краулятся yt-dlp по вкладкам "
               "tabs; reader — чтец по умолчанию (если в заголовке не указан); ttl_days — как часто обновлять. "
               "manifests: готовые манифесты, импортируются без сети. sites: поиск на лету с кэшем."),
    "youtube": [
        {"id": "buldakov", "name": "Олег Булдаков | BLACKWOOD", "handle": "@ОлегБулдаков-ы5ш",
         "url": "https://www.youtube.com/channel/UC67qJmazjlqYCfGIiAVVXRQ", "reader": "Олег Булдаков",
         "lang": "ru", "tabs": ["videos", "playlists"], "ttl_days": 3},
        {"id": "sharkov", "name": "Шарков - Аудіокниги Українською", "handle": "@Sharkov0202",
         "url": "https://www.youtube.com/channel/UCBXu2JI9xvaDdBAYcA20D4g", "reader": "Шарков",
         "lang": "uk", "tabs": ["videos", "playlists"], "ttl_days": 3},
    ],
    "manifests": [{"id": "manifest:F-buldakov", "path": "manifests/F-buldakov.json", "platform": "YouTube",
                   "channel": "Олег Булдаков | BLACKWOOD"}],
    "sites": {"knigavuhe": {"ttl_days": 14}, "akniga": {"ttl_days": 14}},
}

_TABLES = """
CREATE TABLE IF NOT EXISTS src_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL UNIQUE, src TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '', url TEXT NOT NULL, urls TEXT NOT NULL DEFAULT '[]', channel TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', work TEXT NOT NULL DEFAULT '',
  reader TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT '', duration_s REAL, parts INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL DEFAULT 'single', availability TEXT NOT NULL DEFAULT 'unknown', downloadable INTEGER NOT NULL DEFAULT 1,
  complete_score REAL, complete_notes TEXT NOT NULL DEFAULT '', views INTEGER, fetched_at TEXT, checked_at TEXT, raw TEXT);
CREATE INDEX IF NOT EXISTS src_items_src ON src_items(src);
CREATE VIRTUAL TABLE IF NOT EXISTS src_fts USING fts5(norm, tokenize='trigram');
CREATE TABLE IF NOT EXISTS src_crawls(source TEXT PRIMARY KEY, fetched_at TEXT, n INTEGER, members INTEGER,
  error TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS src_queries(site TEXT NOT NULL, qnorm TEXT NOT NULL, fetched_at REAL NOT NULL, n INTEGER,
  PRIMARY KEY(site, qnorm));
CREATE TABLE IF NOT EXISTS probe_cache(key TEXT PRIMARY KEY, at REAL NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS works(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wkey TEXT NOT NULL UNIQUE, author TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', alt_titles TEXT NOT NULL DEFAULT '[]', n_records INTEGER NOT NULL DEFAULT 0,
  n_public INTEGER NOT NULL DEFAULT 0, best_record INTEGER, langs TEXT NOT NULL DEFAULT '',
  annotation TEXT NOT NULL DEFAULT '', genre TEXT NOT NULL DEFAULT '', readers TEXT NOT NULL DEFAULT '',
  duration_s REAL, updated_at TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS works_fts USING fts5(norm, tokenize='trigram');
CREATE TABLE IF NOT EXISTS src_sitemap(site TEXT NOT NULL, url TEXT NOT NULL, lastmod TEXT, seen_at TEXT,
  PRIMARY KEY(site, url));
"""
_NEED = {"src_items", "src_fts", "src_crawls", "src_queries", "probe_cache", "works", "works_fts", "src_sitemap"}
# Колонки, добавленные к src_items «широким каталогом» (Этап 2) — ALTER TABLE на старых базах. На них опираются
# векторы/RAG (abook_links): annotation ≤ 400 символов — текст для эмбеддинга, work_id -> works.id.
_ADD_COLS = (("genre", "TEXT NOT NULL DEFAULT ''"), ("tags", "TEXT NOT NULL DEFAULT ''"),
             ("annotation", "TEXT NOT NULL DEFAULT ''"), ("series", "TEXT NOT NULL DEFAULT ''"),
             ("lastmod", "TEXT"), ("work_id", "INTEGER"))


def A():
    return F.A


def _now():
    return F._now()


# ------------------------------------------------------------------ нормализация и разбор заголовков

_TR = str.maketrans({"ё": "е", "і": "и", "ї": "и", "є": "е", "ґ": "г", "й": "и", "ъ": "ь", "'": "", "’": "", "ʼ": "",
                     "`": ""})


_FOLD = str.maketrans({"ы": "и", "э": "и", "е": "и"})


def fold(s):
    """Грубая свёртка рус/укр для матча: тени/тіні, предков/предків -> одно написание."""
    return norm(s).translate(_FOLD)


def norm(s):
    s = str(s or "").lower().translate(_TR)
    s = re.sub(r"[^\w]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_PART = re.compile(r"[\s.,:;(\[\-–—]*\b(?:часть|частина|ч\.|part|глава|розділ|серия|серія)\s*(\d{1,3})"
                   r"(?:\s*(?:/|из|з|of)\s*(\d{1,3}))?[)\]]?", re.I)
_PART_TAIL = re.compile(r"[\s.,(\[\-–—]+(\d{1,2})\s*/\s*(\d{1,2})[)\]]?\s*$")
_NOISE = re.compile(r"(?:^|[\s.,|(\[])(?:полная\s+)?(?:аудио\s?книга|аудіокнига|аудиокнига|audiobook|аудіо|"
                    r"аудиоспектакль|радиоспектакль)(?:\s+полностью)?\b[)\]]?", re.I)
_READ = re.compile(r"[.,(\[|\s-]*(?:читает|читає|чтец|читал[аи]?|читають|читают|read by|narrated by)\s*[:\-–—]?\s*"
                   r"([^.()\[\]|#]{3,60})", re.I)


def parse_title(t, default_reader=""):
    """«Автор - Название. Часть 1/2. Аудиокнига. Читает …» -> {author, work, reader, part, of, members}."""
    raw = str(t or "")
    s = re.sub(r"#\S+", " ", raw)
    out = {"author": "", "work": "", "reader": "", "part": None, "of": None, "members": bool(_SPONSOR.search(raw))}
    m = _READ.search(s)
    if m:
        out["reader"] = m.group(1).strip(" .,-–—")
        s = s[:m.start()] + " " + s[m.end():]
    m = _PART.search(s) or _PART_TAIL.search(s)
    if m:
        out["part"], out["of"] = int(m.group(1)), (int(m.group(2)) if m.group(2) else None)
        s = s[:m.start()] + " " + s[m.end():]
    s = _NOISE.sub(" ", s)
    s = re.sub(r"\((?:спонсорськ\w*|спонсорск\w*)\)", " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" .,|-–—")
    mm = re.match(r"(.{3,80}?)\s+[-–—]\s+(.+)$", s) or re.match(r"(.{3,80}?)\s*[:|]\s+(.+)$", s)
    if mm and not re.match(r"^\s*#?\d", mm.group(1)):
        out["author"], out["work"] = mm.group(1).strip(" .,«»\""), mm.group(2).strip(" .,«»\"")
    elif mm:                                  # «#1 Джеймс Герберт - Пацюки»: номер в цикле
        out["author"] = re.sub(r"^\s*#?\d+\s*", "", mm.group(1)).strip(" .,")
        out["work"] = mm.group(2).strip(" .,«»\"")
    else:
        out["work"] = s.strip(" .,«»\"")
    if not out["author"] or re.search(r'[«»"“”]', out["author"]) or re.match(r'\s*[«"“„]', out["work"]):
        _quoted_or_caps(s, out)
    out["work"] = re.sub(r"\s*[.,]\s*(?:цикл|серия|серія)\b.*$", "", out["work"], flags=re.I).strip(" .,") or out["work"]
    out["reader"] = out["reader"] or default_reader
    return out


# Форматы украинских каналов: «Леонід Данільчик "МАШИНА НА КОНТРОЛІ"», «"Чорне Сонце", Василь Шкляр»,
# «Детектив «Часова пастка» | Міріам Аллен де Форд», «Генрі Слезар СУСІД У КАМЕРІ» (автор обычным регистром,
# название капсом). Автор — сегмент из 2–4 слов с заглавной буквы (не капсом: капсом пишут жанр/рубрику).
_UPW = r"[A-ZА-ЯЁІЇЄҐ][a-zа-яёіїєґ'’.\-]+"
_NAME = re.compile(rf"^(?:{_UPW}\s+){{1,3}}{_UPW}$|^{_UPW}$")
_QUOTED = re.compile(r'«([^»]{2,90})»|"([^"]{2,90})"|“([^”]{2,90})”|„([^“”]{2,90})[“”]')
_NAME_CAPS = re.compile(rf"^((?:{_UPW}\s+){{1,3}}{_UPW})\s+([A-ZА-ЯЁІЇЄҐ0-9][A-ZА-ЯЁІЇЄҐ0-9\s'’,.!?\-]{{2,}})$")
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]+")


def _quoted_or_caps(s, out):
    s = _EMOJI.sub(" ", s)
    q = _QUOTED.search(s)
    if q:
        work = next(g for g in q.groups() if g).strip(" .,")
        rest = s[:q.start()] + " | " + s[q.end():]
        names = [x.strip(" .,!") for x in re.split(r"\s*[|,–—]\s*|\s+-\s+|\(|\)", rest)]
        names = [x for x in names if _NAME.match(x) and not re.search(r"українськ|аудіо|аудио|повністю|читає", x, re.I)]
        if names:
            out["author"] = names[0]
        out["work"] = work
        return
    m = _NAME_CAPS.match(re.sub(r"\s+", " ", s).strip(" .,|-–—\""))
    if m and not out["author"]:
        out["author"], out["work"] = m.group(1), m.group(2).strip(" .,")


def _clean_work(work, channel):
    """Хвосты « - Аудіокниги Українською - Шарков»: отрезать сегменты, состоящие из слов названия канала."""
    ch = set(norm(channel).split()) | {"аудиокниги", "аудиокнига", "украинською", "украинском", "на", "полностью"}
    segs = re.split(r"\s+[-–—|]\s+", work)
    while len(segs) > 1 and set(norm(segs[-1]).split()) <= ch:
        segs.pop()
    return " - ".join(segs).strip(" .,")


# ------------------------------------------------------------------ схема

def _ensure_cols(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(src_items)")}
    miss = [(c, t) for c, t in _ADD_COLS if c not in cols]
    if miss:
        with A()._WRITE_LOCK:
            for c, t in miss:
                conn.execute(f"ALTER TABLE src_items ADD COLUMN {c} {t}")
    conn.execute("CREATE INDEX IF NOT EXISTS src_items_work ON src_items(work_id)")


def migrate(conn):
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    if not (_NEED - have):
        _ensure_cols(conn)
        return None
    backup = None
    with contextlib.suppress(Exception):
        d = A().db_backups_dir()
        d.mkdir(parents=True, exist_ok=True)
        backup = d / f"library-pre-catalog-{datetime.now():%Y%m%d-%H%M%S}.db"
        conn.execute("VACUUM INTO ?", (str(backup),))
    try:
        with A()._WRITE_LOCK:
            conn.executescript(_TABLES)
    except sqlite3.OperationalError:          # sqlite без trigram — запасной токенизатор, матч по префиксам
        with A()._WRITE_LOCK:
            conn.executescript(_TABLES.replace("tokenize='trigram'", "tokenize='unicode61 remove_diacritics 2'"))
    _ensure_cols(conn)
    return backup


def _trigram(conn):
    r = conn.execute("SELECT sql FROM sqlite_master WHERE name='src_fts'").fetchone()
    return bool(r and "trigram" in (r[0] or ""))


def sources_file():
    return Path(os.environ.get("ABOOK_SOURCES") or (A().ABOOK_DIR / "sources.json"))


def load_sources():
    p = sources_file()
    d = F._load_json(p)
    if not isinstance(d, dict):
        d = json.loads(json.dumps(DEFAULT_SOURCES))
        with contextlib.suppress(OSError):
            F._atomic_json(p, d)
    for k, v in DEFAULT_SOURCES.items():
        d.setdefault(k, v)
    return d


# ------------------------------------------------------------------ запись в индекс

def _fts_text(r):
    return fold(" ".join(str(r.get(k) or "") for k in ("author", "work", "title", "reader", "channel")))


def upsert(conn, rows):
    """rows: dict с полями src_items. Ручные поля из манифеста (author/work/reader) не затираются краулом."""
    if not rows:
        return 0
    with A()._WRITE_LOCK, A()._tx(conn):
        for r in rows:
            r.setdefault("fetched_at", _now())
            old = conn.execute("SELECT id, src, author, work, reader, complete_notes, genre, tags, annotation, series "
                               "FROM src_items WHERE source_id=?", (r["source_id"],)).fetchone()
            if old:                     # догруженное лениво (аннотация с карточки и т. п.) пустым не затираем
                for k in ("genre", "tags", "annotation", "series"):
                    if not r.get(k):
                        r[k] = old[k]
            if old and old["src"].startswith("manifest:") and not r["src"].startswith("manifest:"):
                for k in ("author", "work", "reader"):
                    r[k] = old[k] or r.get(k)
                r["src"] = old["src"]
            cols = ["source_id", "src", "platform", "url", "urls", "channel", "title", "author", "work", "reader",
                    "lang", "duration_s", "parts", "kind", "availability", "downloadable", "complete_score",
                    "complete_notes", "views", "fetched_at", "raw", "genre", "tags", "annotation", "series", "lastmod"]
            vals = [r.get(c) for c in cols]
            vals[cols.index("urls")] = json.dumps(r.get("urls") or [r["url"]], ensure_ascii=False)
            vals[cols.index("raw")] = json.dumps(r.get("raw"), ensure_ascii=False)[:20000] if r.get("raw") is not None else None
            for c, dflt in (("availability", "unknown"), ("kind", "single"), ("parts", 1), ("downloadable", 1),
                            ("complete_notes", ""), ("lang", ""), ("channel", ""), ("title", ""), ("author", ""),
                            ("work", ""), ("reader", ""), ("platform", ""), ("genre", ""), ("tags", ""),
                            ("annotation", ""), ("series", "")):
                if vals[cols.index(c)] is None:
                    vals[cols.index(c)] = dflt
            if old:
                conn.execute(f"UPDATE src_items SET {', '.join(c + '=?' for c in cols[1:])} WHERE id=?",
                             vals[1:] + [old["id"]])
                rid = old["id"]
                conn.execute("DELETE FROM src_fts WHERE rowid=?", (rid,))
            else:
                rid = conn.execute(f"INSERT INTO src_items({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                   vals).lastrowid
            conn.execute("INSERT INTO src_fts(rowid, norm) VALUES(?,?)", (rid, _fts_text(r)))
    return len(rows)


def _drop_ids(conn, sids):
    if not sids:
        return
    with A()._WRITE_LOCK, A()._tx(conn):
        for s in sids:
            r = conn.execute("SELECT id FROM src_items WHERE source_id=?", (s,)).fetchone()
            if r:
                conn.execute("DELETE FROM src_fts WHERE rowid=?", (r[0],))
                conn.execute("DELETE FROM src_items WHERE id=?", (r[0],))


# ------------------------------------------------------------------ полнота без скачивания

def completeness(r):
    """(score 0..1 | None, notes) по данным списка: части, пропуски номеров, длительность, спонсорство."""
    notes, score = [], 1.0
    if r.get("availability") == "members":
        return 0.0, "только для спонсоров канала — скачать нельзя"
    if r.get("kind") == "parts":
        nums = r.get("_nums") or []
        of = r.get("_of")
        if nums:
            want = list(range(1, max(max(nums), of or 0) + 1))
            miss = [n for n in want if n not in nums]
            if miss:
                score -= 0.5
                notes.append("нет частей: " + ", ".join(map(str, miss[:8])))
            if len(set(nums)) != len(nums):
                score -= 0.2
                notes.append("номера частей повторяются")
            if r.get("_members_parts"):
                score = 0.0
                notes.append(f"частей только для спонсоров: {r['_members_parts']}")
    if r.get("kind") == "single" and r.get("_part"):
        score -= 0.5
        notes.append(f"отдельная часть {r['_part']}" + (f" из {r['_of']}" if r.get("_of") else "") + " — остальных нет в списке")
    d = r.get("duration_s")
    if r.get("kind") == "playlist" and not d:
        return None, "плейлист — состав проверяется при поиске"
    if d is None:
        notes.append("длительность неизвестна")
        score -= 0.1
    elif d < 600:
        score -= 0.6
        notes.append(f"очень коротко ({d / 60:.0f} мин) — фрагмент/анонс?")
    elif d < 1800:
        notes.append(f"короткая запись ({d / 60:.0f} мин) — рассказ или фрагмент")
    if F._JUNK.search(r.get("title") or ""):
        score -= 0.5
        notes.append("похоже на анонс/обзор")
    return round(max(0.0, score), 2), "; ".join(notes)


def cross_check(conn):
    """Сверка длительностей одной книги в разных записях: заметно короче лучшей — пометка (и минус к полноте)."""
    groups = {}
    for r in conn.execute("SELECT id, author, work, duration_s, complete_score, complete_notes FROM src_items "
                          "WHERE duration_s>0 AND work<>'' AND availability<>'members'"):
        groups.setdefault((norm(r["author"]).split(" ")[-1:][0] if r["author"] else "", norm(r["work"])), []).append(r)
    upd = []
    for g in groups.values():
        if len(g) < 2:
            continue
        mx = max(r["duration_s"] for r in g)
        for r in g:
            note = re.sub(r";? ?короче других записей[^;]*", "", r["complete_notes"] or "").strip("; ")
            sc = r["complete_score"]
            if r["duration_s"] < 0.75 * mx:
                note = (note + "; " if note else "") + f"короче других записей этой книги ({r['duration_s'] / 3600:.1f} " \
                                                        f"ч против {mx / 3600:.1f} ч)"
                sc = round(max(0.0, (sc if sc is not None else 1.0) - 0.3), 2)
            if note != (r["complete_notes"] or "") or sc != r["complete_score"]:
                upd.append((sc, note, r["id"]))
    if upd:
        with A()._WRITE_LOCK, A()._tx(conn):
            conn.executemany("UPDATE src_items SET complete_score=?, complete_notes=? WHERE id=?", upd)
    return len(upd)


# ------------------------------------------------------------------ импорт манифестов (без сети)

def import_manifests(conn):
    n = 0
    for m in load_sources().get("manifests") or []:
        p = Path(m.get("path") or "")
        if not p.is_absolute():
            p = A().ABOOK_DIR / p
        d = F._load_json(p)
        if not isinstance(d, dict):
            continue
        st = p.stat().st_mtime
        prev = conn.execute("SELECT meta FROM src_crawls WHERE source=?", (m["id"],)).fetchone()
        if prev and (json.loads(prev[0] or "{}").get("mtime") == st):
            continue
        rows = []
        for it in d.get("items") or []:
            urls = [u for u in (it.get("urls") or []) if isinstance(u, str)]
            if not urls:
                continue
            r = {"source_id": F._key(urls[0]), "src": m["id"], "platform": m.get("platform") or F.platform_of(urls[0]),
                 "url": urls[0], "urls": urls, "channel": m.get("channel") or it.get("source") or "",
                 "title": f"{it.get('author', '')} — {it.get('title', '')}", "author": it.get("author") or "",
                 "work": it.get("title") or "", "reader": it.get("narrator") or "", "lang": it.get("lang") or "",
                 "duration_s": float(it["duration_h"]) * 3600 if it.get("duration_h") else None,
                 "parts": len(urls), "kind": "parts" if len(urls) > 1 else "single", "availability": "unknown",
                 "raw": {"manifest": p.name, "id": it.get("id"), "kind": it.get("kind"), "quality": it.get("quality")}}
            if it.get("kind") == "radioplay":
                r["raw"]["radioplay"] = True
            r["complete_score"], r["complete_notes"] = completeness(r)
            r["complete_notes"] = ("; ".join(x for x in [r["complete_notes"], "из манифеста (проверено при сборке)"] if x))
            rows.append(r)
        upsert(conn, rows)
        n += len(rows)
        with A()._WRITE_LOCK, A()._tx(conn):
            conn.execute("INSERT OR REPLACE INTO src_crawls(source, fetched_at, n, members, error, meta) VALUES(?,?,?,?,?,?)",
                         (m["id"], _now(), len(rows), 0, None, json.dumps({"mtime": st, "path": str(p)})))
    return n


def _video_avail_map(conn):
    """yt-id видео -> availability по данным краула каналов (одиночные и части склеек) и по проверкам."""
    m = {}
    for r in conn.execute("SELECT source_id, availability, kind, raw, src FROM src_items WHERE src NOT LIKE 'manifest:%'"):
        if r["kind"] == "parts":
            with contextlib.suppress(Exception):
                for x in json.loads(r["raw"] or "{}").get("parts") or []:
                    a = x.get("availability")
                    m["yt:" + x["id"]] = "members" if a in MEMBERS else "public" if a in ("public", "unlisted") else \
                        m.get("yt:" + x["id"], "unknown")
        elif r["source_id"].startswith("yt:"):
            m[r["source_id"]] = r["availability"]
    return m


def sync_manifest_availability(conn):
    """Записи из манифестов (и только они) получают доступность по краулу канала: хоть одна часть
    только для спонсоров -> members; все части видны в списке канала без пометки -> public."""
    vm = _video_avail_map(conn)
    upd = []
    for r in conn.execute("SELECT id, urls, availability, complete_notes FROM src_items WHERE src LIKE 'manifest:%'"):
        keys = [F._key(u) for u in json.loads(r["urls"] or "[]")]
        av = [vm.get(k, "unknown") for k in keys]
        new = "members" if "members" in av else "public" if av and all(a == "public" for a in av) else r["availability"]
        if new != r["availability"]:
            notes = r["complete_notes"] or ""
            if new == "members" and "спонсор" not in notes:
                notes = "только для спонсоров канала — скачать нельзя; " + notes
            upd.append((new, notes, 0.0 if new == "members" else None, r["id"]))
    if upd:
        with A()._WRITE_LOCK, A()._tx(conn):
            for av, nt, sc, i in upd:
                conn.execute("UPDATE src_items SET availability=?, complete_notes=?, complete_score=COALESCE(?, complete_score) "
                             "WHERE id=?", (av, nt, sc, i))
    return len(upd)


def availability(url, conn=None, check=True):
    """'public' | 'members' | 'unknown' для ссылки (или первой ссылки книги). Сначала индекс и кэш проверок
    (без сети, мгновенно); если неизвестно и check — `yt-dlp -J` через probe_cached (кэш 7 дней).
    Для чата/карточек: перед кнопкой «Скачать» у книги каталога библиотеки (in_library без файла)."""
    own = conn is None
    conn = conn or A().db_connect()
    try:
        k = F._key(url)
        r = conn.execute("SELECT availability FROM src_items WHERE source_id=? AND availability<>'unknown'", (k,)).fetchone()
        if r:
            return r[0]
        a = _video_avail_map(conn).get(k)
        if a in ("public", "members"):
            return a
        pc = _probe_cached_row(conn, url)
        if pc:
            pr = pc.get("probe") or {}
            return "public" if pr.get("ok") else "members" if "спонсор" in (pr.get("error") or "") else "unknown"
        if not check:
            return "unknown"
    finally:
        if own:
            conn.close()
    c = probe_cached(F._cand(url, "проверка"))
    pr = c.get("probe") or {}
    return "public" if pr.get("ok") else "members" if "спонсор" in (pr.get("error") or "") else "unknown"


# ------------------------------------------------------------------ краулинг YouTube-каналов

_CRAWL = {"running": False, "source": None, "phase": "", "done": 0, "total": 0, "started": None, "finished": None,
          "cancel": False, "proc": None, "log": [], "results": {}, "per": {}}
_CLOCK = threading.Lock()


def _ytdlp_cancellable(args, timeout):
    """yt-dlp как в abook._ytdlp_run (своя копия cookies), но через Popen — отмена убивает процесс."""
    a = A()
    wd = F.workdir()
    cmd = [a.YTDLP_BIN, "--ignore-config", "--no-progress", "--socket-timeout", "20", "--retries", "3",
           "--extractor-retries", "2"]
    node = a._node_bin()
    if node:
        cmd += ["--js-runtimes", f"node:{node}"]
    ck = None
    if a.COOKIES_PATH.is_file() and a.COOKIES_PATH.stat().st_size > 0:
        ck = wd / f".cookies-cat-{os.getpid()}-{threading.get_ident()}.txt"
        shutil.copyfile(a.COOKIES_PATH, ck)
        os.chmod(ck, 0o600)
        cmd += ["--cookies", str(ck)]
    try:
        p = subprocess.Popen(cmd + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             cwd=str(wd), stdin=subprocess.DEVNULL, start_new_session=True)
        _CRAWL["proc"] = p
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                os.killpg(p.pid, signal.SIGKILL)
            p.communicate()
            raise RuntimeError(f"yt-dlp не уложился в {timeout} с")
        finally:
            _CRAWL["proc"] = None
        if _CRAWL["cancel"]:
            raise F.Cancelled()
        if p.returncode != 0 and not out.strip():
            errs = [l for l in err.splitlines() if "ERROR" in l]
            raise RuntimeError((errs[-1] if errs else err.strip()[-300:]) or f"yt-dlp exit {p.returncode}")
        return json.loads(out)
    finally:
        if ck:
            with contextlib.suppress(OSError):
                ck.unlink()


# Язык записи. F._lang_of ловит любую «і» — и в «Davіd X» (латиница с кириллической і), и в белорусском. Здесь:
# украинский — слова целиком кириллицей с і/ї/є/ґ (или маркеры «аудіокнига», «читає», «українською»), и их больше,
# чем «русских» слов с ы/э/ъ/ё; белорусский (ў) — 'be' (вес языка 0). Нужен, чтобы веса ru/uk в выдаче работали.
_UK_MARK = re.compile(r"аудіо\s?книг|читає|читають|українськ|частина|розділ", re.I)
_UK_WORD = re.compile(r"(?<![a-zA-Z])[а-яґєіїʼ'’]*[ґєіїҐЄІЇ][а-яґєіїʼ'’]*(?![a-zA-Z])", re.I)
_RU_WORD = re.compile(r"\b[а-яё]*[ыэъё][а-яё]*\b", re.I)


def lang_guess(*texts, default=""):
    t = " ".join(x for x in texts if x)
    if not t:
        return default
    if re.search(r"[ўЎ]", t):
        return "be"
    uk = len([w for w in _UK_WORD.findall(t) if len(w) > 1 or w.lower() in "іїєґ"]) + 2 * len(_UK_MARK.findall(t))
    ru = len(_RU_WORD.findall(t))
    if uk and uk >= ru:
        return "uk"
    if re.search(r"[а-яё]", t, re.I):
        return "ru"
    return default or "en"


def _avail(e, title=""):
    a = e.get("availability")
    if a in MEMBERS or _SPONSOR.search(title or ""):
        return "members"
    if a in ("public", "unlisted"):
        return "public"
    return "unknown"


def _rows_from_videos(src, ents):
    """Видео канала -> записи; части (Часть 1/2 …) одной книги склеиваются в kind=parts."""
    singles, groups = [], {}
    for e in ents:
        if not e or not e.get("id") or e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        t = e.get("title") or ""
        if F.A._UNAVAILABLE_TITLE.match(t.strip()):
            continue
        p = parse_title(t, src.get("reader") or "")
        p["work"] = _clean_work(p["work"], src.get("name") or "")
        url = f"https://www.youtube.com/watch?v={e['id']}"
        av = _avail(e, t)
        base = {"src": src["id"], "platform": "YouTube", "channel": src.get("name") or "", "title": t,
                "author": p["author"], "work": p["work"], "reader": p["reader"],
                "lang": src.get("lang") or lang_guess(t), "duration_s": e.get("duration"), "views": e.get("view_count"),
                "availability": av, "raw": {"id": e["id"], "availability": e.get("availability"), "dur": e.get("duration")}}
        if p["part"] is not None:
            # спонсорская и открытая версии одного видео (у Шаркова каждое — дважды) — разные группы
            k = (norm(p["author"]), norm(p["work"]), av == "members")
            groups.setdefault(k, []).append((p["part"], p["of"], url, base))
        else:
            singles.append(dict(base, source_id=F._key(url), url=url, urls=[url], parts=1, kind="single"))
    rows = list(singles)
    for (_, _, mem), parts in groups.items():
        parts.sort(key=lambda x: x[0])
        # дубли одного номера (перезалив): берём первую по списку (свежую)
        seen, uniq = set(), []
        for x in parts:
            if x[0] not in seen:
                seen.add(x[0])
                uniq.append(x)
        b = dict(uniq[0][3])
        urls = [x[2] for x in uniq]
        durs = [x[3]["duration_s"] for x in uniq]
        of = max((x[1] or 0) for x in uniq) or None
        r = dict(b, source_id=F._key(urls[0]), url=urls[0], urls=urls, parts=len(urls),
                 kind="parts" if len(urls) > 1 or (of and of > 1) else "single",
                 duration_s=(sum(d for d in durs if d) or None),
                 title=re.sub(r"\s*[.,]?\s*(?:Часть|Частина|Part)\s*\d+(?:\s*/\s*\d+)?", "", b["title"], flags=re.I),
                 views=max((x[3].get("views") or 0) for x in uniq) or None,
                 raw={"parts": [{"n": x[0], "of": x[1], "id": x[3]["raw"]["id"], "dur": x[3]["duration_s"],
                                 "availability": x[3]["raw"]["availability"]} for x in uniq]})
        r["_nums"] = [x[0] for x in parts]
        r["_of"] = of
        r["_members_parts"] = 0 if mem else sum(1 for x in uniq if x[3]["availability"] == "members")
        if r["kind"] == "single":
            r["_part"] = uniq[0][0]
        if None in durs and r["duration_s"]:
            r["complete_notes"] = "длительность известна не для всех частей"
        rows.append(r)
    for r in rows:
        sc, nt = completeness(r)
        r["complete_score"] = sc
        r["complete_notes"] = "; ".join(x for x in [nt, r.get("complete_notes")] if x)
        for k in ("_nums", "_of", "_members_parts", "_part"):
            r.pop(k, None)
    return rows


def _rows_from_playlists(src, ents):
    rows = []
    for e in ents:
        if not e or not e.get("id"):
            continue
        t = e.get("title") or ""
        p = parse_title(t, src.get("reader") or "")
        url = f"https://www.youtube.com/playlist?list={e['id']}"
        r = {"source_id": F._key(url), "src": src["id"], "platform": "YouTube", "url": url, "urls": [url],
             "channel": src.get("name") or "", "title": t, "author": p["author"], "work": p["work"],
             "reader": p["reader"], "lang": src.get("lang") or lang_guess(t), "duration_s": None,
             "parts": e.get("playlist_count") or 0, "kind": "playlist", "availability": _avail(e, t),
             "raw": {"id": e["id"]}}
        if not p["author"] and len(t.split()) <= 3:
            r["complete_notes"] = "подборка автора/рубрики, не одна книга"
        sc, nt = completeness(r)
        r["complete_score"], r["complete_notes"] = sc, "; ".join(x for x in [nt, r.get("complete_notes")] if x)
        rows.append(r)
    return rows


def crawl_channel(conn, src, force=False):
    base = src["url"].rstrip("/")
    known = {r[0] for r in conn.execute("SELECT source_id FROM src_items WHERE src=? OR src LIKE 'manifest:%'",
                                        (src["id"],))}
    stat = {"videos": 0, "playlists": 0, "members": 0, "new": 0, "skipped": False}
    prev = conn.execute("SELECT fetched_at FROM src_crawls WHERE source=?", (src["id"],)).fetchone()
    if prev and not force and prev[0]:
        with contextlib.suppress(ValueError):
            age = time.time() - datetime.fromisoformat(prev[0]).timestamp()
            if age < float(src.get("ttl_days") or 3) * 86400:
                stat["skipped"] = True
                return stat
    rows = []
    # без этого YouTube отдаёт автоперевод заголовков («DETECTIVE STORY IN UKRAINIAN…» вместо «ДЕТЕКТИВНА ІСТОРІЯ…»)
    xa = ["--extractor-args", f"youtube:lang={src['lang']}"] if src.get("lang") in ("uk", "ru") else []
    for tab in src.get("tabs") or ["videos", "playlists"]:
        _CRAWL["phase"] = f"{src.get('name')}: {tab}"
        if tab == "videos" and known and not force:
            # инкремент: если свежие 60 видео все известны — список не изменился, полный не тянем
            d = _ytdlp_cancellable(xa + ["--flat-playlist", "-J", "--playlist-end", "60", f"{base}/videos"], 120) or {}
            ids = [F._key(f"https://www.youtube.com/watch?v={e['id']}") for e in d.get("entries") or [] if e and e.get("id")]
            parts_ids = set()
            for r in conn.execute("SELECT raw FROM src_items WHERE src=? AND kind='parts'", (src["id"],)):
                with contextlib.suppress(Exception):
                    parts_ids |= {"yt:" + x["id"] for x in json.loads(r[0] or "{}").get("parts") or []}
            if ids and all(i in known or i in parts_ids for i in ids):
                stat["videos"] = -1
                continue
        d = _ytdlp_cancellable(xa + ["--flat-playlist", "-J", f"{base}/{tab}"], 600) or {}   # нет вкладки -> null
        ents = d.get("entries") or []
        part = _rows_from_videos(src, ents) if tab == "videos" else _rows_from_playlists(src, ents)
        stat[tab] = len(part)
        rows += part
    stat["members"] = sum(1 for r in rows if r["availability"] == "members")
    stat["new"] = sum(1 for r in rows if r["source_id"] not in known)
    # записи-части, ставшие частью склейки (раньше были single), убираем
    glued = set()
    for r in rows:
        if r["kind"] == "parts":
            glued |= {F._key(u) for u in r["urls"][1:]}
    upsert(conn, rows)
    _drop_ids(conn, [s for s in glued if s in known])
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.execute("INSERT OR REPLACE INTO src_crawls(source, fetched_at, n, members, error, meta) VALUES(?,?,?,?,?,?)",
                     (src["id"], _now(), conn.execute("SELECT count(*) FROM src_items WHERE src=?", (src["id"],)).fetchone()[0],
                      conn.execute("SELECT count(*) FROM src_items WHERE src=? AND availability='members'",
                                   (src["id"],)).fetchone()[0], None, json.dumps(stat, ensure_ascii=False)))
    return stat


def _crawl_channels(conn, srcs, force):
    for s in srcs:
        if _CRAWL["cancel"]:
            break
        _CRAWL["source"] = s.get("id")
        try:
            st = crawl_channel(conn, s, force=force)
            _CRAWL["results"][s["id"]] = st
            _CRAWL["log"].append(f"{s.get('name')}: " + ("свежий, пропущен" if st["skipped"] else
                                 f"видео {st['videos'] if st['videos'] >= 0 else 'без изменений'}, "
                                 f"плейлистов {st['playlists']}, только для спонсоров {st['members']}, новых {st['new']}"))
        except F.Cancelled:
            _CRAWL["log"].append(f"{s.get('name')}: отменено")
            break
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"[:300]
            _CRAWL["log"].append(f"{s.get('name')}: ошибка — {msg}")
            with A()._WRITE_LOCK, A()._tx(conn):
                conn.execute("INSERT INTO src_crawls(source, error) VALUES(?,?) ON CONFLICT(source) DO UPDATE SET "
                             "error=excluded.error", (s["id"], msg))
        _CRAWL["done"] += 1


def _site_job(sid, force, max_pages, conn=None):
    own = conn is None
    conn = conn or A().db_connect()
    try:
        st = crawl_wide(conn, sid, force=force, max_pages=max_pages)
        _CRAWL["results"][sid] = st
        _CRAWL["log"].append(f"{sid}: {json.dumps(st, ensure_ascii=False)}")
    except F.Cancelled:
        _CRAWL["log"].append(f"{sid}: отменено, курсор сохранён")
    except Exception as e:
        _CRAWL["log"].append(f"{sid}: ошибка — {type(e).__name__}: {e}"[:300])
    finally:
        _CRAWL["done"] += 1
        if own:
            conn.close()


def _plan(conn, only, force, auto):
    """Что обходить: каналы YouTube + сайты. На автостарте сервера сайты, у которых полный проход ещё не сделан,
    пропускаются (долго; его запускают явно: CLI `crawl` или POST op=crawl source=<сайт>), остальные — инкремент."""
    srcs = load_sources()
    cfg = srcs.get("sites") or {}
    yt = [s for s in srcs.get("youtube") or [] if not only or only in (s.get("id"), "youtube")]
    sites = []
    for sid in SITE_SOURCES:
        if only and only not in (sid, "sites") and not (only == "akniga" and sid == "akniga-sitemap"):
            continue
        c = cfg.get(sid.split("-")[0]) or {}
        if c.get("crawl") is False:
            continue
        if auto:
            m = _cmeta(conn, sid)
            if sid == "akniga-sitemap":
                if not m.get("map_at"):
                    continue
            elif not m.get("full_done") and sid != "archive":
                continue
            last = (m.get("last_run") or {}).get("at")
            ttl = float(c.get("crawl_ttl_days") or 3) * 86400
            if last and time.time() - datetime.fromisoformat(last).timestamp() < ttl:
                continue
        sites.append(sid)
    return yt, sites


def _crawl_worker(only, force, auto=False, max_pages=None, parallel=False):
    conn = A().db_connect()
    try:
        yt, sites = _plan(conn, only, force, auto)
        _CRAWL["total"] = len(yt) + len(sites)
        import_manifests(conn)
        if parallel:                       # разные хосты — параллельно (CLI); каждый поток — своё соединение
            ths = [threading.Thread(target=_site_job, args=(sid, force, max_pages), daemon=True) for sid in sites]
            for t in ths:
                t.start()
            _crawl_channels(conn, yt, force)
            for t in ths:
                while t.is_alive():
                    t.join(1)
        else:
            _crawl_channels(conn, yt, force)
            for sid in sites:
                if _CRAWL["cancel"]:
                    break
                _CRAWL["source"] = sid
                _site_job(sid, force, max_pages, conn)
        with contextlib.suppress(Exception):
            sync_manifest_availability(conn)
        with contextlib.suppress(Exception):
            cross_check(conn)
        if not only and not _CRAWL["cancel"]:
            try:
                lc = learn_channels(conn)
                if lc.get("added") or lc.get("suggest"):
                    _CRAWL["log"].append(f"каналы из живого поиска: добавлено {len(lc['added'])}, "
                                         f"кандидатов {len(lc['suggest'])}")
                if lc.get("added"):
                    _crawl_channels(conn, [x for x in load_sources().get("youtube") or []
                                           if x["id"] in {a["id"] for a in lc["added"]}], False)
            except F.Cancelled:
                pass
            except Exception as e:
                _CRAWL["log"].append(f"каналы из живого поиска: ошибка — {type(e).__name__}: {e}"[:300])
        _CRAWL["phase"] = "склейка произведений"
        try:
            w = rebuild_works(conn)
            _CRAWL["log"].append(f"произведения: {w['works']} из {w['records']} записей за {w['seconds']} с")
        except Exception as e:
            _CRAWL["log"].append(f"произведения: ошибка — {type(e).__name__}: {e}"[:300])
    finally:
        _CRAWL.update(running=False, finished=_now(), phase="", source=None)
        conn.close()


def start_crawl(source=None, force=False, auto=False, max_pages=None):
    with _CLOCK:
        if _CRAWL["running"]:
            return {"ok": False, "error": "краулинг уже идёт"}
        _CRAWL.update(running=True, source=None, phase="старт", done=0, total=0, started=_now(), finished=None,
                      cancel=False, log=[], results={}, per={})
    threading.Thread(target=_crawl_worker, args=(source, force, auto, max_pages), daemon=True,
                     name="abook-catalog-crawl").start()
    return {"ok": True}


def cancel_crawl():
    if not _CRAWL["running"]:
        return {"ok": False}
    _CRAWL["cancel"] = True
    p = _CRAWL.get("proc")
    if p:
        with contextlib.suppress(Exception):
            os.killpg(p.pid, signal.SIGTERM)
    return {"ok": True}


def crawl_status(conn):
    srcs = load_sources()
    per = {r["source"]: dict(r) for r in conn.execute("SELECT * FROM src_crawls")}
    counts = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT src, count(*), sum(availability='members') FROM src_items GROUP BY src")}
    out = []
    for s in (srcs.get("youtube") or []) + (srcs.get("manifests") or []):
        c = per.get(s["id"]) or {}
        n, mem = counts.get(s["id"], (0, 0))
        out.append({"id": s["id"], "name": s.get("name") or s.get("path"), "kind": "youtube" if "url" in s else "manifest",
                    "items": n, "members": mem or 0, "fetched_at": c.get("fetched_at"), "error": c.get("error"),
                    "meta": json.loads(c["meta"]) if c.get("meta") else None})
    for site in SITE_SOURCES:
        c = per.get(site) or {}
        meta = json.loads(c["meta"]) if c.get("meta") else None
        if meta:
            meta.pop("files_done", None)
            meta.pop("cursor", None)
        n, mem = counts.get(site, (0, 0)) if site != "akniga-sitemap" else ((meta or {}).get("sitemap_urls") or 0, 0)
        q = conn.execute("SELECT count(*) FROM src_queries WHERE site=?", (site,)).fetchone()[0]
        out.append({"id": site, "name": {"archive": "archive.org (+ LibriVox)", "akniga-sitemap": "akniga.org sitemap"}
                    .get(site, site + ".org"), "kind": "site", "items": n, "members": mem or 0, "queries": q,
                    "fetched_at": c.get("fetched_at"), "error": c.get("error"), "meta": meta,
                    "full_done": bool((meta or {}).get("full_done") or (meta or {}).get("map_at")),
                    "progress": (meta or {}).get("page") and (meta or {}).get("pages") and
                    round(meta["page"] / meta["pages"], 3)})
    total = conn.execute("SELECT count(*), sum(availability='members') FROM src_items").fetchone()
    wk = conn.execute("SELECT count(*) FROM works").fetchone()[0]
    ac = per.get("auto-channels")
    return {"running": _CRAWL["running"], "source": _CRAWL["source"], "phase": _CRAWL["phase"],
            "done": _CRAWL["done"], "total": _CRAWL["total"], "started": _CRAWL["started"],
            "finished": _CRAWL["finished"], "log": _CRAWL["log"][-10:], "sources": out,
            "items": total[0], "members": total[1] or 0, "works": wk, "trigram": _trigram(conn),
            "per": {k: {x: y for x, y in v.items() if x != "result"} for k, v in (_CRAWL.get("per") or {}).items()},
            "auto_channels": json.loads(ac["meta"]) if ac and ac.get("meta") else None,
            "sources_file": str(sources_file())}


# ------------------------------------------------------------------ сайты: knigavuhe.org, akniga.org (на лету + кэш)

def _secs_ru(s):
    s = str(s or "")
    h = re.search(r"(\d+)\s*час", s)
    m = re.search(r"(\d+)\s*мин", s)
    t = (int(h.group(1)) * 3600 if h else 0) + (int(m.group(1)) * 60 if m else 0)
    return t or None


def _txt(s):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _short(s, n=400):
    """Аннотация для выдачи и векторов: чистый текст ≤ n символов, обрезка по слову."""
    t = re.sub(r"(?:\.{3}|…)\s*$", "", _txt(s)).strip()
    if len(t) <= n:
        return t
    return t[:n - 1].rsplit(" ", 1)[0].rstrip(" ,.;:—-") + "…"


def _site_fresh(conn, site, q):
    r = conn.execute("SELECT fetched_at FROM src_queries WHERE site=? AND qnorm=?", (site, norm(q))).fetchone()
    return bool(r and time.time() - r[0] < SITE_TTL)


def _site_mark(conn, site, q, n):
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.execute("INSERT OR REPLACE INTO src_queries(site, qnorm, fetched_at, n) VALUES(?,?,?,?)",
                     (site, norm(q), time.time(), n))


def _parse_knigavuhe(h):
    rows = []
    for blk in re.split(r'<div class="bookkitem(?: -[\w-]+)*">', h)[1:]:
        m = re.search(r'<a href="(/book/[^"]+)" class="bookkitem_name">(.*?)</a>', blk, re.S)
        if not m:
            continue
        url = "https://knigavuhe.org" + m.group(1)
        work = _txt(re.sub(r"</?span[^>]*>", "", m.group(2)))
        au = re.search(r'bookkitem_author_label">[^<]*</span>(.*?)</span>', blk, re.S)
        author = ", ".join(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", au.group(1), re.S)) if au else ""
        rd = re.search(r'-reader"></span>(.*?)</div>', blk, re.S)
        reader = ", ".join(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", rd.group(1), re.S)) if rd else ""
        tm = re.search(r'bookkitem_meta_time">([^<]+)<', blk)
        vw = re.search(r'-views"></span>\s*<span[^>]*>([\d\s ]+)<', blk)
        gn = re.search(r'bookkitem_genre">(.*?)</div>', blk, re.S)
        ab = re.search(r'bookkitem_about">(.*?)</div>', blk, re.S)
        se = re.search(r'-serie"></span>(.*?)</div>', blk, re.S)
        rows.append({"source_id": F._key(url), "src": "knigavuhe", "platform": "knigavuhe.org", "url": url, "urls": [url],
                     "channel": "knigavuhe.org", "title": f"{author} — {work}" if author else work, "author": author,
                     "work": work, "reader": reader, "lang": lang_guess(author, work), "duration_s": _secs_ru(tm.group(1) if tm else ""),
                     "parts": 0, "kind": "files", "availability": "unknown", "downloadable": 1,
                     "views": int(re.sub(r"\D", "", vw.group(1))) if vw and re.sub(r"\D", "", vw.group(1)) else None,
                     "complete_score": None, "complete_notes": "состав файлов проверяется при поиске",
                     "genre": ", ".join(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", gn.group(1), re.S)) if gn else "",
                     "annotation": _short(ab.group(1)) if ab else "", "series": _txt(se.group(1))[:200] if se else "",
                     "raw": {"site": "knigavuhe"}})
    return rows


def _parse_akniga(h):
    rows = []
    for blk in re.split(r'<div class="content__main__articles--item', h)[1:]:
        m = re.search(r'<a href="(https://akniga\.org/[^"]+)" class="content__article-main-link[^>]*>\s*<h2[^>]*>(.*?)</h2>',
                      blk, re.S)
        if not m:
            continue
        url, head = m.group(1), _txt(m.group(2))
        author, _, work = head.partition(" – ")
        if not work:
            author, work = "", head
        perf = re.findall(r'href="https://akniga\.org/performer/[^"]*">([^<]+)<', blk)
        hh = re.search(r'class="hours">([^<]*)<', blk)
        mm = re.search(r'class="minutes">([^<]*)<', blk)
        if not author and not perf and not hh and not mm:      # подборка-статья в ленте, не книга
            continue
        lic = "caption__article-preview\">Лицензия" in blk
        gn = re.search(r'class="section__title">.*?<span>([^<]+)</span>', blk, re.S)
        ab = re.search(r'class="description__article-main[^"]*">(.*?)</span>', blk, re.S)
        se = re.search(r'book-series">.*?<a [^>]*>([^<]+)</a>', blk, re.S)
        vw = re.search(r'label--views[^>]*>.*?</svg>\s*([\d\s]+)<', blk, re.S)
        rows.append({"source_id": F._key(url), "src": "akniga", "platform": "akniga.org", "url": url, "urls": [url],
                     "channel": "akniga.org", "title": head, "author": author.strip(), "work": work.strip(),
                     "reader": ", ".join(_txt(x) for x in perf), "lang": lang_guess(author, work),
                     "duration_s": _secs_ru(f"{hh.group(1) if hh else ''} {mm.group(1) if mm else ''}"),
                     "parts": 0, "kind": "files", "availability": "members" if lic else "unknown", "downloadable": 0,
                     "complete_score": None,
                     "complete_notes": ("«Лицензия» — платная, только по подписке akniga" if lic else
                                        "akniga.org: плеер зашифрован, yt-dlp не берёт — только как подсказка"),
                     "genre": _txt(gn.group(1)) if gn else "", "annotation": _short(ab.group(1)) if ab else "",
                     "series": _txt(se.group(1))[:200] if se else "",
                     "views": int(re.sub(r"\D", "", vw.group(1))) if vw and re.sub(r"\D", "", vw.group(1)) else None,
                     "raw": {"site": "akniga", "license": lic}})
    return rows


def search_site(conn, site, q, force=False):
    """Поиск на сайте с кэшем 14 дней: свежий запрос -> из индекса, без сети. Возвращает число записей."""
    if not force and _site_fresh(conn, site, q):
        return None
    if site == "knigavuhe":
        h = F._http("https://knigavuhe.org/search/?q=" + urllib.parse.quote(q), timeout=15)
        rows = _parse_knigavuhe(h)
    elif site == "akniga":
        h = F._http("https://akniga.org/search/books?q=" + urllib.parse.quote(q), timeout=15)
        rows = _parse_akniga(h)
    else:
        raise ValueError(site)
    upsert(conn, rows)
    _site_mark(conn, site, q, len(rows))
    return len(rows)


def site_cands(site, q):
    """Для abook_find._run_platforms: поиск на сайте (с кэшем) -> кандидаты в формате _cand."""
    conn = A().db_connect()
    try:
        search_site(conn, site, q)
        return [to_cand(r, f"{site}.org") for r in _fts(conn, q, 12, src=site)]
    finally:
        conn.close()


def knigavuhe_tracks(url):
    """Страница книги knigavuhe -> треки (прямые mp3) из `new BookPlayer(id, [...])`."""
    h = F._http(url, timeout=20)
    m = re.search(r"new BookPlayer\(\d+,\s*(?=\[)", h)
    if not m:
        blocked = re.search(r"по требованию правообладател|недоступна|заблокирован", h, re.I)
        raise RuntimeError("книга снята по требованию правообладателя" if blocked else "плеер не найден на странице")
    tr, _ = json.JSONDecoder().raw_decode(h, m.end())
    return [{"url": t["url"], "title": t.get("title") or "", "duration": t.get("duration_float") or t.get("duration"),
             "error": t.get("error")} for t in tr if t.get("url")]


# ------------------------------------------------------------------ поиск по индексу (мгновенный)

def _q_terms(q, tri):
    ws = [w for w in fold(q).split() if len(w) >= 3]
    out = []
    for w in ws:
        if len(w) >= 6:                     # основа: окончания (обочине/обочина, предків/предки)
            w = w[:len(w) - 2]
        elif len(w) == 5:
            w = w[:4]
        out.append(w)
    return out


_STOP = {"аудиокнига", "аудиокниг", "аудиокни", "аудиокн", "аудио", "книга", "полностью", "читает", "чита"}


def _fts(conn, q, limit=50, src=None, table="src", exact=False):
    """FTS по записям (table='src': src_fts/src_items) или по произведениям (table='works': works_fts/works).
    exact — слова как есть (без обрезки окончаний) и все обязательны: проход по скелетам в search_works.
    Два шага: сначала только rowid+текст из индекса (быстро), полные строки — лишь для прошедших порог."""
    tri = _trigram(conn)
    qq = " ".join(w for w in norm(q).split() if w not in _STOP and not w.startswith("аудиокн"))
    terms = [w for w in qq.split() if len(w) >= 3] if exact else _q_terms(qq, tri)
    if not terms:
        return []
    # OR по основам, затем порог: ≥ 60 % слов запроса (рус/укр пишутся по-разному: «забытых»/«забутих»)
    expr = (" AND " if exact else " OR ").join((f'"{w}"*' if not tri else f'"{w}"') for w in terms)
    need = len(terms) if exact else max(1, -(-len(terms) * 3 // 5))
    ft, tb = ("works_fts", "works") if table == "works" else ("src_fts", "src_items")
    try:
        if src:
            hits = conn.execute(f"SELECT f.rowid, f.norm FROM {ft} f JOIN {tb} s ON s.id=f.rowid WHERE {ft} MATCH ? "
                                f"AND s.src=? ORDER BY bm25({ft}) LIMIT ?", (expr, src, max(limit * 8, 400))).fetchall()
        else:
            hits = conn.execute(f"SELECT rowid, norm FROM {ft} WHERE {ft} MATCH ? ORDER BY bm25({ft}) LIMIT ?",
                                (expr, max(limit * 8, 400))).fetchall()
    except sqlite3.OperationalError:
        return []
    keep = [(h[0], h[1]) for h in hits if sum(1 for w in terms if w in h[1]) >= need][:limit * 4]
    if not keep:
        return []
    full = {r["id"]: r for r in conn.execute(f"SELECT * FROM {tb} WHERE id IN ({','.join('?' * len(keep))})",
                                              [k[0] for k in keep])}
    out = []
    for rid, n in keep:
        if rid in full:
            d = dict(full[rid])
            d["_n"] = n
            out.append(d)
    return out


_LIB = {"t": 0, "keys": {}}


def _library_keys(conn):
    if time.time() - _LIB["t"] > 120:
        keys = {}
        for r in conn.execute("SELECT id, urls, in_library FROM items"):
            with contextlib.suppress(Exception):
                for u in json.loads(r["urls"] or "[]")[:1]:
                    keys[F._key(u)] = r["id"]
        _LIB.update(t=time.time(), keys=keys)
    return _LIB["keys"]


def _probe_cached_row(conn, url):
    r = conn.execute("SELECT at, data FROM probe_cache WHERE key=?", (_pkey([url]),)).fetchone()
    if r and time.time() - r[0] < PROBE_TTL:
        with contextlib.suppress(Exception):
            return json.loads(r[1])
    return None


def to_cand(r, found_by="каталог"):
    """Строка src_items -> кандидат abook_find (_cand), со служебными полями каталога."""
    urls = json.loads(r["urls"] or "[]") or [r["url"]]
    typ = {"parts": "parts", "playlist": "playlist", "files": "files"}.get(r["kind"], "video")
    c = F._cand(r["url"], found_by, title=r["title"] or "", channel=r["channel"] or "", duration=r["duration_s"],
                narrator=r["reader"] or "", lang=r["lang"] or "", views=r["views"], type=typ)
    c["urls"] = urls
    c["platform"] = r["platform"] or c["platform"]
    c["catalog"] = {"id": r["id"], "src": r["src"], "author": r["author"], "work": r["work"],
                    "availability": r["availability"], "downloadable": bool(r["downloadable"]),
                    "complete_score": r["complete_score"], "complete_notes": r["complete_notes"], "kind": r["kind"],
                    "parts": r["parts"]}
    if r["raw"] and '"radioplay": true' in r["raw"]:
        c["kind"] = "radioplay"
    return c


def search(conn, q, limit=20, include_members=False):
    """Мгновенный поиск по каталогу. -> (кандидаты в формате карточек abook_find + поля каталога, мс)."""
    t0 = time.perf_counter()
    rows = _fts(conn, q, limit)
    titles = [q]
    lib = _library_keys(conn)
    scored = []
    for r in rows:
        if r["availability"] == "members" and not include_members:
            continue
        rel = F.relevance(f"{r['author']} {r['work']} {r['title']}", titles)
        relw = F.relevance(f"{r['author']} {r['work']}", titles) if r["work"] else rel
        s = 60 * max(rel, relw)
        s += {"public": 8, "unknown": 0}.get(r["availability"], -20)
        s += 10 * (r["complete_score"] if r["complete_score"] is not None else 0.6)
        s += 0 if r["downloadable"] else -15
        s += {"ru": 4, "uk": 4, "en": 1}.get(r["lang"], 0)
        if r["duration_s"] and r["duration_s"] > 3600:
            s += 3
        if r["views"]:
            s += min(5.0, math.log10(float(r["views"]) + 1))
        scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, r in scored[:limit]:
        c = to_cand(r)
        out.append(pub(c, r, score=round(s, 1), lib=lib.get(r["source_id"]), probe=_probe_cached_row(conn, r["url"])))
    return out, round((time.perf_counter() - t0) * 1000, 1)


def pub(c, r, score=None, lib=None, probe=None):
    """Карточка кандидата для /api/find/catalog — поля как у abook_find._pub + поля каталога."""
    cat = c["catalog"]
    d = F._pub(c)
    flags = []
    if cat["availability"] == "unknown":
        flags.append("доступность не проверена (могут быть только для спонсоров)")
    if cat["complete_notes"]:
        flags.append(cat["complete_notes"])
    if not cat["downloadable"]:
        flags.append("скачать нельзя — только ссылка")
    pr = (probe or {}).get("probe") or {}
    d.update({"key": _key_of(r), "found_by": ["каталог"], "flags": flags, "score": score,
              "verified": bool(pr.get("ok")), "duration": pr.get("duration") or d["duration"],
              "parts": pr.get("parts") or r["parts"] or len(c["urls"]),
              "catalog_id": r["id"], "source": r["src"], "author": r["author"], "work": r["work"],
              "availability": cat["availability"], "downloadable": cat["downloadable"],
              "complete_score": cat["complete_score"], "complete_notes": cat["complete_notes"],
              "link": r["url"], "in_library": lib, "fetched_at": r["fetched_at"]})
    if pr.get("error") and not pr.get("ok"):
        d["drop"] = "недоступно: " + pr["error"][:160]
    return d


def _key_of(r):
    return r["source_id"]


def get_row(conn, key):
    return conn.execute("SELECT * FROM src_items WHERE source_id=? OR id=?",
                        (str(key), int(key) if str(key).isdigit() else -1)).fetchone()


# ------------------------------------------------------------------ кэш проверки (probe) по URL, TTL 7 дней

def _pkey(urls):
    return hashlib.sha1("\n".join(urls).encode()).hexdigest()


_TRANSIENT = re.compile(r"^\w+(?:Error|Exception)\b|timed out|timeout|URLError|ConnectionReset|Temporary|429|Too Many|socket|не открывается", re.I)


def probe_cached(c):
    """abook_find.probe с кэшем (7 дней) + сайты каталога (knigavuhe: прямые mp3; akniga: не скачивается)
    + отметка доступности в src_items (members-only по ответу yt-dlp)."""
    conn = A().db_connect()
    try:
        k = _pkey(c["urls"])
        r = conn.execute("SELECT at, data FROM probe_cache WHERE key=?", (k,)).fetchone()
        fresh_only = (urllib.parse.urlparse(c["url"]).hostname or "").endswith("4read.org")
        if r and time.time() - r[0] < PROBE_TTL and not fresh_only:
            with contextlib.suppress(Exception):
                d = json.loads(r[1])
                c.update({x: d[x] for x in ("probe", "urls", "type", "title", "channel", "views") if d.get(x) is not None})
                c["probe"]["cached"] = True
                if c.get("catalog") and c["probe"].get("ok"):
                    c["catalog"]["availability"] = "public"
                return c
        orig_urls = list(c["urls"])
        host = (urllib.parse.urlparse(c["url"]).hostname or "").lower()
        if "knigavuhe" in host:
            _probe_knigavuhe(c)
        elif host.endswith("4read.org"):
            _probe_4read(c)
        elif "akniga" in host:
            c["probe"] = {"ok": False, "error": "akniga.org: плеер зашифрован, yt-dlp не берёт — скачать нельзя",
                          "duration": c.get("duration"), "parts": 1, "unavailable": 0, "order": None, "titles": []}
        else:
            F.probe(c)
        pr = c["probe"]
        err = pr.get("error") or ""
        mem = bool(re.search(r"members|member-only|join this channel|спонсор|subscriber|premium", err, re.I))
        if mem:
            pr["error"] = "только для спонсоров канала"
        if c.get("catalog"):
            c["catalog"]["availability"] = "members" if mem else "public" if pr.get("ok") else c["catalog"]["availability"]
        if (pr.get("ok") and not fresh_only) or (err and not _TRANSIENT.search(err)):
            with A()._WRITE_LOCK, A()._tx(conn):
                conn.execute("INSERT OR REPLACE INTO probe_cache(key, at, data) VALUES(?,?,?)",
                             (_pkey(orig_urls), time.time(), json.dumps(
                                 {x: c.get(x) for x in ("probe", "urls", "type", "title", "channel", "views")},
                                 ensure_ascii=False)))
                av = "members" if mem else "public" if pr.get("ok") else None
                if av:
                    conn.execute("UPDATE src_items SET availability=?, checked_at=? WHERE source_id=?",
                                 (av, _now(), F._key(c["url"])))
        return c
    finally:
        conn.close()


def _probe_knigavuhe(c):
    pr = {"ok": False, "error": "", "duration": None, "parts": 1, "unavailable": 0, "order": None, "titles": []}
    c["probe"] = pr
    try:
        tr = knigavuhe_tracks(c["url"])
        bad = [t for t in tr if t.get("error")]
        good = [t for t in tr if not t.get("error")]
        if not good:
            pr["error"] = "нет доступных файлов"
            return c
        c["urls"], c["type"] = [t["url"] for t in good], "files"
        pr.update(parts=len(good), unavailable=len(bad), titles=[t["title"] for t in good],
                  duration=sum(float(t["duration"] or 0) for t in good) or None)
        if all(t.get("duration") for t in good):      # длительность каждого трека — abook get сверит с ней части
            pr["part_durations"] = [float(t["duration"]) for t in good]
        pr["order"] = A().title_order_problem(pr["titles"])
        req = urllib.request.Request(good[0]["url"], method="HEAD", headers={"User-Agent": F.UA})
        urllib.request.urlopen(req, timeout=F.HTTP_TIMEOUT).close()
        pr["ok"] = bool(pr["duration"]) and not bad
        if bad:
            pr["error"] = f"недоступно файлов: {len(bad)}"
    except Exception as e:
        pr["error"] = f"{type(e).__name__}: {e}"[:200]
    return c


# ------------------------------------------------------------------ скачивание кандидата каталога

def enqueue_row(conn, key):
    """Запись каталога -> очередь загрузок abook_find (тот же конвейер abook get)."""
    r = get_row(conn, key)
    if not r:
        raise ValueError("Запись каталога не найдена")
    if r["availability"] == "members":
        raise ValueError("Только для спонсоров канала — скачать нельзя")
    if not r["downloadable"]:
        raise ValueError("С этой площадки скачать нельзя — откройте ссылку")
    c = probe_cached(to_cand(r))
    pr = c.get("probe") or {}
    if not pr.get("ok"):
        raise ValueError("Источник не прошёл проверку: " + (pr.get("error") or "недоступен"))
    with F._QLOCK:
        for e in F._qload():
            if e["state"] in F.ACTIVE and e.get("source_key") == r["source_id"]:
                return {"ok": True, "key": e["key"], "already": True, "position": F._position(e)}
    author = r["author"] or "Неизвестный автор"
    title = r["work"] or r["title"] or r["source_id"]
    iid = F._new_id(conn, author, title)
    kind = "radioplay" if c.get("kind") == "radioplay" else "audiobook"
    item = {"id": iid, "section": "Аудиоспектакли/По запросу" if kind == "radioplay" else F.UI_SECTION,
            "author": author, "title": title, "narrator": r["reader"] or "", "kind": kind, "lang": r["lang"] or "ru",
            "urls": c["urls"], "duration_h": round(float(pr.get("duration") or 0) / 3600, 2) or None,
            **({"part_durations": pr["part_durations"]} if len(pr.get("part_durations") or []) == len(c["urls"]) else {}),
            "source": f"{r['platform']} · {r['channel']}".strip(" ·"), "about": "", "why": "",
            "requested": {"query": "", "at": _now(), "catalog": r["source_id"], "found_by": ["каталог"]}}
    return F.enqueue(item, parts=pr.get("parts") or len(item["urls"]), source_key=r["source_id"])


# ------------------------------------------------------------------ широкий каталог (Этап 2): полный обход сайтов

# Вежливость: ≤ 1 запрос в CRAWL_INTERVAL с на хост (в разных потоках — разные хосты), честный User-Agent,
# ретраи с нарастающей паузой (429/5xx/сеть; Retry-After уважается), курсор в src_crawls.meta после каждой
# страницы — обход прерывается когда угодно (отмена, Ctrl-C, падение) и продолжается с того же места.
CRAWL_INTERVAL = float(os.environ.get("ABOOK_CRAWL_INTERVAL") or 0.8)
CRAWL_UA = os.environ.get("ABOOK_CRAWL_UA") or ("Mozilla/5.0 (compatible; abook-catalog/1.0; personal audiobook "
                                                "library index; ~1 req/s)")
ARCHIVE_Q = ('mediatype:audio AND language:(rus OR russian OR ru OR "Русский" OR "русский" OR ukr OR ukrainian '
             'OR "Українська" OR "украинский")')
ARCHIVE_FIELDS = "identifier,title,creator,description,runtime,language,subject,collection,downloads,item_size,publicdate"
SITE_SOURCES = ("knigavuhe", "akniga", "akniga-sitemap", "archive", "4read")

_HOSTS = {}
_HLOCK = threading.Lock()


def _csleep(sec):
    """Пауза, прерываемая отменой обхода."""
    end = time.time() + sec
    while time.time() < end:
        if _CRAWL["cancel"]:
            raise F.Cancelled()
        time.sleep(min(0.5, max(0.0, end - time.time())))


def polite_get(url, tries=6, timeout=40):
    """GET с паузой между запросами к одному хосту и ретраями. 404/410 -> None."""
    host = urllib.parse.urlparse(url).hostname or ""
    with _HLOCK:
        h = _HOSTS.setdefault(host, {"lock": threading.Lock(), "last": 0.0, "n": 0, "errors": 0})
    err = None
    for i in range(tries):
        with h["lock"]:
            _csleep(max(0.0, h["last"] + CRAWL_INTERVAL - time.time()))
            h["last"] = time.time()
            h["n"] += 1
        wait = min(180, 4 * 2 ** i)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": CRAWL_UA, "Accept-Language": "ru,uk;q=0.8"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code not in (403, 408, 429) and e.code < 500:
                raise
            err = f"HTTP {e.code}"
            with contextlib.suppress(Exception):
                wait = max(wait, min(600, float(e.headers.get("Retry-After") or 0)))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            err = f"{type(e).__name__}: {e}"
        h["errors"] += 1
        _progress(phase=f"{host}: {err}, повтор через {wait:.0f} с")
        _csleep(wait)
    raise RuntimeError(f"{host}: {err} ({tries} попыток)")


def _progress(sid=None, **kw):
    sid = sid or getattr(_TLS, "sid", None) or "?"
    d = _CRAWL.setdefault("per", {}).setdefault(sid, {})
    d.update(kw, at=time.time())


_TLS = threading.local()


def _cmeta(conn, source):
    r = conn.execute("SELECT meta FROM src_crawls WHERE source=?", (source,)).fetchone()
    with contextlib.suppress(Exception):
        return json.loads(r[0] or "{}") if r else {}
    return {}


def _csave(conn, source, meta, error=None, src=None):
    n = conn.execute("SELECT count(*) FROM src_items WHERE src=?", (src or source,)).fetchone()[0]
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.execute("INSERT OR REPLACE INTO src_crawls(source, fetched_at, n, members, error, meta) VALUES(?,?,?,?,?,?)",
                     (source, _now(), n, 0, error, json.dumps(meta, ensure_ascii=False)))


_LISTING = {
    # лента «новые» — от свежих к старым; /letter/ запрещён robots.txt knigavuhe и не нужен
    "knigavuhe": {"url": lambda n: f"https://knigavuhe.org/new/?page={n}", "last": r'href="/new/\?page=(\d+)"',
                  "parse": lambda h: _parse_knigavuhe(h)},
    "akniga": {"url": lambda n: "https://akniga.org/index/" if n == 1 else f"https://akniga.org/index/page{n}/",
               "last": r"/index/page(\d+)/", "parse": lambda h: _parse_akniga(h)},
}


def crawl_site(conn, site, force=False, max_pages=None):
    """Полный обход ленты сайта (knigavuhe ≈ 6,5 тыс. стр. × 10, akniga ≈ 6 тыс. стр. × 12) с курсором.
    Каждый запуск: сначала «голова» — страницы с 1-й, пока две подряд не окажутся целиком известными (новое
    с прошлого раза), затем продолжение полного прохода с meta.page, пока он не завершён (meta.full_done).
    force=True — полный проход заново с 1-й страницы. max_pages — бюджет запросов на этот запуск."""
    cfg = _LISTING[site]
    meta = _cmeta(conn, site)
    if force:
        meta.update(page=0, full_done=False)
    known = {r[0] for r in conn.execute("SELECT source_id FROM src_items WHERE src=?", (site,))}
    stat = {"pages": 0, "rows": 0, "new": 0}
    budget = [max_pages or 10 ** 9]

    def page(n):
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        h = polite_get(cfg["url"](n))
        if h is None:
            return []
        ls = [int(x) for x in re.findall(cfg["last"], h)]
        if ls:
            meta["pages"] = max(ls) if n == 1 else max(ls + [meta.get("pages") or 0])
        rows = cfg["parse"](h)
        new = [r for r in rows if r["source_id"] not in known]
        upsert(conn, rows)
        known.update(r["source_id"] for r in rows)
        stat["pages"] += 1
        stat["rows"] += len(rows)
        stat["new"] += len(new)
        return rows, new

    # 1) голова: новое с прошлого запуска
    if known and not force:
        streak = 0
        for n in range(1, 301):
            _progress(phase=f"{site}: новые, стр. {n}", done=stat["pages"], total=meta.get("pages"))
            res = page(n)
            if not res:
                break
            streak = streak + 1 if not res[1] else 0
            if streak >= 2:
                break
        meta["head_at"] = _now()
        _csave(conn, site, meta)
    # 2) полный проход (продолжение с курсора)
    if not meta.get("full_done"):
        n = int(meta.get("page") or 0) + 1
        meta.setdefault("full_started", _now())
        empty = 0
        while True:
            if _CRAWL["cancel"]:
                raise F.Cancelled()
            tot = meta.get("pages")
            if tot and n > tot:
                meta.update(full_done=True, full_at=_now())
                break
            _progress(phase=f"{site}: полный обход, стр. {n}" + (f" из {tot}" if tot else ""), done=n, total=tot)
            res = page(n)
            if res is None:                        # бюджет на этот запуск кончился
                break
            empty = empty + 1 if not res or not res[0] else 0
            meta["page"] = n
            _csave(conn, site, meta)
            if empty >= 3:                         # три пустые страницы подряд — лента кончилась
                meta.update(full_done=True, full_at=_now())
                break
            n += 1
    meta["last_run"] = dict(stat, at=_now())
    _csave(conn, site, meta)
    return stat


def _parse_akniga_page(url, h):
    """Карточка книги akniga (для дыр между лентой и sitemap) -> запись src_items."""
    m = re.search(r'<h1 class="caption__article-main">(.*?)</h1>', h, re.S)
    if not m:
        return None
    head = _txt(m.group(1))
    author, _, work = head.partition(" – ")
    if not work:
        author, work = "", head
    perf = re.findall(r'href="https://akniga\.org/performer/[^"]*">([^<]+)<', h)
    hh = re.search(r'class="hours">([^<]*)<', h)
    mm = re.search(r'class="minutes">([^<]*)<', h)
    gn = re.search(r'class="section__title">.*?<span>([^<]+)</span>', h, re.S) or \
        re.search(r'akniga\.org/section/[^"]*"[^>]*>([^<]{3,60})<', h)
    ab = re.search(r'<div class="description__article-main">(.*?)</div>', h, re.S)
    if not ab or len(_txt(ab.group(1))) < 40:
        ab = re.search(r'<meta property="og:description" content="([^"]*)"', h)
    ann = _short(re.sub(r"^Аудиокнига «[^»]*»(?:, читает [^.]*)?\.\s*(?:Слушайте бесплатно онлайн\.)?\s*", "",
                        _txt(ab.group(1)) if ab else ""))
    lic = bool(re.search(r'caption__article-preview">Лицензия', h))
    reader = ", ".join(dict.fromkeys(_txt(x) for x in perf))
    return {"source_id": F._key(url), "src": "akniga", "platform": "akniga.org", "url": url, "urls": [url],
            "channel": "akniga.org", "title": head, "author": author.strip(), "work": work.strip(), "reader": reader,
            "lang": lang_guess(author, work), "duration_s": _secs_ru(f"{hh.group(1) if hh else ''} {mm.group(1) if mm else ''}"),
            "parts": 0, "kind": "files", "availability": "members" if lic else "unknown", "downloadable": 0,
            "complete_score": None, "genre": _txt(gn.group(1)) if gn else "", "annotation": ann,
            "complete_notes": ("«Лицензия» — платная, только по подписке akniga" if lic else
                               "akniga.org: плеер зашифрован, yt-dlp не берёт — только как подсказка"),
            "raw": {"site": "akniga", "license": lic, "from": "page"}}


def crawl_akniga_sitemap(conn, force=False, max_pages=None):
    """sitemap.xml akniga -> src_sitemap (все ссылки на книги + lastmod; ≈ 150 файлов по 500), затем карточки
    книг, которых нет в индексе после ПОЛНОГО обхода ленты (не больше max_pages за запуск, по умолчанию 5000).
    Sitemap перечитывается раз в 7 дней (или force)."""
    meta = _cmeta(conn, "akniga-sitemap")
    stat = {"files": 0, "urls": 0, "fetched": 0, "missing": 0}
    fresh = meta.get("map_at") and time.time() - datetime.fromisoformat(meta["map_at"]).timestamp() < 7 * 86400
    if force or not fresh:
        idx = polite_get("https://akniga.org/sitemap.xml") or ""
        files = [u for u in re.findall(r"<loc>([^<]+)</loc>", idx) if "sitemap_audiobooks" in u]
        done = set(meta.get("files_done") or []) if not force else set()
        for i, fu in enumerate(files):
            if fu in done:
                continue
            _progress(phase=f"akniga sitemap {i + 1}/{len(files)}", done=i, total=len(files))
            x = polite_get(fu) or ""
            pairs = re.findall(r"<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", x)
            with A()._WRITE_LOCK, A()._tx(conn):
                conn.executemany("INSERT INTO src_sitemap(site, url, lastmod, seen_at) VALUES('akniga',?,?,?) "
                                 "ON CONFLICT(site, url) DO UPDATE SET lastmod=excluded.lastmod, seen_at=excluded.seen_at",
                                 [(u.strip(), lm or None, _now()) for u, lm in pairs])
            stat["files"] += 1
            stat["urls"] += len(pairs)
            done.add(fu)
            meta["files_done"] = sorted(done)
            _csave(conn, "akniga-sitemap", meta, src="akniga")
        meta.update(map_at=_now(), files_total=len(files), files_done=[])
        _csave(conn, "akniga-sitemap", meta, src="akniga")
    known = {r[0] for r in conn.execute("SELECT source_id FROM src_items WHERE src='akniga'")}
    miss = [r[0] for r in conn.execute("SELECT url FROM src_sitemap WHERE site='akniga' ORDER BY lastmod DESC")
            if F._key(r[0]) not in known]
    stat["missing"] = len(miss)
    # пока лента akniga не пройдена целиком, «дыры» — это почти весь сайт: карточки по одной не тянем
    lim = (max_pages if max_pages is not None else 5000) if _cmeta(conn, "akniga").get("full_done") else 0
    for i, u in enumerate(miss[:lim]):
        _progress(phase=f"akniga: карточки вне ленты {i + 1}/{min(lim, len(miss))}", done=i, total=min(lim, len(miss)))
        h = polite_get(u)
        r = _parse_akniga_page(u, h) if h else None
        if r:
            r["lastmod"] = conn.execute("SELECT lastmod FROM src_sitemap WHERE site='akniga' AND url=?", (u,)).fetchone()[0]
            upsert(conn, [r])
            stat["fetched"] += 1
    meta["last_run"] = dict(stat, at=_now())
    meta["sitemap_urls"] = conn.execute("SELECT count(*) FROM src_sitemap WHERE site='akniga'").fetchone()[0]
    _csave(conn, "akniga-sitemap", meta, src="akniga")
    return stat


# ------------------------------------------------------------------ 4read.org — украинские аудиокниги

# 4read.org («АудіоКниги Українською», DLE): ≈ 4 900 страниц в sitemap news_pages.xml (часть — статьи без плеера),
# бесплатно, без входа. Карточка: автор, «Читає», «Триває» (чч:мм:сс), жанры, цикл, просмотры, аннотация. Плеер —
# Playerjs с file:"{v1}m33u2/<slug>.m3u" -> m3u с прямыми mp3 на reasd.org (подписаны, живут ≈ 10 ч — поэтому
# probe_cached их не кэширует, mp3 берутся заново при постановке в очередь). robots.txt: закрыты только /user/,
# do=download/search и т. п. — карточки и m3u открыты. Инкремент — по lastmod sitemap.
FOURREAD = "https://4read.org"


def _parse_4read_page(url, h):
    """Карточка 4read -> запись src_items; статья (нет «Читає»/плеера и длительности) -> None."""
    m = re.search(r'<h1[^>]*>(.*?)</h1>', h, re.S)
    og = re.search(r'<meta property="og:title" content="([^"]*)"', h)
    # og:title — «Назва - АудіоКниги Українською», h1 — «Аудіокнига Назва - автор Автор»
    work = re.sub(r"\s*-\s*АудіоКниги Українською\s*$", "", _txt(og.group(1) if og else "")) or \
        re.sub(r"^Аудіокнига\s+|\s+-\s+автор\s+.*$", "", _txt(m.group(1) if m else ""))
    pl = re.search(r'Playerjs\(\{[^}]*?file:"([^"]+)"', h)
    dur = re.search(r'data-duration="([^"]+)"', h)
    rd = re.search(r'<span>Читає:</span>(.*?)</li>', h, re.S)
    if not work or not (pl or dur or rd):
        return None
    au = re.search(r'<span>Автор:</span>(.*?)</li>', h, re.S)
    author = ", ".join(dict.fromkeys(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", au.group(1), re.S))) if au else ""
    reader = ", ".join(dict.fromkeys(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", rd.group(1), re.S))) if rd else ""
    gn = re.search(r'<span>Жанр:</span>(.*?)</li>', h, re.S)
    genre = " / ".join(_txt(x) for x in re.findall(r"<a [^>]*>(.*?)</a>", gn.group(1), re.S)) if gn else ""
    se = re.search(r'href="https://4read\.org/xfsearch/cikl/[^"]*"[^>]*>([^<]+)<', h)
    vw = re.search(r'Переглядів: </span>([\d\s\xa0]+)<', h)
    ab = re.search(r'itemprop="description">(.*?)</div>', h, re.S)
    m3u = urllib.parse.urljoin(FOURREAD + "/", pl.group(1).replace("{v1}", "")) if pl else ""
    # часть книг вместо своего плеера — встроенные видео YouTube (по видео на часть): их и качаем через yt-dlp
    yt = list(dict.fromkeys(f"https://www.youtube.com/watch?v={x}" for x in
                            re.findall(r'youtube\.com/embed/([\w-]{11})', h) if x != "videoseries")) if not pl else []
    work = re.sub(r"\s*[-–—]\s*АудіоКниги Українською\s*$", "", work)
    return {"source_id": F._key(url), "src": "4read", "platform": "4read.org", "url": url, "urls": [url] + yt,
            "channel": "4read.org", "title": f"{author} — {work}" if author else work, "author": author, "work": work,
            "reader": reader, "lang": "be" if lang_guess(author, work) == "be" else "uk",   # сайт целиком украинский
            "duration_s": _hms(dur.group(1)) if dur else None, "parts": 0, "kind": "files",
            "availability": "public" if pl else "unknown", "downloadable": 1 if pl or yt else 0, "complete_score": None,
            "complete_notes": "" if pl else f"4read: видео YouTube ({len(yt)})" if yt else
            "4read: плеера на странице нет (снята?) — только ссылка",
            "views": int(re.sub(r"\D", "", vw.group(1)) or 0) or None if vw else None,
            "genre": genre, "series": _txt(se.group(1)) if se else "", "annotation": _short(ab.group(1) if ab else ""),
            "raw": {"site": "4read", "m3u": m3u, "youtube": yt}}


def crawl_4read(conn, force=False, max_pages=None):
    """sitemap news_pages.xml -> src_sitemap(site='4read'), затем карточки, которых нет в индексе или у которых
    lastmod новее сохранённого. max_pages — бюджет карточек на запуск. Карточка-статья запоминается (lastmod),
    чтобы не тянуть её снова. Прерывается когда угодно: всё, что дописано, уже в базе."""
    meta = _cmeta(conn, "4read")
    stat = {"urls": 0, "fetched": 0, "books": 0, "articles": 0, "new": 0}
    _progress(phase="4read: sitemap")
    x = polite_get(f"{FOURREAD}/news_pages.xml") or ""
    pairs = re.findall(r"<loc>([^<]+)</loc>(?:\s*<changefreq>[^<]*</changefreq>)?\s*(?:<lastmod>([^<]+)</lastmod>)?", x)
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.executemany("INSERT INTO src_sitemap(site, url, lastmod, seen_at) VALUES('4read',?,?,?) "
                         "ON CONFLICT(site, url) DO UPDATE SET lastmod=excluded.lastmod, seen_at=excluded.seen_at",
                         [(u.strip(), lm or None, _now()) for u, lm in pairs])
    stat["urls"] = len(pairs)
    have = {r[0]: r[1] for r in conn.execute("SELECT source_id, lastmod FROM src_items WHERE src='4read'")}
    skip = meta.get("articles") or {}                    # url -> lastmod статей без плеера
    todo = []
    for u, lm in conn.execute("SELECT url, lastmod FROM src_sitemap WHERE site='4read' ORDER BY lastmod DESC"):
        k = F._key(u)
        if force or (k not in have and skip.get(u) != lm) or (k in have and lm and (have[k] or "") < lm):
            todo.append((u, lm))
    lim = max_pages if max_pages is not None else 10 ** 9
    for i, (u, lm) in enumerate(todo[:lim]):
        if _CRAWL["cancel"]:
            raise F.Cancelled()
        _progress(phase=f"4read: карточки {i + 1}/{min(lim, len(todo))}", done=i, total=min(lim, len(todo)))
        h = polite_get(u)
        stat["fetched"] += 1
        r = _parse_4read_page(u, h) if h else None
        if not r:
            skip[u] = lm
            stat["articles"] += 1
            if stat["articles"] % 50 == 0:
                meta["articles"] = skip
                _csave(conn, "4read", meta)
            continue
        r["lastmod"] = lm
        stat["new"] += r["source_id"] not in have
        upsert(conn, [r])
        stat["books"] += 1
    meta["articles"] = skip
    if len(todo) <= lim:
        meta.update(full_done=True, full_at=_now())
    meta["last_run"] = dict(stat, at=_now())
    _csave(conn, "4read", meta)
    return stat


def _probe_4read(c):
    """Карточка 4read -> m3u -> прямые mp3 (подписанные, живут часы). Длительность — «Триває» с карточки."""
    pr = {"ok": False, "error": "", "duration": None, "parts": 1, "unavailable": 0, "order": None, "titles": []}
    c["probe"] = pr
    try:
        h = F._http(c["url"], timeout=20)
        r = _parse_4read_page(c["url"], h)
        m3u = (r or {}).get("raw", {}).get("m3u")
        yt = (r or {}).get("raw", {}).get("youtube") or []
        if not m3u and yt:
            c.setdefault("platform", "YouTube")
            page, c["urls"], c["url"] = c["url"], yt, yt[0]      # F.probe смотрит на c["url"]
            try:
                F.probe(c)
            finally:
                c["url"] = page
            return c
            pr["error"] = "4read: плеера на странице нет"
            return c
        req = urllib.request.Request(m3u, headers={"User-Agent": F.UA, "Referer": c["url"]})
        with urllib.request.urlopen(req, timeout=F.HTTP_TIMEOUT) as f:
            body = f.read().decode("utf-8", "replace")
        urls = [l.strip() for l in body.splitlines() if l.strip().startswith("http")]
        if not urls:
            pr["error"] = "4read: пустой список файлов"
            return c
        c["urls"], c["type"] = urls, "files"
        pr.update(parts=len(urls), duration=r.get("duration_s"),
                  titles=[urllib.parse.urlparse(u).path.rsplit("/", 1)[-1] for u in urls])
        pr["order"] = A().title_order_problem(pr["titles"])
        # файлы на reasd.org отдаются только с Referer 4read (abook get передаёт его yt-dlp); HEAD там 403 — Range-GET
        urllib.request.urlopen(urllib.request.Request(urls[0], headers={"User-Agent": F.UA, "Referer": FOURREAD + "/",
                                                                        "Range": "bytes=0-1023"}),
                               timeout=F.HTTP_TIMEOUT).close()
        pr["ok"] = True
    except Exception as e:
        pr["error"] = f"{type(e).__name__}: {e}"[:200]
    return c


def relang(conn):
    """Пересчитать lang у записей сайтов (у каналов язык задан в sources.json) — после смены lang_guess."""
    ch = {}
    rows = conn.execute("SELECT id, src, author, work, lang, raw FROM src_items WHERE src IN "
                        "('knigavuhe','akniga','archive','4read')").fetchall()
    for i, src, au, wk, lg, raw in rows:
        if src == "archive":
            new = "uk" if lg == "uk" else (lang_guess(wk) if lang_guess(wk) in ("uk", "be") else lg)
        elif src == "4read":
            new = "uk" if lang_guess(au, wk) != "be" else "be"
        else:
            new = lang_guess(au, wk) or lg
        if new != lg:
            ch[i] = new
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.executemany("UPDATE src_items SET lang=? WHERE id=?", [(v, k) for k, v in ch.items()])
    out = {}
    for v in ch.values():
        out[v] = out.get(v, 0) + 1
    return {"checked": len(rows), "changed": len(ch), "to": out}


def _hms(s):
    """'1:58:25' | '42:06' | '123 minutes' | '3600' -> секунды."""
    s = str(s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?::\d{1,2}){1,2}(?:\.\d+)?", s):
        t = 0.0
        for x in s.split(":"):
            t = t * 60 + float(x)
        return t or None
    m = re.match(r"([\d.]+)\s*(min|мин)", s, re.I)
    if m:
        return float(m.group(1)) * 60
    with contextlib.suppress(ValueError):
        return float(s) or None
    return None


def _first(v):
    return (v[0] if v else "") if isinstance(v, list) else (v or "")


_JUNK_CREATOR = re.compile(r"^(?:автор контента|unknown|неизвестн\w*|various|разные|n/?a|-+)$", re.I)


def _archive_row(d):
    ident = d.get("identifier")
    if not ident:
        return None
    title = _txt(_first(d.get("title"))) or ident
    cr = d.get("creator")
    creators = [c for c in (cr if isinstance(cr, list) else [cr] if cr else []) if c and not _JUNK_CREATOR.match(c.strip())]
    author, work = ", ".join(_txt(c) for c in creators[:3]), title
    if not author:
        p = parse_title(title)
        author, work = p["author"], p["work"] or title
    langs = [str(x).lower() for x in (d.get("language") if isinstance(d.get("language"), list) else [d.get("language")])]
    lang = "uk" if any(x in ("ukr", "ukrainian", "українська", "украинский", "uk") for x in langs) else "ru"
    if lang == "ru" and lang_guess(work) in ("uk", "be"):       # language: rus при украинском/белорусском названии
        lang = lang_guess(work)
    col = d.get("collection") or []
    col = col if isinstance(col, list) else [col]
    lv = "librivoxaudio" in col
    desc = d.get("description")
    desc = " ".join(desc) if isinstance(desc, list) else (desc or "")
    subj = d.get("subject")
    subj = subj if isinstance(subj, list) else [subj] if subj else []
    url = f"https://archive.org/details/{ident}"
    return {"source_id": F._key(url), "src": "archive", "platform": "archive.org", "url": url, "urls": [url],
            "channel": "LibriVox" if lv else "archive.org", "title": f"{author} — {work}" if author else work,
            "author": author, "work": work, "reader": "", "lang": lang, "duration_s": _hms(d.get("runtime")),
            "parts": 0, "kind": "files", "availability": "public", "downloadable": 1, "complete_score": None,
            "complete_notes": "состав файлов проверяется при поиске", "views": d.get("downloads"),
            "tags": ", ".join(_txt(x) for x in subj[:12])[:300], "annotation": _short(desc),
            "lastmod": d.get("publicdate"),
            "raw": {"site": "archive", "collection": col[:6], "size": d.get("item_size")}}


def crawl_archive(conn, force=False, max_pages=None):
    """archive.org: scrape API (курсор, по 5000) по русским/украинским аудио (вкл. LibriVox) — ≈ 35 тыс., ≈ 1 мин.
    Повторно — только опубликованное с прошлого полного прохода (publicdate ≥ дата − 3 дня)."""
    meta = _cmeta(conn, "archive")
    if force:
        meta = {}
    q = ARCHIVE_Q
    if meta.get("full_done"):
        since = (datetime.fromisoformat(meta["since"]) - timedelta(days=3)).strftime("%Y-%m-%d")
        q += f" AND publicdate:[{since} TO null]"
        cursor = None
    else:
        cursor = meta.get("cursor")
        meta.setdefault("started", _now())
    stat = {"pages": 0, "rows": 0}
    while True:
        if max_pages is not None and stat["pages"] >= max_pages:
            break
        params = {"q": q, "fields": ARCHIVE_FIELDS, "count": "5000"}
        if cursor:
            params["cursor"] = cursor
        _progress(phase=f"archive.org: {stat['rows']} из {meta.get('total') or '?'}", done=stat["rows"],
                  total=meta.get("total"))
        txt = polite_get("https://archive.org/services/search/v1/scrape?" + urllib.parse.urlencode(params), timeout=120)
        d = json.loads(txt or "{}")
        if d.get("error"):
            raise RuntimeError("archive.org: " + str(d["error"])[:200])
        rows = [r for r in (_archive_row(x) for x in d.get("items") or []) if r]
        upsert(conn, rows)
        stat["pages"] += 1
        stat["rows"] += len(rows)
        if not meta.get("full_done"):
            meta["total"] = meta.get("total") or d.get("total")      # на следующих страницах total — остаток
        cursor = d.get("cursor")
        if not meta.get("full_done"):
            meta["cursor"] = cursor
            _csave(conn, "archive", meta)
        if not cursor:
            if not meta.get("full_done"):
                meta.update(full_done=True, since=meta.get("started") or _now(), cursor=None)
            else:
                meta["since"] = _now()
            break
    meta["last_run"] = dict(stat, at=_now())
    _csave(conn, "archive", meta)
    return stat


# ------------------------------------------------------------------ самообучение: каналы YouTube из живого поиска

def learn_channels(conn, apply=None):
    """Каналы, давшие ≥ min_hits разных живых поисков (find_searches.result: best/choices, прошедшие проверку
    yt-dlp, площадка YouTube), которых нет в sources.json. Режим sources.json `auto_channels.mode`:
    add (по умолчанию) — дописать канал в youtube с auto=true и пометкой, он краулится как остальные;
    suggest — только вернуть список (виден в /api/find/catalog/status); off — ничего."""
    src = load_sources()
    cfg = src.get("auto_channels") or {}
    mode = apply or cfg.get("mode") or "add"
    need = int(cfg.get("min_hits") or 3)
    have = {norm(x) for s in src.get("youtube") or [] for x in [s.get("name") or ""] + list(s.get("aliases") or [])}
    have |= {norm(x) for x in cfg.get("ignore") or []}
    hits = {}
    try:
        rows = conn.execute("SELECT id, result FROM find_searches WHERE status='done' AND result IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        return {"mode": mode, "suggest": [], "added": []}
    for r in rows:
        with contextlib.suppress(Exception):
            res = json.loads(r["result"])
            seen = set()
            for c in [res.get("best")] + list(res.get("choices") or []):
                if not c or not c.get("verified") or c.get("platform") != "YouTube" or not c.get("channel"):
                    continue
                k = norm(c["channel"])
                if k in have or k in seen:
                    continue
                seen.add(k)
                h = hits.setdefault(k, {"channel": c["channel"], "searches": [], "url": c.get("url"), "langs": []})
                h["searches"].append(r["id"])
                h["langs"].append(c.get("lang") or "")
    sugg = sorted((h for h in hits.values() if len(h["searches"]) >= need), key=lambda h: -len(h["searches"]))
    added = []
    if mode == "add" and sugg:
        for h in sugg:
            try:
                info = _ytdlp_cancellable(["-J", "--skip-download", "--no-playlist", h["url"]], 120)
            except F.Cancelled:
                raise
            except Exception as e:
                h["error"] = f"{type(e).__name__}: {e}"[:200]
                continue
            cid = info.get("channel_id")
            if not cid:
                continue
            langs = [x for x in h["langs"] if x]
            ent = {"id": "auto-" + cid[-10:], "name": info.get("channel") or h["channel"],
                   "url": f"https://www.youtube.com/channel/{cid}", "reader": "",
                   "lang": max(set(langs), key=langs.count) if langs else "", "tabs": ["videos", "playlists"],
                   "ttl_days": 7, "auto": True, "aliases": [h["channel"]],
                   "note": f"добавлен автоматически {datetime.now():%d.%m.%Y}: прошёл проверку в "
                           f"{len(h['searches'])} поисках (find_searches {', '.join(map(str, h['searches'][:8]))})"}
            src = load_sources()
            if any(s.get("url") == ent["url"] for s in src.get("youtube") or []):
                continue
            src.setdefault("youtube", []).append(ent)
            F._atomic_json(sources_file(), src)
            added.append(ent)
    out = {"mode": mode, "min_hits": need, "added": added,
           "suggest": [{"channel": h["channel"], "searches": h["searches"][:20], "error": h.get("error")} for h in sugg]}
    _csave(conn, "auto-channels", out, src="-")
    return out


# ------------------------------------------------------------------ произведения: склейка записей (works)

_LAT = [("shch", "щ"), ("sch", "щ"), ("zh", "ж"), ("kh", "х"), ("ch", "ч"), ("sh", "ш"), ("ts", "ц"), ("tz", "ц"),
        ("ph", "ф"), ("th", "т"), ("ck", "к"), ("x", "кс"), ("w", "в"), ("q", "к"), ("c", "к"), ("j", "дж"),
        ("h", "х"), ("b", "б"), ("d", "д"), ("f", "ф"), ("g", "г"), ("k", "к"), ("l", "л"), ("m", "м"), ("n", "н"),
        ("p", "п"), ("r", "р"), ("s", "с"), ("t", "т"), ("v", "в"), ("z", "з")]
_VOW = set("аеиоуыэюяьъaeiouy")
_WSTOP = {"аудиокнига", "аудиокниги", "аудиокнига", "аудиокниги", "аудиоспектакль", "радиоспектакль", "читает",
          "полностью", "сборник", "рассказ", "рассказы", "роман", "повесть"}
_ASTOP = {"автор", "авторов", "коллектив", "контента", "разные", "неизвестныи", "неизвестен", "сборник", "народ",
          "народная", "народные", "сказка", "librivox"}


@functools.lru_cache(maxsize=200000)
def _skel_word(w):
    """Скелет слова для ключа произведения: латиница -> кириллица (грубо), без гласных/знаков — так
    «Тіні забутих предків» = «Тени забытых предков», «Turgenev» = «Тургенев»."""
    if re.search(r"[a-z]", w):
        for a, b in _LAT:
            w = w.replace(a, b)
    w = w.translate(_TR)
    return "".join(ch for ch in w if ch not in _VOW)


@functools.lru_cache(maxsize=200000)
def _title_key(t):
    s = str(t or "")
    s = _PART.sub(" ", s)
    # «Книга 2», «Том 3» — разные произведения цикла: номер остаётся в ключе, даже если он в скобках
    vol = " ".join("к" + m.group(1) for m in re.finditer(r"\b(?:книга|кніга|том|book|volume|vol)\.?\s*(\d{1,3})", s, re.I))
    s = re.sub(r"\b(?:книга|кніга|том|book|volume|vol)\.?\s*\d{1,3}", " ", s, flags=re.I)
    s = re.sub(r"\((?:[^()]{0,60})\)|\[[^\]]{0,60}\]", " ", s)          # (2011), (сборник), [Читает …]
    s = re.sub(r"\b(?:1[89]|20)\d\d\b", " ", s)
    ws = [w for w in norm(s).split() if w not in _WSTOP]
    sk = " ".join(x for x in (_skel_word(w) for w in ws) if x)
    sk = sk if len(sk.replace(" ", "")) >= 3 else fold(" ".join(ws))
    return (sk + " " + vol).strip() if sk else ""


@functools.lru_cache(maxsize=200000)
def _author_toks(a):
    a = re.sub(r"\([^)]*\)", " ", str(a or ""))
    toks = set()
    for w in norm(a).split():
        if len(w) < 3 or w in _ASTOP:
            continue
        sk = _skel_word(w)
        if len(sk) >= 2:
            toks.add(sk)
    return frozenset(toks)


def _rec_rank(r):
    """Лучшая запись произведения: открытая, скачиваемая, проверенная, полная, длинная."""
    return ((r["availability"] != "members") * 16 + bool(r["downloadable"]) * 8 + bool(r["duration_s"]) * 4
            + (r["availability"] == "public") * 2,
            r["complete_score"] if r["complete_score"] is not None else 0.6, r["duration_s"] or 0, r["views"] or 0)


def _pick(vals):
    vals = [v for v in vals if v]
    if not vals:
        return ""
    cyr = [v for v in vals if re.search(r"[а-яёіїєґ]", v, re.I)] or vals
    return max(sorted(set(cyr)), key=lambda v: (cyr.count(v), -len(v)))


def rebuild_works(conn):
    """Склейка src_items в works (полная пересборка, ≈ секунды на 100 тыс.; id произведений стабильны по wkey).
    Ключ: скелет названия (без «Часть N», года, скобок) + пересечение скелетов слов автора; записи без автора
    примыкают к самой большой группе с тем же названием."""
    t0 = time.time()
    rows = conn.execute("SELECT id, src, title, author, work, reader, lang, duration_s, availability, downloadable, "
                        "complete_score, views, genre, annotation, work_id, kind FROM src_items").fetchall()
    by_t = {}
    for r in rows:
        if r["kind"] == "playlist" and not r["author"]:
            continue                                         # подборки каналов — не произведение
        tk = _title_key(r["work"] or r["title"])
        if not tk:
            continue
        by_t.setdefault(tk, []).append(r)
    groups = {}
    for tk, rs in by_t.items():
        clusters = []                                        # [toks, [rows]]
        anon = []
        for r in rs:
            at = _author_toks(r["author"])
            if not at:
                anon.append(r)
                continue
            hit = [c for c in clusters if not c[0].isdisjoint(at)]
            if not hit:
                clusters.append([set(at), [r]])
            else:
                c0 = hit[0]
                for c in hit[1:]:
                    c0[0] |= c[0]
                    c0[1] += c[1]
                    clusters.remove(c)
                c0[0] |= at
                c0[1].append(r)
        if anon:
            if clusters:
                max(clusters, key=lambda c: len(c[1]))[1].extend(anon)
            else:
                clusters.append([set(), anon])
        for toks, rs2 in clusters:
            cnt = {}
            for r in rs2:
                for t in _author_toks(r["author"]):
                    cnt[t] = cnt.get(t, 0) + 1
            surname = max(sorted(cnt), key=lambda t: (cnt[t], len(t))) if cnt else ""
            groups[f"{surname}|{tk}"] = rs2
    cols = ["wkey", "author", "title", "alt_titles", "n_records", "n_public", "best_record", "langs", "annotation",
            "genre", "readers", "duration_s", "updated_at"]
    old = {r[0]: (r[1], tuple(r[2:])) for r in conn.execute(f"SELECT wkey, id, {', '.join(cols[1:-1])} FROM works")}
    t1 = time.time()
    now = _now()
    out, wid_of = [], {}
    for wk, rs in groups.items():
        best = max(rs, key=_rec_rank)
        titles = [r["work"] or r["title"] for r in rs]
        title = _pick(titles)
        alts = sorted({t for t in titles if t and fold(t) != fold(title)}, key=lambda t: (len(t), t))[:10]
        anns = [r["annotation"] for r in rs if r["annotation"]]
        readers = list(dict.fromkeys(x.strip() for r in rs for x in (r["reader"] or "").split(",") if x.strip()))
        out.append({"wkey": wk, "author": _pick([r["author"] for r in rs]), "title": title,
                    "alt_titles": json.dumps(alts, ensure_ascii=False), "n_records": len(rs),
                    "n_public": sum(1 for r in rs if r["availability"] != "members" and r["downloadable"]),
                    "best_record": best["id"], "langs": ",".join(sorted({r["lang"] for r in rs if r["lang"]})),
                    "annotation": max(anns, key=lambda a: (len(a), a)) if anns else "", "genre": _pick([r["genre"] for r in rs]),
                    "readers": ", ".join(readers[:12])[:400], "duration_s": best["duration_s"], "updated_at": now,
                    "_ids": [r["id"] for r in rs]})
    # пишем только изменившееся: на 200 тыс. записей полная перезапись держала бы блокировку записи минуту
    changed = 0
    with A()._WRITE_LOCK, A()._tx(conn):
        for w in out:
            o = old.get(w["wkey"])
            if o:
                wid = o[0]
                if o[1] != tuple(w[c] for c in cols[1:-1]):
                    conn.execute(f"UPDATE works SET {', '.join(c + '=?' for c in cols[1:])} WHERE id=?",
                                 [w[c] for c in cols[1:]] + [wid])
                    conn.execute("DELETE FROM works_fts WHERE rowid=?", (wid,))
                    conn.execute("INSERT INTO works_fts(rowid, norm) VALUES(?,?)", (wid, _works_text(w)))
                    changed += 1
            else:
                wid = conn.execute(f"INSERT INTO works({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                                   [w[c] for c in cols]).lastrowid
                conn.execute("INSERT INTO works_fts(rowid, norm) VALUES(?,?)", (wid, _works_text(w)))
                changed += 1
            w["id"] = wid
            for i in w["_ids"]:
                wid_of[i] = wid
        gone = [(old[k][0],) for k in old.keys() - groups.keys()]
        conn.executemany("DELETE FROM works WHERE id=?", gone)
        conn.executemany("DELETE FROM works_fts WHERE rowid=?", gone)
        conn.executemany("UPDATE src_items SET work_id=? WHERE id=?",
                         [(wid_of.get(r["id"]), r["id"]) for r in rows if r["work_id"] != wid_of.get(r["id"])])
        conn.execute("INSERT OR REPLACE INTO src_crawls(source, fetched_at, n, meta) VALUES('_works',?,?,?)",
                     (now, len(out), json.dumps({"records": len(rows), "removed": len(gone), "changed": changed,
                                                 "seconds": round(time.time() - t0, 1)})))
    return {"works": len(out), "records": len(rows), "changed": changed, "removed": len(gone),
            "group_s": round(t1 - t0, 1), "seconds": round(time.time() - t0, 1)}


def _works_text(w):
    """Текст works_fts: свёртка fold() + скелет (без гласных) автора и названий — рус/укр/латиница сходятся."""
    t = " ".join([w["author"], w["title"], " ".join(json.loads(w["alt_titles"]))])
    return fold(t + " " + w["readers"]) + " | " + " ".join(_skel_word(x) for x in norm(t).split())


_JUNK_TITLE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]|#\\w")


def search_works(conn, q, limit=20, include_members=False, per_work=12):
    """Поиск по произведениям (works_fts): одна строка = книга, внутри — записи (карточки как у search).
    Два прохода FTS: обычный (fold) и по скелету слов — «Тіні забутих предків» находит «Тени забытых предков»."""
    t0 = time.perf_counter()
    rows = _fts(conn, q, limit, table="works")
    # скелеты — только если обычный проход почти пуст (рус/укр/латиница), все слова обязательны и без обрезки
    sk = [x for x in (_skel_word(w) for w in norm(q).split() if w not in _STOP) if len(x) >= 3]
    if len(rows) < 3 and sk and (len(sk) >= 2 or len(sk[0]) >= 5):
        ids = {r["id"] for r in rows}
        rows += [r for r in _fts(conn, " ".join(sk), limit, table="works", exact=True) if r["id"] not in ids]
    titles = [q]
    scored = []
    for w in rows:
        if not w["n_public"] and not include_members:
            continue
        rel = F.relevance(f"{w['author']} {w['title']} {' '.join(json.loads(w['alt_titles'] or '[]'))}", titles)
        s = 60 * rel + 4 * math.log2(1 + w["n_records"]) + (6 if w["n_public"] else -10)
        s += 3 if ("ru" in w["langs"] or "uk" in w["langs"]) else 0
        if _JUNK_TITLE.search(w["title"] or ""):                  # эмодзи, хэштеги — ролики, а не книги
            s -= 30
        if w["duration_s"] and w["duration_s"] < 900:              # меньше 15 минут — анонс, нарезка, песня
            s -= 20
        scored.append((s, w))
    scored.sort(key=lambda x: -x[0])
    lib = _library_keys(conn)
    out = []
    for s, w in scored[:limit]:
        recs = conn.execute("SELECT * FROM src_items WHERE work_id=?" + ("" if include_members else
                            " AND availability<>'members'") + " ORDER BY id=? DESC, downloadable DESC, "
                            "duration_s DESC LIMIT ?", (w["id"], w["best_record"], per_work)).fetchall()
        cards = [pub(to_cand(r), r, lib=lib.get(r["source_id"]), probe=_probe_cached_row(conn, r["url"])) for r in recs]
        out.append({"work_id": w["id"], "author": w["author"], "title": w["title"],
                    "alt_titles": json.loads(w["alt_titles"] or "[]"), "langs": [x for x in w["langs"].split(",") if x],
                    "n_records": w["n_records"], "n_public": w["n_public"], "annotation": w["annotation"],
                    "genre": w["genre"], "readers": w["readers"], "duration": w["duration_s"],
                    "best_record": w["best_record"], "score": round(s, 1),
                    "in_library": next((c["in_library"] for c in cards if c.get("in_library")), None),
                    "records": cards})
    return out, round((time.perf_counter() - t0) * 1000, 1)


# ------------------------------------------------------------------ обход сайтов: запуск одного источника

def crawl_wide(conn, sid, force=False, max_pages=None):
    _TLS.sid = sid
    _progress(phase=f"{sid}: старт", done=0, total=None, started=_now(), error=None)
    try:
        if sid in _LISTING:
            st = crawl_site(conn, sid, force=force, max_pages=max_pages)
        elif sid == "akniga-sitemap":
            st = crawl_akniga_sitemap(conn, force=force, max_pages=max_pages)
        elif sid == "archive":
            st = crawl_archive(conn, force=force, max_pages=max_pages)
        elif sid == "4read":
            st = crawl_4read(conn, force=force, max_pages=max_pages)
        else:
            raise ValueError(sid)
        _progress(phase=f"{sid}: готово", finished=_now(), result=st)
        return st
    except F.Cancelled:
        _progress(phase=f"{sid}: отменено (курсор сохранён)", finished=_now())
        raise
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:300]
        _progress(phase=f"{sid}: ошибка", error=msg, finished=_now())
        meta = _cmeta(conn, sid)
        _csave(conn, sid, meta, error=msg, src="akniga" if sid == "akniga-sitemap" else sid)
        raise


# ------------------------------------------------------------------ старт

FTS_VERSION = "2"          # меняется вместе с norm/fold/_fts_text — тогда индекс перестраивается на старте


def reindex(conn):
    r = conn.execute("SELECT meta FROM src_crawls WHERE source='_fts'").fetchone()
    if r and r[0] == FTS_VERSION:
        return 0
    rows = conn.execute("SELECT * FROM src_items").fetchall()
    with A()._WRITE_LOCK, A()._tx(conn):
        conn.execute("DELETE FROM src_fts")
        for x in rows:
            conn.execute("INSERT INTO src_fts(rowid, norm) VALUES(?,?)", (x["id"], _fts_text(dict(x))))
        conn.execute("INSERT OR REPLACE INTO src_crawls(source, fetched_at, n, meta) VALUES('_fts',?,?,?)",
                     (_now(), len(rows), FTS_VERSION))
    return len(rows)


def startup(conn):
    b = migrate(conn)
    with contextlib.suppress(Exception):
        reindex(conn)
    n = 0
    with contextlib.suppress(Exception):
        load_sources()
        n = import_manifests(conn)
    with contextlib.suppress(Exception):
        if not conn.execute("SELECT 1 FROM works LIMIT 1").fetchone() and \
                conn.execute("SELECT 1 FROM src_items LIMIT 1").fetchone():
            rebuild_works(conn)
    auto = os.environ.get("ABOOK_CATALOG_AUTO", "1") != "0" and not A().TEST_MODE and not F.NO_NET
    if auto:
        start_crawl(auto=True)
    return {"backup": str(b) if b else None, "imported": n, "auto_crawl": auto}


# ------------------------------------------------------------------ CLI: обход в фоне на любой базе

def _cli():
    """python3 abook_catalog.py crawl --db ~/abook/library.db [--source knigavuhe|akniga|akniga-sitemap|archive|
    youtube|sites|<id канала>] [--max-pages N] [--force] [--serial]
    python3 abook_catalog.py works|status|bench --db <путь> [--q запрос]
    Обход возобновляем: Ctrl-C/SIGTERM — страница дописывается, курсор сохранён, повторный запуск продолжит."""
    import argparse     # noqa: PLC0415
    import importlib.machinery  # noqa: PLC0415
    import importlib.util  # noqa: PLC0415
    ap = argparse.ArgumentParser(prog="abook_catalog.py", description=_cli.__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["crawl", "works", "status", "bench", "learn", "relang"])
    ap.add_argument("--db", required=True)
    ap.add_argument("--source")
    ap.add_argument("--max-pages", type=int)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--serial", action="store_true", help="сайты по очереди (по умолчанию — параллельно, разные хосты)")
    ap.add_argument("--q", action="append")
    a = ap.parse_args()
    here = Path(__file__).resolve().parent
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(here))
    ld = importlib.machinery.SourceFileLoader("abook_main", str(here / "abook"))
    spec = importlib.util.spec_from_loader("abook_main", ld)
    ab = importlib.util.module_from_spec(spec)
    sys.modules["abook_main"] = ab
    ld.exec_module(ab)                       # abook сам делает abook_find.bind(globals())
    ab.DB_PATH = Path(a.db).expanduser().resolve()
    if ab.DB_PATH != Path.home() / "abook" / "library.db":
        ab.TEST_MODE = True
    F.bind(vars(ab))
    if __name__ == "__main__":                 # этот модуль — __main__; abook_find._cat() должен видеть то же состояние
        sys.modules["abook_catalog"] = sys.modules["__main__"]
    conn = ab.db_connect()
    migrate(conn)
    if a.cmd == "status":
        st = crawl_status(conn)
        st.pop("per", None)
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return
    if a.cmd == "relang":
        print(relang(conn), rebuild_works(conn))
        return
    if a.cmd == "works":
        print(rebuild_works(conn))
        return
    if a.cmd == "learn":
        print(json.dumps(learn_channels(conn, apply=a.source), ensure_ascii=False, indent=1))
        return
    if a.cmd == "bench":
        qs = a.q or ["тени забытых предков", "пикник на обочине", "стивен кинг", "мастер и маргарита", "война",
                     "тіні забутих предків", "гарри поттер", "достоевский идиот", "космос", "шерлок холмс"]
        for q in qs:
            for fn, nm in ((search, "записи"), (search_works, "произв.")):
                fn(conn, q, 20)
                ms = sorted(fn(conn, q, 20)[1] for _ in range(5))
                print(f"{nm:8} {q[:30]:30} {len(fn(conn, q, 20)[0]):3} шт.  медиана {ms[2]:7.1f} мс  макс {ms[-1]:7.1f}")
        return

    def stop(*_):
        _CRAWL["cancel"] = True
        print("\nотмена: дописываю страницу и сохраняю курсор…", flush=True)
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    _CRAWL.update(running=True, started=_now(), cancel=False, log=[], results={}, per={})
    t0 = time.time()
    th = threading.Thread(target=_crawl_worker, args=(a.source, a.force, False, a.max_pages, not a.serial), daemon=True)
    th.start()
    shown = 0
    while th.is_alive():
        th.join(15)
        for line in _CRAWL["log"][shown:]:
            print(f"[{time.time() - t0:6.0f} с] {line}", flush=True)
        shown = len(_CRAWL["log"])
        per = "; ".join(f"{v.get('phase')}" for v in (_CRAWL.get("per") or {}).values() if not v.get("finished"))
        if per:
            n = conn.execute("SELECT count(*) FROM src_items").fetchone()[0]
            print(f"[{time.time() - t0:6.0f} с] записей {n} | {per}", flush=True)
    for line in _CRAWL["log"][shown:]:
        print(f"[{time.time() - t0:6.0f} с] {line}", flush=True)
    print(f"готово за {time.time() - t0:.0f} с; записей "
          f"{conn.execute('SELECT count(*) FROM src_items').fetchone()[0]}, произведений "
          f"{conn.execute('SELECT count(*) FROM works').fetchone()[0]}")


if __name__ == "__main__":
    _cli()
