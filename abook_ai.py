"""abook_ai — listener profiles, the onboarding questionnaire («Анкета») and Claude recommendations
for `abook review`.

Loaded by ~/.local/bin/abook (`AI.bind(globals())`): every DB helper, the profile context
(_PROFILE/_pid/_profile_ctx), build_aidoc and refresh_outputs live there; this module only adds
features on top. Python stdlib only.

AI step: the app never talks to the network itself. It runs the local Claude Code CLI headless
(`claude -p --model opus --output-format stream-json --json-schema …`) with only WebSearch/WebFetch
enabled, prompt on stdin, in a background thread (one run per profile), and stores every run in
the `ai_runs` table. Runs happen only on demand (buttons), never automatically.
"""
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

A = None          # abook's globals, see bind()


class _NS:
    __slots__ = ("_g",)

    def __init__(self, g):
        object.__setattr__(self, "_g", g)

    def __getattr__(self, k):
        try:
            return self._g[k]
        except KeyError:
            raise AttributeError(k) from None


def bind(g):
    global A
    A = _NS(g)


# ------------------------------------------------------------------ settings

AI_MODEL = os.environ.get("ABOOK_AI_MODEL", "opus")
AI_TIMEOUT = int(os.environ.get("ABOOK_AI_TIMEOUT", "360"))     # per Claude call, seconds
AI_BUDGET_USD = 5.0                                              # hard cap per call (--max-budget-usd)
AI_TOOLS = "WebSearch,WebFetch"
AI_DENY = "Bash,Edit,Write,MultiEdit,NotebookEdit,Read,Glob,Grep,Task,Agent,TodoWrite,KillShell,BashOutput"
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
DEFAULT_PID = 1
NAME_MAX = 40

# ------------------------------------------------------------------ vocabularies (all UI chips)

OPTIONS = {
    "book_like": ["сюжет", "атмосфера", "идеи", "герои", "язык/стиль", "мир/сеттинг", "концовка", "юмор",
                  "мрачность", "напряжение", "эмоции", "реализм/абсурд", "темп", "философия", "короткая форма"],
    "book_dislike": ["затянуто", "скучно", "слишком мрачно", "слишком сложно", "банально", "плохой перевод",
                     "плохой чтец", "неприятные герои", "слабая концовка", "морализаторство", "много воды",
                     "наивно", "не мой жанр"],
    "genres": ["антиутопия", "научная фантастика", "фэнтези", "абсурд/сюрреализм", "детектив", "триллер",
               "хоррор/мистика", "классика", "современная проза", "историческое", "приключения",
               "философская проза", "юмор/сатира", "постапокалипсис", "психологическая проза", "военная проза",
               "нон-фикшн", "биографии", "драматургия", "поэзия"],
    "length": ["короткое (до 2 ч)", "среднее (2–10 ч)", "длинное (10+ ч)"],
    "format": ["аудиокнига", "радиоспектакль", "рассказы", "лекции/нон-фикшн"],
    "lang": ["ru", "uk", "en"],
    "listen": ["дорога", "спорт", "перед сном", "фоном", "прогулка", "домашние дела", "в тишине, внимательно"],
    "film_like": ["сюжет", "визуал", "музыка", "атмосфера", "твист", "персонажи", "идея", "актёры", "диалоги",
                  "напряжение", "юмор", "эмоции", "мрачность", "масштаб"],
    "film_genres": ["научная фантастика", "триллер", "детектив", "драма", "хоррор", "комедия", "фэнтези",
                    "боевик", "криминал", "психологическое", "артхаус", "антиутопия", "исторический",
                    "военный", "документальное", "анимация"],
    "series_genres": ["криминал", "детектив", "фантастика", "драма", "триллер", "комедия", "фэнтези",
                      "исторический", "мини-сериал", "антиутопия", "хоррор", "документальный", "аниме"],
    "game_like": ["сюжет", "атмосфера", "мир/лор", "геймплей", "свобода выбора", "персонажи", "музыка",
                  "визуал", "головоломки", "реиграбельность", "сложность", "кооператив/друзья", "твист", "идея"],
    "game_genres": ["RPG", "экшен", "шутер", "стратегия", "головоломка", "хоррор", "приключение/квест",
                    "симулятор", "песочница/выживание", "roguelike", "инди", "метроидвания", "визуальная новелла",
                    "спорт/гонки", "MMO", "карточные/настольные"],
    "travel_types": ["пляж", "архитектура", "музеи", "природа/горы", "еда", "ночная жизнь", "история",
                     "города-мегаполисы", "тихие места"],
    "travel_pace": ["спокойно", "насыщенно", "по-разному"],
    "music": ["классика", "рок", "метал", "рэп/хип-хоп", "электроника", "джаз", "саундтреки", "инди", "поп",
              "фолк", "эмбиент", "панк", "шансон/бард"],
    "interests": ["программирование/CS", "математика", "физика", "философия", "история", "психология",
                  "экономика", "биология", "космос", "искусство", "лингвистика", "политика", "спорт"],
    "education": ["среднее", "колледж", "высшее", "два высших", "учёная степень", "учусь"],
    "family": ["один/одна", "в паре", "в браке", "есть дети", "дети взрослые", "с родителями"],
}
WORLDVIEW = [
    ("faith", "Вера и наука", ["научная картина мира", "верю в Бога", "ищу, сомневаюсь", "агностик",
                               "не задумываюсь"]),
    ("outlook", "Взгляд на жизнь", ["скорее оптимист", "скорее пессимист", "реалист", "зависит от дня"]),
    ("idea_story", "Что важнее в книге", ["идея", "история", "язык и стиль", "всё вместе"]),
    ("dark", "Мрачные темы (смерть, насилие, безысходность)",
     ["чем мрачнее, тем лучше", "нормально, если оправдано", "в меру", "избегаю"]),
]

# ------------------------------------------------------------------ small helpers


def _now():
    return A.now_iso()


def _s(v, n=300):
    return re.sub(r"[ \t]+", " ", str(v if v is not None else "").replace("\r\n", "\n")).strip()[:n]


def _line(v, n=300):
    return A._one_line(v)[:n]


def _nt(s):
    """Normalised title/author for fuzzy matching: lower, ё=е, no quotes/punctuation."""
    s = A._norm(s)
    s = re.sub(r"[«»\"'“”„()\[\]{}.,:;!?…/\\|_*#-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _surnames(a):
    return {w for w in _nt(a).split() if len(w) >= 3}


def _tri_set(s):
    out = set()
    for w in s.split():
        w = f" {w} "
        out |= {w[i:i + 3] for i in range(len(w) - 2)}
    return out


def same_book(a_author, a_title, b_author, b_title):
    """Fuzzy «is this the same book» (ё=е, case/punctuation-insensitive, subtitle/edition tails ok)."""
    ta, tb = _nt(a_title), _nt(b_title)
    if not ta or not tb:
        return False
    sa, sb = _surnames(a_author), _surnames(b_author)
    auth_known = bool(sa and sb)
    auth_ok = bool(sa & sb) or any(x[:5] == y[:5] for x in sa for y in sb if len(x) >= 5 and len(y) >= 5)
    if auth_known and not auth_ok:
        return False
    if ta == tb:
        return True
    short, long_ = sorted((ta, tb), key=len)
    if len(short) >= 4 and (f" {short} " in f" {long_} ") and (auth_ok or len(short) >= 12):
        return True
    x, y = _tri_set(ta), _tri_set(tb)
    dice = 2 * len(x & y) / ((len(x) + len(y)) or 1)
    return dice >= (0.8 if auth_ok else 0.92)


def _hue(pid, name):
    h = int(hashlib.md5(f"{pid}:{name}".encode()).hexdigest()[:6], 16)
    return (h * 7) % 360


# ------------------------------------------------------------------ profiles


def get_profile(conn, pid):
    r = conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def _clean_name(name):
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise ValueError("Введите имя профиля")
    if len(name) > NAME_MAX:
        raise ValueError(f"Имя профиля — не длиннее {NAME_MAX} символов")
    return name


def _unique_slug(conn, name, exclude=None):
    base = A._translit_slug(name, 40)
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM profiles WHERE slug=? AND id IS NOT ?", (slug, exclude)).fetchone():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _name_taken(conn, name, exclude=None):
    for r in conn.execute("SELECT id, name FROM profiles"):
        if r["id"] != exclude and A._norm(r["name"]) == A._norm(name):
            return True
    return False


def profiles_payload(conn):
    rows = conn.execute("""
        SELECT p.*, (SELECT count(*) FROM reviews r WHERE r.profile_id=p.id) AS nrev,
               (SELECT count(*) FROM queue q WHERE q.profile_id=p.id) AS nq,
               (SELECT status FROM questionnaire WHERE profile_id=p.id) AS qstatus,
               (SELECT source FROM questionnaire WHERE profile_id=p.id) AS qsource,
               (SELECT max(finished) FROM ai_runs a WHERE a.profile_id=p.id AND a.status='done') AS last_ai
        FROM profiles p ORDER BY p.is_default DESC, p.id""").fetchall()
    out = []
    for r in rows:
        full, lite = A._aidoc_names(conn, r["id"])
        out.append({"id": r["id"], "name": r["name"], "slug": r["slug"], "is_default": bool(r["is_default"]),
                    "initial": (r["name"][:1] or "?").upper(), "hue": _hue(r["id"], r["slug"]),
                    "reviews": r["nrev"], "queue": r["nq"], "created": r["created"],
                    "questionnaire": {"status": r["qstatus"] or "none", "source": r["qsource"] or ""},
                    "last_ai": r["last_ai"], "running": r["id"] in _JOBS, "aidoc": full, "aidoc_lite": lite})
    return {"profiles": out, "active": A._pid(), "default": DEFAULT_PID}


def create_profile(conn, name):
    name = _clean_name(name)
    with A._WRITE_LOCK:
        with A._tx(conn):
            if _name_taken(conn, name):
                raise ValueError("Профиль с таким именем уже есть")
            now = _now()
            cur = conn.execute("INSERT INTO profiles(name,slug,is_default,created,updated) VALUES(?,?,0,?,?)",
                               (name, _unique_slug(conn, name), now, now))
            pid = cur.lastrowid
        with A._profile_ctx(pid):
            A.refresh_outputs(conn, "profile")
    return pid


def rename_profile(conn, pid, name):
    name = _clean_name(name)
    with A._WRITE_LOCK:
        prof = get_profile(conn, pid)
        if not prof:
            raise ValueError("Профиль не найден")
        if name == prof["name"]:
            return
        old_names = A._aidoc_names(conn, pid)
        with A._tx(conn):
            if _name_taken(conn, name, exclude=pid):
                raise ValueError("Профиль с таким именем уже есть")
            slug = prof["slug"] if prof["is_default"] else _unique_slug(conn, name, exclude=pid)
            conn.execute("UPDATE profiles SET name=?, slug=?, updated=? WHERE id=?", (name, slug, _now(), pid))
        new_names = A._aidoc_names(conn, pid)
        if new_names != old_names:
            _remove_docs(old_names)
        with A._profile_ctx(pid):
            A.refresh_outputs(conn, "profile")


def _remove_docs(names):
    for n in names:
        with contextlib.suppress(Exception):
            if A._probe_dir(A.OUT_DIR):
                (A.OUT_DIR / n).unlink(missing_ok=True)


def export_profile_obj(conn, pid):
    with A._profile_ctx(pid):
        d = A.export_reviews_obj(conn)
    d.pop("exported", None)
    d.pop("tags", None)
    prof = get_profile(conn, pid) or {}
    q = get_questionnaire(conn, pid)
    runs = [_run_row(r, full=True) for r in conn.execute(
        "SELECT * FROM ai_runs WHERE profile_id=? AND status='done' ORDER BY id", (pid,))]
    return {"profile": {k: prof.get(k) for k in ("id", "name", "slug", "is_default", "created", "updated")},
            **d, "questionnaire": q, "ai_runs": runs}


def export_all(conn):
    """Backup object (reviews.json, .reviews.json, snapshots): top level = the default profile in the
    old v2 shape (so old readers still work) + `profiles` with every profile's full data."""
    with A._profile_ctx(DEFAULT_PID):
        top = A.export_reviews_obj(conn)
    top["version"] = 3
    top["profiles"] = [export_profile_obj(conn, r[0]) for r in conn.execute("SELECT id FROM profiles ORDER BY id")]
    return top


def delete_profile(conn, pid, confirm):
    with A._WRITE_LOCK:
        prof = get_profile(conn, pid)
        if not prof:
            raise ValueError("Профиль не найден")
        if prof["is_default"]:
            raise ValueError("Основной профиль удалить нельзя (его файл для ИИ — главный)")
        if A._norm(str(confirm or "").strip()) != A._norm(prof["name"]):
            raise ValueError("Для подтверждения введите имя профиля")
        if pid in _JOBS:
            raise ValueError("Сейчас идёт подбор ИИ для этого профиля — отмените его сначала")
        blob = json.dumps(export_profile_obj(conn, pid), ensure_ascii=False, indent=2) + "\n"
        d = A.snapshots_dir()
        d.mkdir(parents=True, exist_ok=True)
        backup = d / f"profile-{prof['slug']}-deleted-{datetime.now():%Y%m%d-%H%M%S}.json"
        A._atomic_write_text(backup, blob)
        names = A._aidoc_names(conn, pid)
        with A._tx(conn):
            for t in ("reviews", "review_history", "item_tags", "queue", "questionnaire", "ai_runs"):
                conn.execute(f"DELETE FROM {t} WHERE profile_id=?", (pid,))
            conn.execute("DELETE FROM profiles WHERE id=?", (pid,))
        _remove_docs(names)
        with A._profile_ctx(DEFAULT_PID):
            out = A.refresh_outputs(conn, "profile")
    return {"backup": str(backup), "warnings": out["warnings"], "out": out["out"]}


# ------------------------------------------------------------------ questionnaire

_ENTRY_LISTS = ("books_liked", "books_disliked", "films", "series", "games")


def _chips(v, n=40):
    out, seen = [], set()
    for x in (v if isinstance(v, list) else []):
        x = _s(x, 80)
        if x and A._norm(x) not in seen:
            seen.add(A._norm(x))
            out.append(x)
    return out[:n]


def _rating(v):
    if v in (None, ""):
        return None
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v if 0 <= v <= 10 else None


def _entry(e):
    if not isinstance(e, dict):
        return None
    d = {"id": _s(e.get("id"), 160) or None, "author": _s(e.get("author"), 200),
         "title": _s(e.get("title"), 300), "why": _chips(e.get("why"), 20),
         "rating": _rating(e.get("rating")), "comment": _s(e.get("comment"), 400),
         "kind": "author" if e.get("kind") == "author" else "book"}
    if d["id"] and not d["title"]:
        d["title"] = d["id"]
    return d if d["title"] else None


LANG_RU = {"ru": "русский", "uk": "украинский", "en": "английский", "both": "русский и украинский на равных"}


def lang_weights(conn, pid):
    """Баллы языка записи для поиска и подбора по анкете профиля. По умолчанию русский и украинский на равных (+15),
    английский — «немного» (+3, примерно один совет из пяти). Главный язык ru|uk — второму +10; английский
    «охотно» +8, «нет» −10."""
    p = ((get_questionnaire(conn, pid) or {}).get("answers") or {}).get("prefs") or {}
    main, en = p.get("lang_main") or "both", p.get("en_level") or "немного"
    w = {"ru": 15, "uk": 15, "en": {"немного": 3, "охотно": 8, "нет": -10}.get(en, 3)}
    if main in ("ru", "uk"):
        w["uk" if main == "ru" else "ru"] = 10
    return w


def normalize_answers(a, prev=None):
    """Whitelist + limits. Unknown keys are dropped; `brief` is kept from the stored answers."""
    a = a if isinstance(a, dict) else {}
    out = {}
    for k in _ENTRY_LISTS:
        out[k] = [x for x in (_entry(e) for e in (a.get(k) or [])[:60]) if x]
    p = a.get("prefs") or {}
    out["prefs"] = {"genres": _chips(p.get("genres")), "genres_text": _s(p.get("genres_text"), 300),
                    "length": _chips(p.get("length")), "format": _chips(p.get("format")),
                    "lang": _chips(p.get("lang")), "listen": _chips(p.get("listen")),
                    "lang_main": p.get("lang_main") if p.get("lang_main") in ("ru", "uk", "both") else "",
                    "en_level": p.get("en_level") if p.get("en_level") in ("нет", "немного", "охотно") else "",
                    "narrators": _s(p.get("narrators"), 300)}
    out["film_genres"] = _chips(a.get("film_genres"))
    out["series_genres"] = _chips(a.get("series_genres"))
    out["game_genres"] = _chips(a.get("game_genres"))
    t = a.get("travel") or {}
    out["travel"] = {"been": _chips(t.get("been"), 80), "want": _chips(t.get("want"), 80),
                     "types": _chips(t.get("types")), "pace": _s(t.get("pace"), 40), "text": _s(t.get("text"), 400)}
    m = a.get("music") or {}
    out["music"] = {"chips": _chips(m.get("chips")), "text": _s(m.get("text"), 500)}
    i = a.get("interests") or {}
    out["interests"] = {"chips": _chips(i.get("chips")), "text": _s(i.get("text"), 500)}
    ab = a.get("about") or {}
    out["about"] = {"name": _s(ab.get("name"), NAME_MAX), "age": _s(ab.get("age"), 20),
                    "education": _chips(ab.get("education"), 6), "education_text": _s(ab.get("education_text"), 200),
                    "profession": _s(ab.get("profession"), 200), "location": _s(ab.get("location"), 200),
                    "family": _chips(ab.get("family"), 8), "family_text": _s(ab.get("family_text"), 200)}
    w = a.get("worldview") or {}
    out["worldview"] = {}
    for k, _, opts in WORLDVIEW:
        x = w.get(k) or {}
        v = _s(x.get("v"), 80)
        out["worldview"][k] = {"v": v if v in opts else "", "text": _s(x.get("text"), 300)}
    x = a.get("extra") or {}
    out["extra"] = {"text": _s(x.get("text"), 2000), "avoid_authors": _chips(x.get("avoid_authors"), 40),
                    "avoid_topics": _chips(x.get("avoid_topics"), 40), "darkness": _s(x.get("darkness"), 60),
                    "where": _chips(x.get("where")), "hours": _s(x.get("hours"), 40),
                    "qa": [{"q": _s(e.get("q"), 300), "options": [_s(o, 80) for o in (e.get("options") or [])][:5],
                            "a": _s(e.get("a"), 300)}
                           for e in (x.get("qa") or [])[:12] if isinstance(e, dict) and _s(e.get("q"))]}
    brief = (prev or {}).get("brief") or a.get("brief")
    if brief:
        out["brief"] = _s(brief, 20000)
    if len(json.dumps(out, ensure_ascii=False)) > 200_000:
        raise ValueError("Анкета слишком большая")
    return out


def _entry_text(e, lite=False):
    if e.get("kind") == "author":
        t = f"автор целиком: {e['title']}"
    else:
        t = (f"{e['author']} — " if e.get("author") else "") + f"«{e['title']}»"
    if e.get("id"):
        t += f" [{e['id']}]"
    if e.get("rating") is not None:
        t += f" {e['rating']}/10"
    if e.get("why"):
        t += f" ({', '.join(e['why'])})"
    if e.get("comment"):
        t += f" — «{_line(e['comment'], 160 if lite else 400)}»"
    return t


def answers_lines(a, lite=False, with_brief=True):
    """[(key, label, text)] — the compact, deterministic rendering used by the summary step,
    the AI document (§1) and the prompt. Empty answers produce no line."""
    a = a or {}
    L = []

    def add(key, label, text):
        if text:
            L.append((key, label, text))

    def join(*parts):
        return "; ".join(p for p in parts if p)

    add("books_liked", "Понравившиеся книги", "; ".join(_entry_text(e, lite) for e in a.get("books_liked") or []))
    add("books_disliked", "Не понравились", "; ".join(_entry_text(e, lite) for e in a.get("books_disliked") or []))
    p = a.get("prefs") or {}
    add("prefs", "Книжные предпочтения", join(
        "жанры: " + ", ".join(p["genres"]) if p.get("genres") else "",
        p.get("genres_text", ""),
        "длина: " + ", ".join(p["length"]) if p.get("length") else "",
        "формат: " + ", ".join(p["format"]) if p.get("format") else "",
        "язык: " + ", ".join(p["lang"]) if p.get("lang") else "",
        "главный язык: " + LANG_RU.get(p["lang_main"], p["lang_main"]) if p.get("lang_main") else "",
        "английский: " + p["en_level"] if p.get("en_level") else "",
        "слушает: " + ", ".join(p["listen"]) if p.get("listen") else "",
        "любимые чтецы: " + p["narrators"] if p.get("narrators") else ""))
    add("films", "Фильмы", join("; ".join(_entry_text(e, lite) for e in a.get("films") or []),
                                "жанры кино: " + ", ".join(a["film_genres"]) if a.get("film_genres") else ""))
    add("series", "Сериалы", join("; ".join(_entry_text(e, lite) for e in a.get("series") or []),
                                  "жанры сериалов: " + ", ".join(a["series_genres"]) if a.get("series_genres") else ""))
    add("games", "Видеоигры", join("; ".join(_entry_text(e, lite) for e in a.get("games") or []),
                                  "жанры игр: " + ", ".join(a["game_genres"]) if a.get("game_genres") else ""))
    t = a.get("travel") or {}
    add("travel", "Путешествия", join(
        "был(а): " + ", ".join(t["been"]) if t.get("been") else "",
        "хочет: " + ", ".join(t["want"]) if t.get("want") else "",
        "тип отдыха: " + ", ".join(t["types"]) if t.get("types") else "",
        "темп: " + t["pace"] if t.get("pace") else "", t.get("text", "")))
    m = a.get("music") or {}
    add("music", "Музыка", join(", ".join(m.get("chips") or []), m.get("text", "")))
    i = a.get("interests") or {}
    add("interests", "Интересы", join(", ".join(i.get("chips") or []), i.get("text", "")))
    ab = a.get("about") or {}
    add("about", "О себе", join(
        "профессия/сфера: " + ab["profession"] if ab.get("profession") else "",
        "живёт: " + ab["location"] if ab.get("location") else "",
        "имя: " + ab["name"] if ab.get("name") else "",
        "возраст: " + ab["age"] if ab.get("age") else "",
        "образование: " + ", ".join(ab.get("education") or []) + (f" ({ab['education_text']})" if ab.get("education_text") else "")
        if (ab.get("education") or ab.get("education_text")) else "",
        "семья: " + ", ".join(ab.get("family") or []) + (f" ({ab['family_text']})" if ab.get("family_text") else "")
        if (ab.get("family") or ab.get("family_text")) else ""))
    w = a.get("worldview") or {}
    wl = []
    for k, label, _ in WORLDVIEW:
        x = w.get(k) or {}
        if x.get("v") or x.get("text"):
            wl.append(f"{label.split(' (')[0].lower()}: " + ", ".join(v for v in (x.get("v"), x.get("text")) if v))
    add("worldview", "Мировоззрение", "; ".join(wl))
    x = a.get("extra") or {}
    add("extra", "Что ещё важно", join(
        "не предлагать авторов: " + ", ".join(x["avoid_authors"]) if x.get("avoid_authors") else "",
        "не предлагать темы: " + ", ".join(x["avoid_topics"]) if x.get("avoid_topics") else "",
        "мрачность: " + x["darkness"] if x.get("darkness") else "",
        "где слушает: " + ", ".join(x["where"]) if x.get("where") else "",
        "часов в неделю: " + x["hours"] if x.get("hours") else "",
        x.get("text", ""),
        "; ".join(f"{e['q']} — {e['a']}" for e in x.get("qa") or [] if e.get("a"))))
    if with_brief and a.get("brief"):
        add("brief", "Из брифа", _line(a["brief"], 20000))
    return L


def get_questionnaire(conn, pid):
    r = conn.execute("SELECT * FROM questionnaire WHERE profile_id=?", (pid,)).fetchone()
    if not r:
        return {"status": "none", "source": "", "step": 0, "answers": {}, "updated": None, "submitted": None}
    try:
        ans = json.loads(r["answers"] or "{}")
    except Exception:
        ans = {}
    return {"status": r["status"], "source": r["source"], "step": r["step"], "answers": ans,
            "updated": r["updated"], "submitted": r["submitted"]}


def ensure_seed(conn):
    """«Основной» profile: its questionnaire-equivalent is the brief (BRIEF-COMMON.md «Кто слушатель»),
    treated as already answered (source=brief). Done once."""
    if conn.execute("SELECT 1 FROM questionnaire WHERE profile_id=?", (DEFAULT_PID,)).fetchone():
        return False
    text = A.load_brief().get("profile") or ""
    if not text.strip():
        return False
    now = _now()
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("INSERT OR IGNORE INTO questionnaire(profile_id,answers,step,status,source,updated,submitted)"
                     " VALUES(?,?,0,'submitted','brief',?,?)",
                     (DEFAULT_PID, json.dumps({"brief": text}, ensure_ascii=False), now, now))
    return True


def questionnaire_payload(conn, pid):
    q = get_questionnaire(conn, pid)
    prof = get_profile(conn, pid) or {}
    q["lines"] = [{"key": k, "label": lab, "text": t} for k, lab, t in answers_lines(q["answers"])]
    q["profile"] = {"id": pid, "name": prof.get("name"), "is_default": bool(prof.get("is_default"))}
    q["options"] = OPTIONS
    q["worldview"] = [{"key": k, "label": lab, "options": opts} for k, lab, opts in WORLDVIEW]
    return q


def save_draft(conn, pid, payload, submit=False):
    prev = get_questionnaire(conn, pid)
    ans = normalize_answers(payload.get("answers"), prev["answers"])
    try:
        step = max(0, min(20, int(payload.get("step") or 0)))
    except (TypeError, ValueError):
        step = 0
    now = _now()
    renamed = False
    with A._WRITE_LOCK:
        # «Имя» in «О себе» is the profile's name: only when the user changed that field
        new_name = ans["about"]["name"]
        old_name = ((prev["answers"] or {}).get("about") or {}).get("name") or ""
        prof = get_profile(conn, pid)
        if new_name and new_name != old_name and prof and new_name != prof["name"]:
            try:
                rename_profile(conn, pid, new_name)
                renamed = True
            except ValueError:
                pass
        status = "submitted" if submit or prev["status"] == "submitted" else "draft"
        source = "user" if submit else (prev["source"] or "user")   # «brief» stays until the user submits
        with A._tx(conn):
            conn.execute("""INSERT INTO questionnaire(profile_id,answers,step,status,source,updated,submitted)
                            VALUES(?,?,?,?,?,?,?) ON CONFLICT(profile_id) DO UPDATE SET answers=excluded.answers,
                            step=excluded.step, status=excluded.status, source=excluded.source,
                            updated=excluded.updated, submitted=coalesce(excluded.submitted, submitted)""",
                         (pid, json.dumps(ans, ensure_ascii=False), step, status, source, now,
                          now if submit else None))
        out = None
        if submit:
            with A._profile_ctx(pid):
                out = A.refresh_outputs(conn, "questionnaire")
    res = questionnaire_payload(conn, pid)
    res["renamed"] = renamed
    if out:
        res.update(warnings=out["warnings"], out=out["out"])
    with contextlib.suppress(Exception):
        import abook_sync   # noqa: PLC0415
        abook_sync.schedule()
    return res


# ------------------------------------------------------------------ AI runs (DB)

def _run_row(r, full=False):
    d = {"id": r["id"], "kind": r["kind"], "status": r["status"], "started": r["started"],
         "finished": r["finished"], "model": r["model"], "duration_sec": r["duration_sec"],
         "cost_usd": r["cost_usd"], "error": r["error"], "inputs_hash": r["inputs_hash"],
         "prompt_chars": r["prompt_chars"], "wish": r["wish"] if "wish" in r.keys() else None}
    for k in ("result", "notes", "meta"):
        try:
            d[k] = json.loads(r[k]) if r[k] else None
        except Exception:
            d[k] = None
    if full:
        d["raw"] = r["raw"]
    return d


TOP_KINDS = ("initial", "refresh")      # runs that produce a profile + top-5; «plus1» is one book on request


def latest_run(conn, pid):
    r = conn.execute("SELECT * FROM ai_runs WHERE profile_id=? AND status='done' AND kind IN ('initial','refresh') "
                     "ORDER BY id DESC LIMIT 1", (pid,)).fetchone()
    return _run_row(r) if r else None


def plus_runs(conn, pid, limit=8):
    """Recent finished «+1 по запросу» runs, newest first, each with its pick enriched with the live item."""
    rows = [_run_row(r) for r in conn.execute(
        "SELECT * FROM ai_runs WHERE profile_id=? AND status='done' AND kind='plus1' ORDER BY id DESC LIMIT ?",
        (pid, limit))]
    ids = [((r.get("result") or {}).get("pick") or {}).get("id") for r in rows]
    items = {i["id"]: i for i in A.get_items(conn, ids=[i for i in ids if i])}
    custom = None                         # an outside pick the listener queued lives on as a custom item
    for r in rows:
        pk = (r.get("result") or {}).get("pick") or {}
        pk["item"] = items.get(pk.get("id")) if pk.get("id") else None
        if not pk.get("id") and pk.get("title"):
            if custom is None:
                custom = A.get_items(conn, where="i.custom=1")
            pk["item"] = next((i for i in custom if same_book(i["author"], i["title"], pk.get("author") or "", pk["title"])), None)
        r["wish"] = (r.get("result") or {}).get("wish", "")
    return rows


def get_run(conn, pid, rid):
    r = conn.execute("SELECT * FROM ai_runs WHERE profile_id=? AND id=?", (pid, rid)).fetchone()
    return _run_row(r, full=True) if r else None


def _enrich(conn, run):
    """Attach live item data (title, queue, review status for this profile) to a run's top-5."""
    if not run or not run.get("result"):
        return run
    top = run["result"].get("top5") or []
    items = {i["id"]: i for i in A.get_items(conn, ids=[t["id"] for t in top])}
    for t in top:
        t["item"] = items.get(t["id"])
    return run


def status_payload(conn, pid):
    with _JOBS_LOCK:
        job = _JOBS.get(pid)
        j = None
        if job:
            j = {k: job[k] for k in ("run_id", "kind", "phase", "attempt", "events", "started", "wish")}
            j["elapsed"] = round(time.time() - job["t0"], 1)
    hist = [{"id": r["id"], "kind": r["kind"], "status": r["status"], "started": r["started"],
             "finished": r["finished"], "duration_sec": r["duration_sec"], "error": r["error"],
             "titles": _titles(conn, r["result"]), "wish": r["wish"]}
            for r in conn.execute("SELECT id,kind,status,started,finished,duration_sec,error,result,wish FROM ai_runs "
                                  "WHERE profile_id=? ORDER BY id DESC LIMIT 30", (pid,))]
    last_err = next((h for h in hist if h["status"] in ("error", "cancelled")), None)
    return {"job": j, "latest": _enrich(conn, latest_run(conn, pid)), "plus": plus_runs(conn, pid), "history": hist,
            "last_problem": last_err if (last_err and hist and hist[0]["id"] == last_err["id"]) else None,
            "model": AI_MODEL, "claude": bool(Path(CLAUDE_BIN).exists()),
            "questionnaire": {k: v for k, v in get_questionnaire(conn, pid).items() if k in ("status", "source")}}


def _titles(conn, result_json):
    try:
        res = json.loads(result_json) or {}
    except Exception:
        return []
    pk = res.get("pick")
    if pk:
        it = A.get_items(conn, ids=[pk["id"]]) if pk.get("id") else []
        return [it[0]["title"] if it else pk.get("title") or ""]
    top = res.get("top5") or []
    items = {i["id"]: i for i in A.get_items(conn, ids=[t.get("id") for t in top if t.get("id")])}
    return [items[t["id"]]["title"] for t in top if t.get("id") in items]


def mark_stale_runs(conn):
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("UPDATE ai_runs SET status='error', error='прервано: сервер был перезапущен', finished=? "
                     "WHERE status='running'", (_now(),))


def _migrate_ai(conn):
    """ai_runs.wish — the listener's free-text request of a «+1» run (kept even when the run fails)."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ai_runs)")}
    if "wish" not in cols:
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute("ALTER TABLE ai_runs ADD COLUMN wish TEXT")


def startup(conn):
    _migrate_ai(conn)
    ensure_seed(conn)
    mark_stale_runs(conn)


# ------------------------------------------------------------------ what the listener already knows

def known_books(conn, pid):
    """Everything the listener already named or reviewed: never recommend it (top-5 or outside)."""
    q = get_questionnaire(conn, pid)["answers"]
    out = []
    for k, how in (("books_liked", "анкета: понравилось"), ("books_disliked", "анкета: не понравилось")):
        for e in q.get(k) or []:
            out.append({"id": e.get("id"), "author": e.get("author") or "", "title": e.get("title") or "",
                        "how": how + (f", {e['rating']}/10" if e.get("rating") is not None else "")})
    with A._profile_ctx(pid):
        revs = A._joined_reviews(conn)
    for r in revs:
        if r["status"] in ("listened", "dropped", "in_progress"):
            how = f"отзыв: {A.REVIEW_STATUSES[r['status']]}" + (f", {r['overall']}/10" if r["overall"] is not None else "")
            out.append({"id": r["item_id"], "author": r["author"], "title": r["title"], "how": how})
    if pid == DEFAULT_PID:
        for r in A.load_brief().get("read") or []:
            out.append({"id": r["id"], "author": r["author"], "title": r["title"], "how": "бриф: уже прочитано"})
    return out


def _known_ids(conn, known, lib):
    """Library ids matching anything known (id match or fuzzy author+title)."""
    ids = {k["id"] for k in known if k.get("id")}
    for it in lib:
        if it["id"] in ids:
            continue
        for k in known:
            if same_book(k["author"], k["title"], it["author"], it["title"]):
                ids.add(it["id"])
                break
    return ids


# ------------------------------------------------------------------ Claude call

_JOBS = {}                 # profile id -> live job
_JOBS_LOCK = threading.Lock()


class Cancelled(Exception):
    pass


_STR = {"type": "string"}
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["profile", "top5", "outside_library", "questions_to_refine"],
    "properties": {
        "profile": {"type": "object", "additionalProperties": False,
                    "required": ["summary", "taste_axes", "loves", "avoid", "listening_context"],
                    "properties": {
                        "summary": _STR,
                        "taste_axes": {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["axis", "value", "evidence"],
                            "properties": {"axis": _STR, "value": _STR, "evidence": _STR}}},
                        "loves": {"type": "array", "items": _STR},
                        "avoid": {"type": "array", "items": _STR},
                        "listening_context": _STR}},
        "top5": {"type": "array", "minItems": 5, "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False, "required": ["id", "why", "confidence"],
            "properties": {"id": _STR, "why": _STR, "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}},
        "outside_library": {"type": "array", "maxItems": 5, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["author", "title", "why", "where_to_find"],
            "properties": {"author": _STR, "title": _STR, "why": _STR, "where_to_find": _STR}}},
        "questions_to_refine": {"type": "array", "items": _STR}}}
PLUS_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["pick"],
    "properties": {"pick": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "author", "title", "why", "wish_fit", "confidence", "where_to_find"],
        "properties": {"id": _STR, "author": _STR, "title": _STR, "why": _STR, "wish_fit": _STR,
                       "confidence": {"type": "number", "minimum": 0, "maximum": 1}, "where_to_find": _STR}}}}
FIX_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["top5"],
    "properties": {"top5": SCHEMA["properties"]["top5"] | {"minItems": 1}}}


def _workdir():
    d = A.DB_PATH.parent / "ai-work"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _event(job, kind, text):
    with _JOBS_LOCK:
        job["events"].append({"t": round(time.time() - job["t0"], 1), "kind": kind, "text": text[:200]})
        del job["events"][:-14]


def _phase(job, text):
    with _JOBS_LOCK:
        job["phase"] = text


def call_claude(prompt, schema, job):
    """One headless Claude Code call. Returns (data | None, meta, error | None).
    Only WebSearch/WebFetch are available to the model; no files, no shell."""
    import abook_llm as LLM   # noqa: PLC0415
    if LLM.provider() == "agy":
        sub = F_job = __import__("abook_find").new_job()
        sub["cancel"] = False
        stop = threading.Event()

        def relay():                                   # отмена подбора → отмена вызова agy
            while not stop.wait(0.5):
                if job.get("cancel"):
                    F_job["cancel"] = True
                    return
        threading.Thread(target=relay, daemon=True).start()
        try:
            data, meta, err = LLM.run(prompt, sub, AI_MODEL, schema=schema, timeout=AI_TIMEOUT if "AI_TIMEOUT" in globals() else 600)
        except Exception as e:
            data, meta, err = None, {}, ("отменено" if job.get("cancel") else str(e))
        finally:
            stop.set()
        return data, meta, err
    cmd = [CLAUDE_BIN, "-p", "--model", AI_MODEL, "--output-format", "stream-json", "--verbose",
           "--safe-mode", "--no-session-persistence", "--tools", AI_TOOLS, "--allowedTools", AI_TOOLS,
           "--disallowedTools", AI_DENY, "--permission-mode", "dontAsk",
           "--max-budget-usd", str(AI_BUDGET_USD), "--json-schema", json.dumps(schema, ensure_ascii=False)]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(_workdir()), env=env, start_new_session=True)
    with _JOBS_LOCK:
        job["proc"] = proc
    final, err_tail = {}, []

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
            if t == "assistant":
                for c in (ev.get("message") or {}).get("content") or []:
                    if c.get("type") == "tool_use":
                        name, inp = c.get("name"), c.get("input") or {}
                        if name == "WebSearch":
                            _event(job, "search", str(inp.get("query") or ""))
                            _phase(job, "Claude ищет в интернете")
                        elif name == "WebFetch":
                            _event(job, "fetch", str(inp.get("url") or ""))
                            _phase(job, "Claude читает страницу")
                        elif name == "StructuredOutput":
                            _phase(job, "Claude оформляет ответ")
                    elif c.get("type") == "text" and (c.get("text") or "").strip():
                        _phase(job, "Claude думает")
            elif t == "system" and ev.get("subtype") == "init":
                _phase(job, "Claude читает анкету и каталог")
            elif t == "result":
                final.update(ev)

    def read_err():
        for raw in proc.stderr:
            err_tail.append(raw.decode("utf-8", "replace").rstrip())
            del err_tail[:-20]

    ths = [threading.Thread(target=f, daemon=True) for f in (feed, read_out, read_err)]
    for th in ths:
        th.start()
    deadline = t0 + AI_TIMEOUT
    reason = None
    while proc.poll() is None:
        if job.get("cancel"):
            reason = "cancel"
        elif time.time() > deadline:
            reason = "timeout"
        if reason:
            _kill(proc)
            break
        time.sleep(0.3)
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)
    for th in ths[1:]:
        th.join(timeout=5)
    with _JOBS_LOCK:
        job["proc"] = None
    meta = {"seconds": round(time.time() - t0, 1), "rc": proc.returncode,
            "cost_usd": final.get("total_cost_usd"), "turns": final.get("num_turns"),
            "duration_api_ms": final.get("duration_api_ms"), "subtype": final.get("subtype"),
            "searches": sum(1 for e in job["events"] if e["kind"] == "search"),
            "fetches": sum(1 for e in job["events"] if e["kind"] == "fetch")}
    with contextlib.suppress(Exception):
        meta["models"] = list((final.get("modelUsage") or {}).keys())
    if reason == "cancel":
        raise Cancelled()
    if reason == "timeout":
        return None, meta, f"нет ответа за {AI_TIMEOUT // 60} мин"
    if not final:
        tail = " / ".join(x for x in err_tail[-3:] if x)
        return None, meta, f"Claude завершился без результата (код {proc.returncode}){': ' + tail if tail else ''}"
    if final.get("is_error") or final.get("subtype") not in (None, "success"):
        return None, meta, f"ошибка Claude: {final.get('subtype')}: {_line(final.get('result'), 300)}"
    data = final.get("structured_output")
    if data is None:
        data = parse_json_loose(final.get("result"))
    if not isinstance(data, dict):
        return None, meta, "ответ не удалось разобрать как JSON"
    return data, meta, None


def parse_json_loose(text):
    if not isinstance(text, str):
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        with contextlib.suppress(Exception):
            return json.loads(s[i:j + 1])
    return None


def _kill(proc):
    with contextlib.suppress(Exception):
        os.killpg(proc.pid, signal.SIGTERM)
    for _ in range(20):
        if proc.poll() is not None:
            return
        time.sleep(0.15)
    with contextlib.suppress(Exception):
        os.killpg(proc.pid, signal.SIGKILL)


# ------------------------------------------------------------------ prompt

_RULES = """Жёсткие правила:
1. top5 — ровно 5 разных id, каждый скопирован из §5 CATALOG (первое поле строки, до «|»). Не выдумывай и не меняй id.
2. Никогда не рекомендуй (ни в top5, ни в outside_library) то, что слушатель уже знает: всё, что он назвал в анкете \
(понравилось ИЛИ не понравилось), всё, на что у него есть отзыв, и «Уже прочитано». Полный список — ниже в «УЖЕ ЗНАКОМО»; \
другие издания/переводы/радиоверсии этих же произведений тоже нельзя.
3. Это слушают: учитывай длину, язык (ru → uk → en), чтеца, ИИ-озвучку (обычно хуже живого голоса), скачано ли (ст=✓ лучше).
4. why — 2–3 предложения на «вы», привязанные к конкретным ответам анкеты или отзывам (назовите книгу, фильм или ответ, \
на который опираетесь).
5. confidence — число от 0 до 1: насколько вероятно, что понравится.
6. outside_library — 0–5 книг ВНЕ каталога, которые особенно подойдут. Можно пользоваться WebSearch/WebFetch (не больше \
8 обращений всего), чтобы проверить, есть ли полная русская аудиокнига или радиоспектакль; where_to_find — конкретно \
(канал YouTube, ЛитРес, «Звуки слов», archive.org…). Если не проверил — так и напиши, не выдумывай ссылки.
7. ГЛАВНОЕ — качественный психологический портрет читателя: не пересказ анкеты, а выводы — какие потребности он \
закрывает книгами (побег, понимание людей, интеллектуальная игра, катарсис, утешение), его отношение к мраку, неопределённости, \
абсурду и морали, что его цепляет в историях на глубинном уровне, как это связано с профессией, возрастом, семьёй, \
путешествиями, играми и мировоззрением. Любой раздел анкеты может быть пустым (например, нет любимых игр) — это нормально, \
не додумывай, опирайся на то, что есть. Главный источник сигнала — книги и отзывы к книгам; остальное уточняет портрет.
profile.summary — 5–9 предложений на «вы» (этот портрет); taste_axes — 4–8 осей вкуса (axis — ось, value — где на ней слушатель, \
evidence — на чём основано); loves и avoid — по 3–8 коротких фраз; listening_context — когда и как слушает и что из этого \
следует для длины и сложности.
8. questions_to_refine — 2–5 коротких вопросов, ответы на которые сильнее всего улучшат подбор.
9. Всё по-русски. Ответ — только JSON по заданной схеме."""


_PLUS_RULES = """Жёсткие правила:
1. Ровно ОДНА книга. Сначала ищи в §5 CATALOG: если там есть подходящая — id скопируй точно (первое поле строки, до «|»), \
author и title — как в каталоге, where_to_find — пустая строка.
2. Только если в каталоге действительно нет ничего, что отвечает запросу, — одна книга ВНЕ каталога: id — пустая строка, \
author и title — точно; можно пользоваться WebSearch/WebFetch (не больше 6 обращений), чтобы проверить, есть ли полная \
русская аудиокнига; where_to_find — конкретно (канал YouTube, ЛитРес, «Звуки слов», archive.org…). Не выдумывай ссылки.
3. Нельзя: всё из «УЖЕ ЗНАКОМО», книги из очереди, прошлый топ-5 и прошлые «+1» (список «УЖЕ ПРЕДЛОЖЕНО»), \
другие издания/переводы этих же произведений.
4. Запрос слушателя — главный фильтр (тема, настроение, длина, «как X»). Анкета (§1) и отзывы (§2/§3, свежие важнее) \
решают, какая из подходящих под запрос книг понравится именно ему. Если запрос противоречит вкусу — всё равно выполни \
запрос, но выбери самый близкий к вкусу вариант и честно скажи об этом в why.
5. why — 2–4 предложения на «вы» с опорой на конкретные ответы анкеты или отзывы (назовите книгу или ответ). \
wish_fit — одно предложение: чем книга отвечает на запрос. confidence — 0..1: насколько вероятно, что понравится.
6. Это слушают: учитывай длину, язык (ru → uk → en), чтеца, ИИ-озвучку (обычно хуже живого голоса), скачано ли (ст=✓ лучше).
7. Всё по-русски. Ответ — только JSON по заданной схеме."""


def build_context(conn, pid, kind, wish=""):
    prof = get_profile(conn, pid)
    q = get_questionnaire(conn, pid)
    with A._profile_ctx(pid):
        doc = A.build_aidoc(conn, lite=(kind == "initial"))
        lib = A.get_items(conn, where="i.in_library=1")
        queue = A.get_queue(conn)
    known = known_books(conn, pid)
    excluded = _known_ids(conn, known, lib)
    allowed = {i["id"] for i in lib} - excluded
    prev = latest_run(conn, pid)
    prev_ids = [t["id"] for t in ((prev or {}).get("result") or {}).get("top5") or []]
    by_id = {i["id"]: i for i in lib}
    kl = []
    for k in known:
        kl.append(f"- {('[' + k['id'] + '] ') if k.get('id') and k['id'] in by_id else ''}"
                  f"{(k['author'] + ' — ') if k['author'] else ''}«{k['title']}» ({k['how']})")
    for iid in sorted(excluded - {k["id"] for k in known if k.get("id")}):
        it = by_id[iid]
        kl.append(f"- [{iid}] {it['author']} — «{it['title']}» (то же произведение, что названо выше)")
    offered = []                          # +1: what was already offered and must not come back
    if kind == "plus1":
        seen = set()
        for iid in list(prev_ids) + list(queue):
            if iid in by_id and iid not in seen:
                seen.add(iid)
                offered.append({"id": iid, "author": by_id[iid]["author"], "title": by_id[iid]["title"]})
        for r in plus_runs(conn, pid, limit=40):
            pk = (r.get("result") or {}).get("pick") or {}
            if pk.get("title") and pk.get("id") not in seen:
                seen.add(pk.get("id"))
                offered.append({"id": pk.get("id") or "", "author": pk.get("author") or "", "title": pk["title"]})
        excluded = excluded | {o["id"] for o in offered if o["id"] in by_id}
        allowed = allowed - excluded
    if kind == "plus1":
        task = ("ЗАДАЧА: слушатель просит ещё одну книгу (+1) под свой запрос. Запрос слушателя дословно:\n«"
                + (wish or "без особого запроса — просто следующую книгу, которая точно зайдёт") + "»\n"
                "Учитывай анкету (§1), все отзывы (§2 и §3, свежие важнее — смотри вес) и прошлые рекомендации (§2a).")
    elif kind == "refresh":
        task = ("ЗАДАЧА: слушатель просит пересмотреть подбор с учётом его отзывов. Опирайся на анкету (§1), на все отзывы "
                "(§2 и §3, свежие важнее — смотри вес) и на прошлые рекомендации (§2a). Составь обновлённый профиль вкуса "
                "и новый топ-5 из §5 CATALOG.")
        still = [i for i in prev_ids if i in allowed]
        if still:
            task += ("\nПрошлый топ-5 ещё не прослушан: " + ", ".join(f"[{i}]" for i in still) +
                     ". Не повторяй эти книги, кроме случая, когда книга по-прежнему явно лучший выбор — тогда скажи это в why.")
    else:
        task = ("ЗАДАЧА: слушатель только что заполнил анкету. По анкете (§1) и отзывам (если есть; свежие важнее) составь "
                "профиль его вкуса и выбери 5 книг из §5 CATALOG, которые ему стоит слушать сейчас. Книги в анкете — "
                "главный сигнал; фильмы, сериалы, путешествия, музыка и мировоззрение — дополнительные.")
    if kind == "plus1":
        ol = [f"- {('[' + o['id'] + '] ') if o['id'] else ''}{(o['author'] + ' — ') if o['author'] else ''}«{o['title']}»"
              for o in offered]
        prompt = "\n\n".join([
            f"Ты — внимательный персональный консультант по аудиокнигам. Слушатель: профиль «{prof['name']}». Ниже — "
            "документ его личной аудиобиблиотеки (формат описан в §0 README документа): §1 PROFILE — анкета и профиль "
            "от ИИ, §2/§3 — отзывы с весами свежести, §2a — прошлые рекомендации ИИ, §5 CATALOG — книги, которые у него "
            "есть, с id.",
            task, _PLUS_RULES,
            "УЖЕ ЗНАКОМО (не предлагать):\n" + ("\n".join(kl) if kl else "- (пока ничего)"),
            "УЖЕ ПРЕДЛОЖЕНО или в очереди (не предлагать):\n" + ("\n".join(ol) if ol else "- (пока ничего)"),
            "=== ДОКУМЕНТ БИБЛИОТЕКИ ===\n" + doc + "\n=== КОНЕЦ ДОКУМЕНТА ===",
            "Напоминание: ровно одна книга; сначала из §5 CATALOG (id точно), вне каталога — только если там нет "
            "подходящей; не из «УЖЕ ЗНАКОМО» и не из «УЖЕ ПРЕДЛОЖЕНО»; ответ — JSON по схеме."])
    else:
      prompt = "\n\n".join([
        f"Ты — внимательный персональный консультант по аудиокнигам. Слушатель: профиль «{prof['name']}». Ниже — документ "
        "его личной аудиобиблиотеки (формат описан в §0 README документа): §1 PROFILE — анкета и прежний профиль, "
        "§2/§3 — отзывы с весами свежести, §2a — прошлые рекомендации ИИ, §5 CATALOG — книги, которые у него есть, с id.",
        task, _RULES,
        "УЖЕ ЗНАКОМО (не рекомендовать ни в top5, ни в outside_library):\n" + ("\n".join(kl) if kl else "- (пока ничего)"),
        "=== ДОКУМЕНТ БИБЛИОТЕКИ ===\n" + doc + "\n=== КОНЕЦ ДОКУМЕНТА ===",
        "Напоминание: top5 — только id из §5 CATALOG и не из «УЖЕ ЗНАКОМО»; outside_library — не из каталога и не из "
        "«УЖЕ ЗНАКОМО»; ответ — JSON по схеме."])
    doc_stable = "\n".join(doc.splitlines()[1:])        # without the generated-at header
    h = hashlib.sha256(json.dumps({"kind": kind, "answers": q["answers"], "doc": doc_stable, "model": AI_MODEL,
                                   "wish": wish}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return {"prompt": prompt, "hash": h, "allowed": allowed, "excluded": excluded, "known": known,
            "lib": by_id, "doc_lite": doc if kind == "initial" else None, "prev_ids": prev_ids, "offered": offered}


def validate_plus(data, ctx):
    """Clean a «+1» answer; returns (pick | None, notes). A catalogue id wins; an outside book that is really in the
    catalogue becomes that catalogue pick (if allowed)."""
    notes = []
    pk = data.get("pick") if isinstance(data.get("pick"), dict) else {}
    iid = re.sub(r"^[\s\[`'\"]+|[\s\]`'\".,]+$", "", str(pk.get("id") or ""))
    a, t = _s(pk.get("author"), 200), _s(pk.get("title"), 300)
    try:
        conf = float(pk.get("confidence"))
        conf = min(1.0, max(0.0, conf)) if math.isfinite(conf) else None
    except (TypeError, ValueError):
        conf = None
    base = {"why": _s(pk.get("why"), 1600), "wish_fit": _s(pk.get("wish_fit"), 400), "confidence": conf}
    if iid:
        if iid not in ctx["lib"]:
            notes.append(f"+1: id [{iid}] нет в каталоге")
        elif iid in ctx["excluded"]:
            notes.append(f"+1: [{iid}] уже знакомо, в очереди или уже предлагалось")
        else:
            it = ctx["lib"][iid]
            return {"id": iid, "author": it["author"], "title": it["title"], "where_to_find": "", **base}, notes
        return None, notes
    if not t:
        notes.append("+1: пустой ответ")
        return None, notes
    hit = next((k for k in ctx["known"] + ctx["offered"] if same_book(k["author"], k["title"], a, t)), None)
    if hit:
        notes.append(f"+1: «{t}» уже знакомо или уже предлагалось")
        return None, notes
    inlib = next((i for i in ctx["lib"].values() if same_book(i["author"], i["title"], a, t)), None)
    if inlib:
        if inlib["id"] in ctx["excluded"]:
            notes.append(f"+1: «{t}» есть в библиотеке [{inlib['id']}], но уже знакомо или предлагалось")
            return None, notes
        notes.append(f"+1: «{t}» на самом деле есть в библиотеке — [{inlib['id']}]")
        return {"id": inlib["id"], "author": inlib["author"], "title": inlib["title"], "where_to_find": "", **base}, notes
    return {"id": "", "author": a, "title": t, "where_to_find": _s(pk.get("where_to_find"), 600), **base}, notes


def validate(data, ctx):
    """Clean the model's JSON; returns (result, notes, bad_top5)."""
    notes = []
    prof = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    res = {"profile": {
        "summary": _s(prof.get("summary"), 3000),
        "taste_axes": [{"axis": _s(x.get("axis"), 120), "value": _s(x.get("value"), 300),
                        "evidence": _s(x.get("evidence"), 500)}
                       for x in (prof.get("taste_axes") or []) if isinstance(x, dict) and x.get("axis")][:10],
        "loves": [_s(x, 200) for x in (prof.get("loves") or []) if _s(x)][:10],
        "avoid": [_s(x, 200) for x in (prof.get("avoid") or []) if _s(x)][:10],
        "listening_context": _s(prof.get("listening_context"), 1000)},
        "top5": [], "outside_library": [],
        "questions_to_refine": [_s(x, 300) for x in (data.get("questions_to_refine") or []) if _s(x)][:6]}
    bad = []
    res["top5"] = _take_top(data.get("top5"), ctx, res["top5"], bad, notes)
    for o in data.get("outside_library") or []:
        if not isinstance(o, dict) or not _s(o.get("title")):
            continue
        a, t = _s(o.get("author"), 200), _s(o.get("title"), 300)
        hit = next((k for k in ctx["known"] if same_book(k["author"], k["title"], a, t)), None)
        if hit:
            notes.append(f"вне библиотеки: убрано «{t}» — уже знакомо ({hit['how']})")
            continue
        inlib = next((i for i in ctx["lib"].values() if same_book(i["author"], i["title"], a, t)), None)
        if inlib:
            notes.append(f"вне библиотеки: «{t}» на самом деле есть в библиотеке [{inlib['id']}] — убрано")
            continue
        res["outside_library"].append({"author": a, "title": t, "why": _s(o.get("why"), 1200),
                                       "where_to_find": _s(o.get("where_to_find"), 600)})
    res["outside_library"] = res["outside_library"][:5]
    return res, notes, bad


def _take_top(items, ctx, acc, bad, notes):
    seen = {t["id"] for t in acc}
    for t in items or []:
        if not isinstance(t, dict):
            continue
        iid = re.sub(r"^[\s\[`'\"]+|[\s\]`'\".,]+$", "", str(t.get("id") or ""))
        if not iid or iid in seen:
            continue
        if iid not in ctx["lib"]:
            bad.append(iid)
            notes.append(f"топ-5: id [{iid}] нет в каталоге")
            continue
        if iid in ctx["excluded"]:
            bad.append(iid)
            notes.append(f"топ-5: [{iid}] уже знакомо слушателю")
            continue
        try:
            conf = float(t.get("confidence"))
            conf = min(1.0, max(0.0, conf)) if math.isfinite(conf) else None
        except (TypeError, ValueError):
            conf = None
        seen.add(iid)
        acc.append({"id": iid, "why": _s(t.get("why"), 1500), "confidence": conf})
        if len(acc) >= 5:
            break
    return acc


def _fix_prompt(conn, ctx, res, bad, need):
    chosen = ", ".join(f"[{t['id']}]" for t in res["top5"]) or "—"
    known = "\n".join(f"- {('[' + k['id'] + '] ') if k.get('id') else ''}{(k['author'] + ' — ') if k['author'] else ''}"
                      f"«{k['title']}»" for k in ctx["known"]) or "- —"
    doc = ctx["doc_lite"]
    if doc is None:
        with A._profile_ctx(ctx["pid"]):
            doc = A.build_aidoc(conn, lite=True)
    return "\n\n".join([
        "Ты подбирал топ-5 аудиокниг из каталога для слушателя. Часть ответа не прошла проверку: "
        + ", ".join(f"[{b}]" for b in bad) + " — таких id нет в §5 CATALOG или слушатель эти книги уже знает.",
        f"Уже выбраны (не повторять): {chosen}.",
        f"Профиль слушателя: {res['profile']['summary']}",
        f"Выбери ещё {need} книг(и) строго из §5 CATALOG ниже (id копируй точно), не из «УЖЕ ЗНАКОМО» и не из уже "
        "выбранных. why — 2–3 предложения на «вы» с опорой на анкету/отзывы, confidence 0..1. Ответ — JSON по схеме.",
        "УЖЕ ЗНАКОМО:\n" + known,
        "=== ДОКУМЕНТ БИБЛИОТЕКИ (lite) ===\n" + doc + "\n=== КОНЕЦ ==="])


def start_run(conn, pid, kind, wish=None):
    kind = kind if kind in ("refresh", "plus1") else "initial"
    wish = re.sub(r"\s+", " ", str(wish or "")).strip()[:1000] if kind == "plus1" else None
    if not Path(CLAUDE_BIN).exists():
        raise ValueError("Не найден Claude Code CLI (`claude`) — ИИ-подбор недоступен")
    if not A.get_items(conn, where="i.in_library=1")[:1]:
        raise ValueError("Каталог пуст — сначала `abook sync`")
    with _JOBS_LOCK:
        if pid in _JOBS:
            raise ValueError("Подбор для этого профиля уже идёт")
        job = {"run_id": None, "kind": kind, "phase": "Готовлю данные", "attempt": 1, "events": [],
               "started": _now(), "t0": time.time(), "cancel": False, "proc": None, "wish": wish}
        _JOBS[pid] = job
    try:
        with A._WRITE_LOCK, A._tx(conn):
            cur = conn.execute("INSERT INTO ai_runs(profile_id,kind,status,started,model,wish) VALUES(?,?,'running',?,?,?)",
                               (pid, kind, job["started"], AI_MODEL, wish))
            job["run_id"] = cur.lastrowid
    except BaseException:
        with _JOBS_LOCK:
            _JOBS.pop(pid, None)
        raise
    threading.Thread(target=_worker, args=(pid, job), daemon=True, name=f"abook-ai-{pid}").start()
    return job["run_id"]


def cancel_run(pid):
    with _JOBS_LOCK:
        job = _JOBS.get(pid)
        if not job:
            return False
        job["cancel"] = True
        proc = job.get("proc")
    if proc is not None:
        threading.Thread(target=_kill, args=(proc,), daemon=True).start()
    return True


class _Done(Exception):
    """«+1» finished early inside the shared try/finally of _worker."""


def _plus_worker(job, ctx, notes, meta_all, raw_all):
    """One book on request: ask, validate; on a rejected pick ask once more naming what was rejected."""
    prompt, pick = ctx["prompt"], None
    for attempt in (1, 2):
        job["attempt"] = attempt
        _phase(job, "Запускаю Claude" + (" (повтор)" if attempt > 1 else ""))
        data, meta, e = call_claude(prompt, PLUS_SCHEMA, job)
        meta_all.append(meta)
        if job.get("cancel"):
            raise Cancelled()
        if data is None:
            notes.append(f"попытка {attempt}: {e}")
            continue
        raw_all.append(data)
        _phase(job, "Проверяю ответ")
        pick, vn = validate_plus(data, ctx)
        notes += vn
        if pick:
            break
        prompt = ctx["prompt"] + "\n\nПРЕДЫДУЩИЙ ОТВЕТ ОТКЛОНЁН ПРОВЕРКОЙ: " + "; ".join(vn) + ". Выбери другую книгу."
    if not pick:
        raise RuntimeError("предложенная книга не прошла проверку" if raw_all else (notes[-1] if notes else "нет ответа"))
    return {"wish": job.get("wish") or "", "pick": pick}


def _worker(pid, job):
    conn = A.db_connect()
    rid = job["run_id"]
    notes, meta_all, raw_all = [], [], []
    status, err, result, ctx = "error", None, None, None
    try:
        A._PROFILE.id = pid
        ctx = build_context(conn, pid, job["kind"], job.get("wish") or "")
        ctx["pid"] = pid
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute("UPDATE ai_runs SET inputs_hash=?, prompt_chars=? WHERE id=?",
                         (ctx["hash"], len(ctx["prompt"]), rid))
        if job["kind"] == "plus1":
            result = _plus_worker(job, ctx, notes, meta_all, raw_all)
            status = "done"
            raise _Done()
        data = None
        for attempt in (1, 2):
            job["attempt"] = attempt
            _phase(job, "Запускаю Claude" + (" (повтор)" if attempt > 1 else ""))
            data, meta, e = call_claude(ctx["prompt"], SCHEMA, job)
            meta_all.append(meta)
            if data is not None:
                raw_all.append(data)
                break
            notes.append(f"попытка {attempt}: {e}")
            err = e
            if job.get("cancel"):
                raise Cancelled()
        if data is None:
            raise RuntimeError(err or "нет ответа")
        _phase(job, "Проверяю ответ")
        result, vnotes, bad = validate(data, ctx)
        notes += vnotes
        need = 5 - len(result["top5"])
        if need > 0:
            _phase(job, f"Уточняю у Claude: {need} из 5 не прошли проверку")
            fix, meta, e = call_claude(_fix_prompt(conn, ctx, result, bad, need), FIX_SCHEMA, job)
            meta_all.append(meta)
            if fix is not None:
                raw_all.append(fix)
                before = len(result["top5"])
                _take_top(fix.get("top5"), ctx, result["top5"], [], notes)
                notes.append(f"уточнение: добавлено {len(result['top5']) - before}")
            else:
                notes.append(f"уточнение не удалось: {e}")
            if len(result["top5"]) < 5:
                notes.append(f"в топе {len(result['top5'])} из 5 — остальные отброшены проверкой")
        if not result["top5"]:
            raise RuntimeError("ни одна рекомендация не прошла проверку")
        status = "done"
    except _Done:
        pass
    except Cancelled:
        status, err = "cancelled", "отменено"
    except Exception as e:
        status, err = "error", f"{type(e).__name__}: {e}" if not isinstance(e, RuntimeError) else str(e)
    finally:
        try:
            dur = round(time.time() - job["t0"], 1)
            cost = sum((m.get("cost_usd") or 0) for m in meta_all) or None
            raw = raw_all[0] if len(raw_all) == 1 else ({"main": raw_all[0], "fix": raw_all[1:]} if raw_all else None)
            with A._WRITE_LOCK:
                with A._tx(conn):
                    conn.execute("UPDATE ai_runs SET status=?, finished=?, duration_sec=?, cost_usd=?, raw=?, result=?,"
                                 " notes=?, meta=?, error=? WHERE id=?",
                                 (status, _now(), dur, cost, json.dumps(raw, ensure_ascii=False) if raw else None,
                                  json.dumps(result, ensure_ascii=False) if status == "done" else None,
                                  json.dumps(notes, ensure_ascii=False), json.dumps(meta_all, ensure_ascii=False),
                                  err, rid))
                if status == "done":
                    with A._profile_ctx(pid):
                        A.refresh_outputs(conn, "ai")
        except Exception as e:  # never leave the job stuck
            A.log(f"WARN: abook_ai: saving run {rid} failed: {e}")
        finally:
            with _JOBS_LOCK:
                _JOBS.pop(pid, None)
            conn.close()


# ------------------------------------------------------------------ AI document sections

def _date(s):
    return (s or "")[:16].replace("T", " ")


def aidoc_profile_lines(conn, lite=False):
    """Appended to §1 PROFILE: the questionnaire (compact) + the latest AI profile."""
    pid = A._pid()
    L = []
    q = get_questionnaire(conn, pid)
    if q["status"] == "submitted" and q["source"] == "user":
        lines = answers_lines(q["answers"], lite=lite, with_brief=pid != DEFAULT_PID)
        L.append(f"## Анкета (заполнена {_date(q['submitted'] or q['updated'])[:10]})")
        L += [f"- {lab}: {t}" for _, lab, t in lines] or ["- (пусто)"]
    elif pid != DEFAULT_PID:
        L.append("- анкета не заполнена — вкус известен только по отзывам")
    run = latest_run(conn, pid)
    p = ((run or {}).get("result") or {}).get("profile")
    if p:
        L.append(f"## Профиль от ИИ (Claude, {_date(run['finished'])})")
        if p.get("summary"):
            L.append(_line(p["summary"], 3000))
        if p.get("taste_axes"):
            L.append("оси вкуса: " + "; ".join(
                f"{x['axis']} — {x['value']}" + ("" if lite or not x.get("evidence") else f" ({_line(x['evidence'], 200)})")
                for x in p["taste_axes"]))
        if p.get("loves"):
            L.append("любит: " + "; ".join(p["loves"]))
        if p.get("avoid"):
            L.append("избегать: " + "; ".join(p["avoid"]))
        if p.get("listening_context"):
            L.append("как слушает: " + _line(p["listening_context"], 600))
    return L


def aidoc_ai_lines(conn, lite=False):
    """§2a — the latest AI top-5 and outside-library picks of the current profile."""
    pid = A._pid()
    run = latest_run(conn, pid)
    L = ["# §2a Рекомендации ИИ"]
    plus = _plus_doc_lines(conn, pid, lite)
    if not run or not run.get("result"):
        return L + ["пока нет (приложение → «Анкета» → «Составить профиль и топ-5»)"] + plus + [""]
    res = run["result"]
    n = conn.execute("SELECT count(*) FROM ai_runs WHERE profile_id=? AND status='done' AND kind IN ('initial','refresh')",
                     (pid,)).fetchone()[0]
    L.append(f"последний подбор: {_date(run['finished'])}, Claude ({run['model']}), "
             f"{'по анкете' if run['kind'] == 'initial' else 'пересмотр с учётом отзывов'}; подборов всего: {n}. "
             "Это совет ИИ, не отзыв слушателя; не повторяй его без причины.")
    items = {i["id"]: i for i in A.get_items(conn, ids=[t["id"] for t in res.get("top5") or []])}
    for k, t in enumerate(res.get("top5") or [], 1):
        it = items.get(t["id"], {})
        conf = f" · уверенность {t['confidence']:.2f}" if isinstance(t.get("confidence"), (int, float)) else ""
        L.append(f"{k}. [{t['id']}] {it.get('author') or '?'} — «{it.get('title') or t['id']}»{conf} — "
                 f"{_line(t.get('why'), 300 if lite else 1200)}")
    for o in res.get("outside_library") or []:
        L.append(f"вне библиотеки: {o['author']} — «{o['title']}» — {_line(o.get('why'), 200 if lite else 800)}"
                 + (f" (где: {_line(o['where_to_find'], 200)})" if o.get("where_to_find") and not lite else ""))
    L += plus
    L.append("")
    return L


def _plus_doc_lines(conn, pid, lite):
    L = []
    for r in plus_runs(conn, pid, limit=10):
        pk = (r.get("result") or {}).get("pick") or {}
        where = f"[{pk['id']}] " if pk.get("id") else "вне библиотеки: "
        L.append(f"+1 по запросу «{_line(r.get('wish') or 'без запроса', 160)}» ({_date(r['finished'])[:10]}): {where}"
                 f"{pk.get('author') or '?'} — «{pk.get('title') or '?'}» — {_line(pk.get('why'), 200 if lite else 600)}")
    return L


# ------------------------------------------------------------------ HTTP

def handle_get(h, conn, p, arg):
    pid = A._pid()
    if p == "/api/profiles":
        return h._json(profiles_payload(conn))
    if p == "/api/questionnaire":
        return h._json(questionnaire_payload(conn, pid))
    if p == "/api/ai/status":
        return h._json(status_payload(conn, pid))
    if p == "/api/ai/run":
        try:
            rid = int(arg("id") or 0)
        except ValueError:
            rid = 0
        run = get_run(conn, pid, rid)
        return h._json(_enrich(conn, run)) if run else h._json({"error": "запуск не найден"}, 404)
    return h._json({"error": "not found"}, 404)


QQ_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["questions"], "properties": {
    "questions": {"type": "array", "maxItems": 6, "items": {
        "type": "object", "additionalProperties": False, "required": ["q", "options"],
        "properties": {"q": {"type": "string"}, "options": {"type": "array", "maxItems": 4, "items": {"type": "string"}}}}}}}


def gap_questions(conn, pid):
    """«Что ещё нужно знать»: 4–6 вопросов, ответы на которые сильнее всего улучшат подбор (дешёвая модель,
    короткий контекст — только строки анкеты и уже заданные вопросы)."""
    import abook_find as F   # noqa: PLC0415
    q = get_questionnaire(conn, pid)
    lines = "\n".join(f"- {lab}: {_line(t, 600)}" for _, lab, t in answers_lines(q["answers"], lite=True, with_brief=False))
    asked = [e["q"] for e in (q["answers"].get("extra") or {}).get("qa") or []]
    prompt = ("Ты помогаешь подбирать аудиокниги. Вот что слушатель уже рассказал о себе:\n" + (lines or "- пока ничего") +
              "\n\nЗадай 4–6 НОВЫХ коротких вопросов, ответы на которые сильнее всего улучшат советы и которых нет в анкете "
              "(например: допустимая жестокость, отношение к открытым финалам, перечитывает ли, нон-фикшн, классика, "
              "длинные серии, чтецы-мужчины/женщины). К каждому — 2–4 варианта ответа по 1–4 слова. Без повторов: "
              + ("; ".join(asked) if asked else "—") + ". Только JSON по схеме, по-русски.")
    job = F.new_job()
    data, meta, err = F.run_claude(prompt, QQ_SCHEMA, job, os.environ.get("ABOOK_QQ_MODEL", "haiku"), timeout=90, budget=0.2)
    if data is None:
        raise ValueError(err or "Не удалось получить вопросы")
    return {"questions": [{"q": _s(x.get("q"), 300), "options": [_s(o, 80) for o in x.get("options") or []][:4]}
                          for x in data.get("questions") or [] if _s(x.get("q"))][:6], "cost_usd": meta.get("cost_usd")}


def answers_from_text(conn, pid, text):
    """Вторая дорога в анкету: человек рассказывает своими словами, Claude раскладывает рассказ по полям анкеты
    (варианты чипов — только из OPTIONS). Заполняются пустые поля, заполненное вручную не перетирается; дальше
    человек проверяет шаги и «Итог» как обычно."""
    import abook_find as F   # noqa: PLC0415
    text = _s(text, 8000)
    if len(text) < 20:
        raise ValueError("Расскажите чуть подробнее — хотя бы пару фраз о книгах, которые нравятся")
    shape = {"books_liked": [{"kind": "book | author (любимый автор целиком: title = имя автора)", "author": "", "title": "", "why": ["из book_like"], "comment": ""}],
             "books_disliked": [{"author": "", "title": "", "why": ["из book_dislike"], "comment": ""}],
             "prefs": {"genres": [], "genres_text": "", "length": [], "format": [], "lang": [], "listen": [], "narrators": ""},
             "films": [{"title": "", "comment": ""}], "series": [{"title": ""}], "games": [{"title": ""}],
             "music": {"chips": [], "text": ""}, "interests": {"chips": [], "text": ""},
             "travel": {"been": [], "want": [], "types": [], "pace": "", "text": ""},
             "about": {"age": "", "profession": "", "location": "", "family": [], "family_text": ""},
             "extra": {"text": "", "avoid_authors": [], "avoid_topics": [], "darkness": "", "where": [], "hours": ""}}
    prompt = ("Разложи рассказ слушателя аудиокниг по полям анкеты. Бери только то, что сказано или прямо следует; "
              "не выдумывай. Чипы — строго из списков вариантов ниже (иначе — в соответствующее *_text/text). "
              "Книги и фильмы — точные названия, автор по-русски, если знаешь.\n\nФОРМА (JSON):\n"
              + json.dumps(shape, ensure_ascii=False) + "\n\nВАРИАНТЫ ЧИПОВ:\n" + json.dumps(OPTIONS, ensure_ascii=False)
              + "\nextra.darkness — одно из: лучше светлое | баланс | мрачное — да | чем мрачнее, тем лучше; "
              "extra.where — из: в дороге, за рулём, спорт, дома, перед сном, на работе; extra.hours — до 3 | 3–10 | 10–20 | больше 20."
              "\n\nРАССКАЗ:\n" + text + "\n\nОтвет — только JSON этой формы.")
    job = F.new_job()
    import abook_links as L   # noqa: PLC0415
    data, meta, err = L.stream_claude(prompt, job, os.environ.get("ABOOK_QTEXT_MODEL", "sonnet"), timeout=180, budget=0.5)
    if data is not None:
        data.pop("reply", None)
    if data is None:
        raise ValueError(err or "Не удалось разобрать рассказ")
    prev = get_questionnaire(conn, pid)["answers"] or {}
    got = normalize_answers(data, prev)

    def empty(v):
        return not v or (isinstance(v, dict) and not any(not empty(x) for x in v.values()))
    merged = dict(prev)
    for k, v in got.items():
        if k == "brief":
            continue
        pv = prev.get(k)
        if isinstance(v, dict) and isinstance(pv, dict):
            merged[k] = {kk: (vv if empty(pv.get(kk)) else pv.get(kk)) for kk, vv in v.items()}
        elif empty(pv):
            merged[k] = v
    ex = dict(merged.get("extra") or {})
    if not ex.get("text"):
        ex["text"] = _s("Рассказ своими словами: " + text, 2000)
    merged["extra"] = ex
    out = save_draft(conn, pid, {"answers": merged, "step": 6})
    return {**out, "filled": sorted(k for k, v in got.items() if not empty(v)), "cost_usd": meta.get("cost_usd")}


def handle_post(h, conn, p, payload):
    pid = A._pid()
    if p == "/api/questionnaire/from_text":
        return h._json(answers_from_text(conn, pid, payload.get("text")))
    if p == "/api/questionnaire/questions":
        return h._json(gap_questions(conn, pid))
    if p == "/api/profiles":
        op = payload.get("op")
        if op == "create":
            new = create_profile(conn, payload.get("name"))
            return h._json({"created": new, **profiles_payload(conn)})
        target = int(payload.get("id") or 0)
        if op == "rename":
            rename_profile(conn, target, payload.get("name"))
            return h._json(profiles_payload(conn))
        if op == "delete":
            r = delete_profile(conn, target, payload.get("confirm"))
            return h._json({**r, **profiles_payload(conn)})
        raise ValueError("Неизвестная операция")
    if p == "/api/questionnaire":
        return h._json(save_draft(conn, pid, payload))
    if p == "/api/questionnaire/submit":
        return h._json(save_draft(conn, pid, payload, submit=True))
    if p == "/api/ai/run":
        rid = start_run(conn, pid, payload.get("kind"), payload.get("wish"))
        return h._json({"ok": True, "run_id": rid})
    if p == "/api/ai/cancel":
        return h._json({"ok": cancel_run(pid)})
    return h._json({"error": "not found"}, 404)


def inject_html(html):
    from abook_ai_ui import CSS, RAIL, VIEWS, JS   # noqa: PLC0415 (kept separate: big strings)
    for mark, s in (("/*AI:CSS*/", CSS), ("<!--AI:RAIL-->", RAIL), ("<!--AI:VIEWS-->", VIEWS), ("/*AI:JS*/", JS)):
        if html.count(mark) != 1:
            raise RuntimeError(f"abook_ai: маркер {mark} не найден в REVIEW_HTML")
        html = html.replace(mark, s)
    return html
