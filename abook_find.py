"""abook_find — вкладка «Найти» в `abook review`: поиск аудиозаписи книги в интернете и скачивание через
конвейер `abook get` (персистентная очередь загрузок). Консультант, память и «карта связей» — в abook_links.py.

Подключается из abook так же, как abook_ai.py (`FIND.bind(globals())`): все помощники БД, профили, sync_db,
refresh_outputs, yt-dlp-обёртки живут там; этот модуль только добавляет функции. Только stdlib.

Поиск источника — не «спроси Claude», а несколько стратегий параллельно, результаты объединяются:
  • прямой поиск по площадкам без ИИ: YouTube (видео и плейлисты — через yt-dlp из выдры), archive.org
    (advancedsearch + metadata: файлы MP3 по порядку), VK и Rutube (через DuckDuckGo site:…; прямой API Rutube);
  • Claude (`claude -p --model opus`, только WebSearch/WebFetch): разбирает запрос (книга / пожелание / неясно),
    оценивает объём полной записи, даёт поисковые запросы на разных языках и найденные им ссылки;
  • Antigravity (`agy`, Gemini, если установлен): то же параллельно, для разгрузки лимита Claude;
  • второй круг прямого поиска по запросам от ИИ (ru/uk/оригинал/с чтецом/радиоспектакль/«часть 1»).
Каждый кандидат перед показом проверяется yt-dlp без скачивания (`-J`, для плейлиста `--flat-playlist`):
доступен ли, реальная длительность, число частей, пропуски, порядок частей; длительность сверяется с ожидаемым
объёмом полного текста (фрагменты, трейлеры, пересказы, «краткое содержание» отсеиваются). Недоступное не
показывается. Однозначный лучший вариант — одна кнопка «Скачать»; неоднозначно — карточки на выбор.

Скачивание: запись добавляется в отдельный манифест ~/abook/manifests/ui-requests.json (формат обычных манифестов;
в нём только скачанное и качающееся сейчас) и запускается `abook get <манифест> --only <id> --bitrate 128
--retry-failed` фоновым процессом (своя группа процессов; отмена — SIGTERM, abook get помечает книгу «отменено»).
Очередь — ~/abook/find-queue.json (атомарная запись, переживает перезапуск сервера). После скачивания —
`abook-check <id> --json` (нет Claude — предупреждение и без проверки), затем sync_db + файлы для ИИ.

Подмены для проверок (переменные окружения сервера):
    ABOOK_FIND_CLAUDE=<скрипт>   вместо claude (фейк с правдоподобным JSON)
    ABOOK_FIND_AGY=<скрипт>      вместо agy;  ABOOK_FIND_NO_AGY=1 — без Antigravity
    ABOOK_FIND_GET_BIN=<скрипт>  вместо `abook get` (по умолчанию — тот же файл abook, что и сервер)
    ABOOK_CHECK_BIN=<скрипт>     вместо abook-check
    ABOOK_FIND_QUEUE=<файл>      другая очередь загрузок (в тестовом режиме по умолчанию — рядом с тестовой БД)
    ABOOK_FIND_NO_NET=1          без прямого поиска по площадкам (только кандидаты от ИИ; проверка yt-dlp остаётся)
"""
import contextlib
import fcntl
import hashlib
import html as _html
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

A = None          # глобальные имена abook (см. bind)
AI = None         # модуль abook_ai (same_book, known_books, answers_lines…) или None


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
    global A, AI
    A = _NS(g)
    AI = g.get("AI")


# ------------------------------------------------------------------ настройки

FIND_MODEL = os.environ.get("ABOOK_FIND_MODEL", "opus")
FIND_TIMEOUT = int(os.environ.get("ABOOK_FIND_TIMEOUT", "300"))      # на один вызов Claude при поиске, с
AGY_TIMEOUT = int(os.environ.get("ABOOK_AGY_TIMEOUT", "180"))
AGY_GRACE = int(os.environ.get("ABOOK_AGY_GRACE", "40"))          # сколько ждать agy после ответа Claude
AGY_MODEL = os.environ.get("ABOOK_AGY_MODEL", "")                     # пусто — модель agy по умолчанию (Flash)
CLAUDE_BIN = os.environ.get("ABOOK_FIND_CLAUDE") or shutil.which("claude") or str(Path.home() / ".local/bin/claude")
AGY_BIN = os.environ.get("ABOOK_FIND_AGY") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")
NO_AGY = os.environ.get("ABOOK_FIND_NO_AGY") == "1"
NO_NET = os.environ.get("ABOOK_FIND_NO_NET") == "1"
CHECK_BIN = (os.environ.get("ABOOK_CHECK_BIN") or shutil.which("abook-check")
             or str(Path.home() / ".local/bin/abook-check"))
CHECK_TIMEOUT = int(os.environ.get("ABOOK_CHECK_TIMEOUT") or 900)
BITRATE = 128                        # как в памяти проекта: источники YouTube ~130 кбит/с, 128 — без потерь
UI_MANIFEST_NAME = "ui-requests.json"
UI_SECTION = "Открытия/По запросу"
UI_SECTION_NOTE = ("Книги, найденные и скачанные из вкладки «Найти» веб-интерфейса: по названию или по совету "
                   "консультанта.")
DENY = "Bash,Edit,Write,MultiEdit,NotebookEdit,Read,Glob,Grep,Task,Agent,TodoWrite,KillShell,BashOutput"
WEB_TOOLS = ("WebSearch", "WebFetch")
PROBE_MAX = 16                       # сколько кандидатов проверять yt-dlp за один поиск
HTTP_TIMEOUT = 15                    # WSL: соединение к закрытому порту висит — всё сетевое только с таймаутом
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
SOURCE_RULE = ("для личного использования можно брать любые публичные записи с YouTube, VK, Rutube, TikTok, Instagram, "
               "archive.org, LibriVox, архивов радио (Гостелерадиофонд, smotrim.ru), подкастов и любых сайтов, откуда "
               "аудио берёт yt-dlp, включая каналы, перезаливающие коммерческие аудиокниги; НЕЛЬЗЯ: торренты, "
               "файлообменники, сомнительные сайты с установщиками")


def _now():
    return A.now_iso()


def _s(v, n=300):
    return re.sub(r"[ \t]+", " ", str(v if v is not None else "").replace("\r\n", "\n")).strip()[:n]


def _line(v, n=300):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _nt(s):
    s = str(s or "").lower().replace("ё", "е")
    s = re.sub(r"[«»\"'“”„()\[\]{}.,:;!?…/\\|_*#+=~-]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def same_book(a1, t1, a2, t2):
    if AI:
        return AI.same_book(a1, t1, a2, t2)
    return _nt(t1) == _nt(t2) and (not a1 or not a2 or _nt(a1) == _nt(a2))


def workdir():
    d = A.DB_PATH.parent / "ai-work" / "find"
    d.mkdir(parents=True, exist_ok=True)
    return d


def queue_file():
    p = os.environ.get("ABOOK_FIND_QUEUE")
    if p:
        return Path(p)
    return (A.DB_PATH.parent if A.TEST_MODE else A.ABOOK_DIR) / "find-queue.json"


def ui_manifest():
    return A.MANIFESTS_DIR / UI_MANIFEST_NAME


def get_bin():
    return os.environ.get("ABOOK_FIND_GET_BIN") or str(Path(A.__file__).resolve())


def claude_ok():
    return Path(CLAUDE_BIN).exists()


def agy_ok():
    return not NO_AGY and Path(AGY_BIN).exists()


def _load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def _atomic_json(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".tmp.{os.getpid()}.{threading.get_ident()}")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)


@contextlib.contextmanager
def _flock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


# ------------------------------------------------------------------ схема БД

_TABLES = """
CREATE TABLE IF NOT EXISTS find_searches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL, query TEXT NOT NULL,
  status TEXT NOT NULL, started TEXT, finished TEXT, result TEXT, error TEXT, meta TEXT, auto INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS chat_sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL, title TEXT NOT NULL DEFAULT '',
  created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS chat_messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL, role TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '', data TEXT, status TEXT NOT NULL DEFAULT 'done', created TEXT,
  meta TEXT, error TEXT);
CREATE INDEX IF NOT EXISTS chat_messages_s ON chat_messages(session_id, id);
CREATE TABLE IF NOT EXISTS consultant_memory(
  id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER NOT NULL, fact TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'taste', source TEXT NOT NULL DEFAULT 'auto', author TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '', item_id TEXT, session_id INTEGER, created TEXT, updated TEXT);
CREATE INDEX IF NOT EXISTS consultant_memory_p ON consultant_memory(profile_id, id);
CREATE TABLE IF NOT EXISTS book_features(
  item_id TEXT PRIMARY KEY, sig TEXT NOT NULL, features TEXT NOT NULL, model TEXT, created TEXT);
"""
_NEED = {"find_searches", "chat_sessions", "chat_messages", "consultant_memory", "book_features"}


def migrate(conn):
    """Новые таблицы вкладки «Найти». Перед первым созданием — копия базы в db-backups/."""
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not (_NEED - have):
        return None
    backup = None
    with contextlib.suppress(Exception):
        d = A.db_backups_dir()
        d.mkdir(parents=True, exist_ok=True)
        backup = d / f"library-pre-find-{datetime.now():%Y%m%d-%H%M%S}.db"
        conn.execute("VACUUM INTO ?", (str(backup),))
    with A._WRITE_LOCK:
        conn.executescript(_TABLES)
    return backup


def startup(conn):
    b = migrate(conn)
    with A._WRITE_LOCK, A._tx(conn):
        conn.execute("UPDATE find_searches SET status='error', error='прервано: сервер был перезапущен', finished=? "
                     "WHERE status='running'", (_now(),))
        conn.execute("UPDATE chat_messages SET status='error', error='прервано: сервер был перезапущен' "
                     "WHERE status='running'")
        pids = [r[0] for r in conn.execute("SELECT id FROM profiles")]
        if pids:      # данные удалённых профилей (abook_ai удаляет только свои таблицы)
            q = ",".join("?" * len(pids))
            conn.execute(f"DELETE FROM chat_messages WHERE session_id IN (SELECT id FROM chat_sessions "
                         f"WHERE profile_id NOT IN ({q}))", pids)
            for t in ("chat_sessions", "consultant_memory", "find_searches"):
                conn.execute(f"DELETE FROM {t} WHERE profile_id NOT IN ({q})", pids)
    n = resume_queue()
    cat = None
    with contextlib.suppress(Exception):          # «Каталог источников» (abook_catalog.py): таблицы, импорт манифестов
        import abook_catalog as CAT   # noqa: PLC0415
        cat = CAT.startup(conn)
    return {"backup": str(b) if b else None, "resumed": n, "catalog": cat}


# ------------------------------------------------------------------ вызовы ИИ (Claude, Antigravity)

class Cancelled(Exception):
    pass


def new_job(**kw):
    j = {"phase": "Готовлю данные", "events": [], "t0": time.time(), "started": _now(), "cancel": False,
         "procs": set(), "lock": threading.Lock()}
    j.update(kw)
    return j


def event(job, kind, text, who=""):
    with job["lock"]:
        job["events"].append({"t": round(time.time() - job["t0"], 1), "kind": kind, "text": str(text)[:200], "who": who})
        del job["events"][:-16]


def phase(job, text):
    job["phase"] = text


def kill(proc):
    with contextlib.suppress(Exception):
        os.killpg(proc.pid, signal.SIGTERM)
    for _ in range(20):
        if proc.poll() is not None:
            return
        time.sleep(0.15)
    with contextlib.suppress(Exception):
        os.killpg(proc.pid, signal.SIGKILL)


def cancel_job(job):
    job["cancel"] = True
    for p in list(job.get("procs") or ()):
        threading.Thread(target=kill, args=(p,), daemon=True).start()


def _clean_env():
    return {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}


def parse_json_loose(text):
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str):
        return None
    s = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    with contextlib.suppress(Exception):
        return json.loads(s)
    i, j = s.find("{"), s.rfind("}")
    if 0 <= i < j:
        with contextlib.suppress(Exception):
            return json.loads(s[i:j + 1])
    return None


def run_claude(prompt, schema, job, model, tools=(), timeout=360, budget=3.0, who="Claude"):
    """Один headless-вызов Claude Code. -> (data | None, meta, error | None). Без инструментов, кроме
    WebSearch/WebFetch (если переданы): ни файлов, ни shell."""
    import abook_llm as LLM   # noqa: PLC0415 — выбранный провайдер (Claude / Antigravity), см. abook_llm.py
    if LLM.provider() == "agy":
        return LLM.run(prompt, job, model, schema=schema, timeout=timeout,
                       who="Antigravity" if who == "Claude" else who)
    tl = ",".join(tools)
    cmd = [CLAUDE_BIN, "-p", "--model", model, "--output-format", "stream-json", "--verbose", "--safe-mode",
           "--no-session-persistence", "--tools", tl]
    if tools:
        cmd += ["--allowedTools", tl]
    cmd += ["--disallowedTools", DENY, "--permission-mode", "dontAsk", "--max-budget-usd", str(budget),
            "--json-schema", json.dumps(schema, ensure_ascii=False)]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(workdir()), env=_clean_env(), start_new_session=True)
    except OSError as e:
        return None, {"seconds": 0}, f"{who} не запустился: {e}"
    job["procs"].add(proc)
    final, err_tail, n = {}, [], {"search": 0, "fetch": 0}

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
                            n["search"] += 1
                            event(job, "search", inp.get("query") or "", who)
                        elif name == "WebFetch":
                            n["fetch"] += 1
                            event(job, "fetch", inp.get("url") or "", who)
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
            kill(proc)
            break
        time.sleep(0.3)
    with contextlib.suppress(Exception):
        proc.wait(timeout=10)
    for th in ths[1:]:
        th.join(timeout=5)
    job["procs"].discard(proc)
    meta = {"who": who, "model": model, "seconds": round(time.time() - t0, 1), "rc": proc.returncode,
            "cost_usd": final.get("total_cost_usd"), "turns": final.get("num_turns"), **n}
    if reason == "cancel" or job.get("cancel"):
        raise Cancelled()
    if reason == "timeout":
        return None, meta, f"{who}: нет ответа за {timeout // 60} мин"
    if not final:
        tail = " / ".join(x for x in err_tail[-3:] if x)
        return None, meta, f"{who} завершился без результата (код {proc.returncode}){': ' + tail[:300] if tail else ''}"
    if final.get("is_error") or final.get("subtype") not in (None, "success"):
        return None, meta, f"{who}: {final.get('subtype')}: {_line(final.get('result'), 300)}"
    data = final.get("structured_output")
    if data is None:
        data = parse_json_loose(final.get("result"))
    if not isinstance(data, dict):
        return None, meta, f"{who}: ответ не разобрать как JSON"
    return data, meta, None


def _dig(obj, keys, depth=0):
    """Найти в произвольном JSON-ответе agy словарь с нужными ключами (или строку с таким JSON)."""
    if depth > 6:
        return None
    if isinstance(obj, dict):
        if any(k in obj for k in keys):
            return obj
        for v in obj.values():
            r = _dig(v, keys, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _dig(v, keys, depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, str) and "{" in obj:
        d = parse_json_loose(obj)
        if isinstance(d, (dict, list)):
            return _dig(d, keys, depth + 1)
    return None


def run_agy(prompt, schema, job, keys, timeout=AGY_TIMEOUT, who="Antigravity"):
    """Antigravity CLI (Gemini) в печатном режиме, только ответ (файлы он не правит: в headless разрешено только
    чтение). Форма вызова строго `agy --add-dir <каталог> [флаги] -p='<задача>'`. -> (data | None, meta, error)."""
    cmd = [AGY_BIN, "--add-dir", str(workdir()), "--output-format", "json",
           "--json-schema", json.dumps(schema, ensure_ascii=False), "--print-timeout", f"{timeout}s"]
    if AGY_MODEL:
        cmd += ["--model", AGY_MODEL]
    cmd.append(f"-p={prompt}")
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(workdir()), start_new_session=True)
    except OSError as e:
        return None, {"who": who, "seconds": 0}, f"{who} не запустился: {e}"
    job["procs"].add(proc)
    out, err = [], []
    ths = [threading.Thread(target=lambda s, acc: acc.append(s.read()), args=(s, acc), daemon=True)
           for s, acc in ((proc.stdout, out), (proc.stderr, err))]
    for th in ths:
        th.start()
    reason = None
    while proc.poll() is None:
        if job.get("cancel"):
            reason = "cancel"
        elif time.time() > t0 + timeout + 30:
            reason = "timeout"
        if reason:
            kill(proc)
            break
        time.sleep(0.3)
    for th in ths:
        th.join(timeout=5)
    job["procs"].discard(proc)
    meta = {"who": who, "seconds": round(time.time() - t0, 1), "rc": proc.returncode}
    if reason == "cancel" or job.get("cancel"):
        raise Cancelled()
    if job.get("agy_late"):
        return None, meta, f"{who}: не успел — поиск продолжен без него"
    if reason == "timeout":
        return None, meta, f"{who}: нет ответа за {timeout // 60} мин"
    text = (out[0] if out else b"").decode("utf-8", "replace")
    with contextlib.suppress(Exception):      # сырой ответ последнего вызова — для разбора формата
        (workdir() / "agy-last.txt").write_text(text + "\n--- stderr ---\n" + (err[0] if err else b"").decode("utf-8", "replace")[-4000:], encoding="utf-8")
    if proc.returncode != 0 and not text.strip():
        tail = (err[0] if err else b"").decode("utf-8", "replace").strip().splitlines()[-2:]
        return None, meta, f"{who}: код {proc.returncode}{': ' + ' / '.join(tail)[:300] if tail else ''}"
    top = parse_json_loose(text)
    so = top.get("structured_output") if isinstance(top, dict) else None   # agy --output-format json: {"structured_output": …}
    data = _dig(so, keys) or _dig(top, keys) or _dig(text, keys)
    if isinstance(top, dict) and top.get("status") and top.get("status") != "SUCCESS" and not data:
        return None, meta, f"{who}: статус {top.get('status')}"
    if not isinstance(data, dict):
        return None, meta, f"{who}: ответ не разобрать как JSON"
    return data, meta, None


# ------------------------------------------------------------------ поиск источника: разбор запроса

_STR = {"type": "string"}
_NUM = {"type": "number"}
_CAND = {"type": "object", "additionalProperties": False,
         "required": ["urls", "platform", "narrator", "kind", "lang", "duration_h", "note"],
         "properties": {"urls": {"type": "array", "items": _STR}, "platform": _STR, "narrator": _STR,
                        "kind": {"type": "string", "enum": ["audiobook", "radioplay", "reading", "other"]},
                        "lang": _STR, "duration_h": _NUM, "note": _STR}}
_WORK = {"type": "object", "additionalProperties": False,
         "required": ["author", "title", "original_title", "alt_titles", "expected_h", "narrator_wanted", "kind_wanted"],
         "properties": {"author": _STR, "title": _STR, "original_title": _STR,
                        "alt_titles": {"type": "array", "items": _STR}, "expected_h": _NUM,
                        "narrator_wanted": _STR,
                        "kind_wanted": {"type": "string", "enum": ["audiobook", "radioplay", "any"]}}}
FIND_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "work", "queries", "candidates", "section", "about", "why", "clarify"],
    "properties": {"kind": {"type": "string", "enum": ["book", "prompt", "unclear"]}, "work": _WORK,
                   "queries": {"type": "array", "items": _STR}, "candidates": {"type": "array", "items": _CAND},
                   "section": _STR, "about": _STR, "why": _STR, "clarify": _STR}}
AGY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["kind", "work", "queries", "candidates"],
    "properties": {"kind": {"type": "string", "enum": ["book", "prompt", "unclear"]}, "work": _WORK,
                   "queries": {"type": "array", "items": _STR}, "candidates": {"type": "array", "items": _CAND}}}


def _profile_brief(conn, pid, n=1600):
    """Коротко о вкусе слушателя для промпта поиска (why/раздел): анкета или бриф."""
    if not AI:
        return ""
    try:
        q = AI.get_questionnaire(conn, pid)["answers"]
        lines = AI.answers_lines(q, lite=True)
        return _line("; ".join(f"{lab}: {t}" for _, lab, t in lines), n)
    except Exception:
        return ""


def _sections(conn):
    return [r[0] for r in conn.execute("SELECT DISTINCT section FROM items WHERE in_library=1 AND section!='' "
                                       "ORDER BY section")]


def find_prompt(conn, pid, q):
    secs = _sections(conn)
    return "\n\n".join([
        "Ты ищешь в интернете аудиозапись книги для личной аудиотеки слушателя (русско/украиноязычный). "
        f"Запрос слушателя дословно: «{q}».",
        "Сначала пойми запрос:\n"
        "- kind=\"book\" — назван конкретный текст (название; возможно автор, чтец, перевод, вид записи);\n"
        "- kind=\"prompt\" — не конкретная книга, а пожелание («что-нибудь как Солярис, но короче», «мрачное про "
        "космос»). Тогда больше ничего не ищи: work с пустыми строками и expected_h=0, candidates и queries пустые;\n"
        "- kind=\"unclear\" — назван только автор или цикл, или непонятно, какое произведение; clarify — короткий "
        "вопрос с 2–4 вариантами.",
        "Для kind=\"book\":\n"
        "1. work: author (как принято по-русски), title (русское название), original_title, alt_titles (другие "
        "переводы, украинское название), expected_h — сколько часов длится ПОЛНАЯ несокращённая аудиокнига (оцени по "
        "объёму текста, ≈9000 слов в час), narrator_wanted — чтец, если слушатель его назвал (иначе пусто), "
        "kind_wanted — radioplay, если просили радиоспектакль/постановку, audiobook — если просили именно книгу, "
        "иначе any.\n"
        "2. queries — 4–8 поисковых запросов для YouTube/VK/Rutube: по-русски; по-украински, если есть перевод; "
        "оригинальное название; с чтецом; «радиоспектакль»; «аудиокнига полностью»; «часть 1».\n"
        "3. candidates — до 8 КОНКРЕТНЫХ записей, которые ты реально видел (WebSearch/WebFetch, не больше 8 "
        "обращений всего): YouTube (видео или плейлист), VK видео, Rutube, archive.org, smotrim.ru и т. п. "
        f"Правило источников (решение слушателя, не обсуждать): {SOURCE_RULE}. Если запись из нескольких частей — "
        "urls в порядке частей или одна ссылка на плейлист. Не выдумывай ссылки: только то, что было в выдаче или на "
        "странице. narrator, kind (audiobook|radioplay|reading|other), lang (ru|uk|en), duration_h (0, если не видно), "
        "note — сокращённая? ИИ-озвучка? неполная? фрагмент?\n"
        "4. section — раздел библиотеки для этой книги: скопируй точно подходящий из списка ниже или напиши "
        f"«{UI_SECTION}».\n"
        "5. about — 2 предложения о книге без спойлеров; why — 1–2 предложения на «вы», чем книга зацепит этого "
        "слушателя (его вкус ниже).",
        "Качество (главный фильтр): полная несокращённая запись; живой голос лучше ИИ-озвучки; язык строго "
        "ru → uk → en; хороший чтец или хороший радиоспектакль.",
        "Разделы библиотеки: " + "; ".join(secs[:120]),
        "Вкус слушателя (коротко): " + (_profile_brief(conn, pid) or "неизвестен"),
        "Всё по-русски. Ответ — только JSON по схеме."])


def agy_prompt(q):
    return ("Найди в интернете (веб-поиск) аудиозапись книги по запросу слушателя: «" + q + "». "
            "Сначала определи kind: book (конкретная книга), prompt (не книга, а пожелание — тогда ничего не ищи, "
            "candidates пустые), unclear (только автор/цикл). Для book: work (author и title по-русски, "
            "original_title, alt_titles, expected_h — часы ПОЛНОЙ несокращённой аудиокниги по объёму текста, "
            "narrator_wanted — чтец, если назван, kind_wanted audiobook|radioplay|any), queries — 4–8 запросов для "
            "поиска на YouTube/VK/Rutube (ru, uk, оригинал, с чтецом, радиоспектакль), candidates — до 8 РЕАЛЬНЫХ ссылок "
            "на полные записи (YouTube видео или плейлист, VK, Rutube, archive.org, smotrim.ru): urls (части по "
            "порядку или плейлист), platform, narrator, kind, lang, duration_h (0 если неизвестно), note. "
            f"Правило источников: {SOURCE_RULE}. Язык записи строго ru → uk → en. Не выдумывай ссылки. "
            "Ничего не создавай и не меняй в файлах — только ответ. Ответ — только JSON по заданной схеме.")


_NARR_RX = re.compile(r"(?:чтец|чтеца|читает|читає|читал|исполнитель|озвучка|озвучил\w*|narrated by|read by)"
                      r"\s*[:\-–—]?\s*([A-ZА-ЯЁІЇЄҐ][\w'’\-]+(?:\s+[A-ZА-ЯЁІЇЄҐ][\w'’\-]+){0,2})", re.U)
_PROMPTISH = re.compile(r"\b(что[- ]?(?:нибудь|то)|посоветуй|посоветуйте|похож\w*|как\s+[«\"]?\w+[»\"]?\s*,?\s*но\b|"
                        r"хочу\s+(?:что|книг|послушать)|подбери|про\s+\w+\s+и\b|мрачн\w*|весел\w*|лёгк\w*|легк\w*|"
                        r"на вечер|перед сном|чего[- ]нибудь)", re.I)


def heuristic_parse(q):
    """Без ИИ: «Автор — Название», чтец из «чтец X», пожелание по ключевым словам."""
    narr = ""
    m = _NARR_RX.search(q)
    if m:
        narr = m.group(1).strip()
    core = _NARR_RX.sub(" ", q)
    core = re.sub(r"\b(аудиокнига|аудиокниги|радиоспектакль|полностью|слушать|скачать)\b", " ", core, flags=re.I)
    core = re.sub(r"\s+", " ", core).strip(" ,.;—-")
    parts = re.split(r"\s+[—–-]\s+|\s*:\s+", core, maxsplit=1)
    author, title = (parts[0].strip(), parts[1].strip()) if len(parts) == 2 else ("", core)
    kind = "prompt" if _PROMPTISH.search(q) and len(q.split()) >= 3 else "book"
    kw = "radioplay" if re.search(r"радио|спектакл|постановк", q, re.I) else "any"
    return {"kind": kind, "work": {"author": author, "title": title, "original_title": "", "alt_titles": [],
                                   "expected_h": 0, "narrator_wanted": narr, "kind_wanted": kw},
            "queries": [], "candidates": [], "section": "", "about": "", "why": "", "clarify": ""}


# ------------------------------------------------------------------ поиск источника: площадки

def _http(url, timeout=HTTP_TIMEOUT, data=None):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept-Language": "ru,uk;q=0.8,en;q=0.5"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _ytdlp(args, timeout):
    """yt-dlp из выдры (как в abook), с быстрыми таймаутами для поиска/проверки."""
    fast = ["--socket-timeout", "15", "--retries", "2", "--extractor-retries", "1"]
    return A._ytdlp_run(list(args[:-1]) + fast + [args[-1]], workdir(), timeout)


def _cand(url, found_by, query="", **kw):
    c = {"url": url, "urls": [url], "platform": platform_of(url), "type": "video", "title": "", "channel": "",
         "duration": None, "count": None, "found_by": [found_by], "queries": [query] if query else [],
         "narrator": "", "kind": "", "lang": "", "note": "", "views": None}
    c.update({k: v for k, v in kw.items() if v is not None})
    return c


def platform_of(url):
    h = urllib.parse.urlparse(url or "").netloc.lower()
    for k, v in (("youtu", "YouTube"), ("vk.com", "VK"), ("vkvideo", "VK"), ("rutube", "Rutube"),
                 ("archive.org", "archive.org"), ("smotrim", "smotrim.ru"), ("ok.ru", "OK"),
                 ("zvukislov", "Звуки слов"), ("librivox", "LibriVox"), ("soundcloud", "SoundCloud")):
        if k in h:
            return v
    return h.removeprefix("www.") or "?"


def search_youtube(q, n=8):
    proc, err = _ytdlp(["--flat-playlist", "-J", f"ytsearch{n}:{q}"], 60)
    if err or proc.returncode != 0:
        raise RuntimeError(err or A._ytdlp_error(proc))
    out = []
    for e in (json.loads(proc.stdout).get("entries") or []):
        if not e or not e.get("id") or (e.get("live_status") in ("is_live", "is_upcoming")):
            continue
        out.append(_cand(f"https://www.youtube.com/watch?v={e['id']}", "поиск YouTube", q, title=e.get("title") or "",
                         channel=e.get("channel") or e.get("uploader") or "", duration=e.get("duration"),
                         views=e.get("view_count")))
    return out


def search_youtube_playlists(q, n=6):
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q) + "&sp=EgIQAw%253D%253D"
    proc, err = _ytdlp(["--flat-playlist", "-J", "--playlist-end", str(n), url], 60)
    if err or proc.returncode != 0:
        raise RuntimeError(err or A._ytdlp_error(proc))
    out = []
    for e in (json.loads(proc.stdout).get("entries") or []):
        if e and e.get("id") and (e.get("ie_key") == "YoutubeTab" or "list=" in (e.get("url") or "")):
            out.append(_cand(f"https://www.youtube.com/playlist?list={e['id']}", "плейлисты YouTube", q,
                             type="playlist", title=e.get("title") or "", channel=e.get("channel") or ""))
    return out


def search_archive(q, n=6):
    u = ("https://archive.org/advancedsearch.php?q=" + urllib.parse.quote(f"({q}) AND mediatype:audio")
         + "&fl[]=identifier&fl[]=title&fl[]=creator&rows=" + str(n) + "&output=json")
    d = json.loads(_http(u))
    out = []
    for doc in (d.get("response") or {}).get("docs") or []:
        ident = doc.get("identifier")
        if ident:
            cr = doc.get("creator")
            out.append(_cand(f"https://archive.org/details/{ident}", "archive.org", q, type="files",
                             title=str(doc.get("title") or ident), channel=", ".join(cr) if isinstance(cr, list) else str(cr or "")))
    return out


def search_ddg(q, site):
    html = _http("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(f"{q} site:{site}"))
    out, seen = [], set()
    for m in re.finditer(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
        href, title = m.group(1), _html.unescape(re.sub(r"<[^>]+>", "", m.group(2)))
        mm = re.search(r"uddg=([^&]+)", href)
        url = urllib.parse.unquote(mm.group(1)) if mm else href
        if not re.search(r"(vk\.com|vkvideo\.ru)/(video|playlist)|rutube\.ru/(video|plst)/", url) or url in seen:
            continue
        seen.add(url)
        out.append(_cand(url, "DuckDuckGo", q, title=_line(title, 200)))
    return out[:6]


def search_rutube(q, n=6):
    d = json.loads(_http("https://rutube.ru/api/search/video/?query=" + urllib.parse.quote(q), timeout=8))
    out = []
    for r in (d.get("results") or [])[:n]:
        if r.get("video_url"):
            out.append(_cand(r["video_url"], "поиск Rutube", q, title=r.get("title") or "",
                             channel=(r.get("author") or {}).get("name") or "", duration=r.get("duration")))
    return out


# ------------------------------------------------------------------ поиск источника: проверка yt-dlp

_JUNK = re.compile(r"кратк\w* (?:содерж|пересказ)|пересказ|summary|обзор|трейлер|trailer|буктрейлер|анализ|разбор|"
                   r"лекци|review|отрывок|фрагмент|отзыв|реакци|fan ?fic|фанфик|мультфильм|фильм \d{4}|кино\b|"
                   r"за \d+ минут|in \d+ minutes|шортс|#shorts", re.I)
_RADIO = re.compile(r"радио|спектакл|постановк|инсцениров|аудиоспектакл|радіо|виста", re.I)
_AIV = re.compile(r"\bИИ\b|нейросет|\bAI\b|синтез|neural|искусственн", re.I)
_UK = re.compile(r"[іїєґІЇЄҐ]|аудіокниг|читає|частина", re.I)
_CYR = re.compile(r"[а-яё]", re.I)
_TNARR = re.compile(r"(?:читает|читає|чтец|читал[аи]?|исп\.?|narrated by|read by|озвуч\w*)\s*[:\-–—]?\s*"
                    r"([A-ZА-ЯЁІЇЄҐ][\w'’.\-]+(?:\s+[A-ZА-ЯЁІЇЄҐ][\w'’.\-]+){0,2})", re.U)


def _lang_of(text):
    if _UK.search(text or ""):
        return "uk"
    return "ru" if _CYR.search(text or "") else "en"


def _stem_words(s):
    return [w[:5] for w in _nt(s).split() if len(w) >= 3]


def relevance(text, titles):
    """Доля слов названия (по основам), найденных в тексте кандидата; максимум по вариантам названия."""
    have = set(_stem_words(text))
    best = 0.0
    for t in titles:
        ws = _stem_words(t)
        if ws:
            best = max(best, sum(1 for w in ws if w in have) / len(ws))
    return best


def _archive_files(ident):
    """archive.org: MP3-файлы элемента в порядке имени (одна группа формата), длительность каждого."""
    d = json.loads(_http(f"https://archive.org/metadata/{urllib.parse.quote(ident)}", timeout=20))
    files = d.get("files") or []
    groups = {}
    for f in files:
        fmt = str(f.get("format") or "")
        name = str(f.get("name") or "")
        if "MP3" in fmt.upper() and name.lower().endswith(".mp3"):
            groups.setdefault(fmt, []).append(f)
    if not groups:
        return None
    # оригиналы (source=original) важнее производных; иначе самая многочисленная группа
    fmt = max(groups, key=lambda k: (sum(1 for f in groups[k] if f.get("source") == "original"), len(groups[k])))
    fl = sorted(groups[fmt], key=lambda f: [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", f["name"])])

    def secs(v):
        try:
            if ":" in str(v):
                p = [float(x) for x in str(v).split(":")]
                return sum(x * 60 ** i for i, x in enumerate(reversed(p)))
            return float(v)
        except (TypeError, ValueError):
            return None
    meta = d.get("metadata") or {}
    return {"title": str(meta.get("title") or ident), "channel": str(meta.get("creator") or "archive.org"),
            "urls": [f"https://archive.org/download/{ident}/{urllib.parse.quote(f['name'])}" for f in fl],
            "titles": [f.get("title") or f["name"] for f in fl], "durations": [secs(f.get("length")) for f in fl]}


_REACH = {}                   # хост -> (доступен?, когда проверяли): VK/Rutube из WSL бывают недоступны — не ждать 15 с на каждом


def reachable(host, port=443):
    host = (host or "").lower()
    ok, t = _REACH.get(host, (None, 0))
    if ok is not None and time.time() - t < 600:
        return ok
    try:
        socket.create_connection((host, port), timeout=6).close()
        ok = True
    except OSError:
        ok = False
    _REACH[host] = (ok, time.time())
    return ok


def probe(c):
    """Проверка скачиваемости без загрузки. Заполняет c['probe'] = {ok, error, duration, parts, …}."""
    pr = {"ok": False, "error": "", "duration": None, "parts": 1, "unavailable": 0, "order": None, "titles": []}
    c["probe"] = pr
    url = c["url"]
    host = urllib.parse.urlparse(url).hostname or ""
    if host and not reachable(host):
        pr["error"] = f"{host} не открывается с этого компьютера — скачать не получится"
        return c
    try:
        if c["platform"] == "archive.org" and "/details/" in url:
            ident = url.split("/details/", 1)[1].split("/")[0].split("?")[0]
            af = _archive_files(ident)
            if not af:
                pr["error"] = "нет MP3-файлов"
                return c
            c["urls"], c["type"] = af["urls"], "files"
            c["title"] = c["title"] or af["title"]
            c["channel"] = c["channel"] or af["channel"]
            pr["parts"], pr["titles"] = len(af["urls"]), af["titles"]
            d = af["durations"]
            pr["duration"] = sum(x for x in d if x) or None
            with contextlib.suppress(Exception):       # первый файл действительно отдаётся
                req = urllib.request.Request(af["urls"][0], method="HEAD", headers={"User-Agent": UA})
                urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).close()
                pr["ok"] = bool(pr["duration"])
            if not pr["ok"]:
                pr["error"] = pr["error"] or "файл не отдаётся или неизвестна длительность"
            return c
        if len(c["urls"]) > 1:                       # части отдельными ссылками (от ИИ)
            total, titles = 0.0, []
            for u in c["urls"][:40]:
                proc, err = _ytdlp(["-J", "--no-playlist", u], 60)
                if err or proc.returncode != 0:
                    pr["error"] = f"часть недоступна: {(err or A._ytdlp_error(proc))[:160]}"
                    pr["unavailable"] += 1
                    return c
                info = json.loads(proc.stdout)
                total += float(info.get("duration") or 0)
                titles.append(info.get("title") or "")
                if not c["title"]:
                    c["title"], c["channel"] = info.get("title") or "", info.get("channel") or info.get("uploader") or ""
            pr.update(ok=total > 0, duration=total or None, parts=len(c["urls"]), titles=titles)
            pr["order"] = A.title_order_problem(titles)
            c["type"] = "parts"
            return c
        if A.is_playlist_url(url):
            proc, err = _ytdlp(["--flat-playlist", "--yes-playlist", "-J", url], 90)
            if err or proc.returncode != 0:
                pr["error"] = (err or A._ytdlp_error(proc))[:200]
                return c
            info = json.loads(proc.stdout)
            ents = [e or {} for e in (info.get("entries") or [])]
            bad = [e for e in ents if (not (e.get("url") or e.get("id"))) or
                   A._UNAVAILABLE_TITLE.match((e.get("title") or "").strip()) or
                   e.get("availability") in ("private", "needs_auth", "subscriber_only")]
            titles = [e.get("title") or "" for e in ents if e not in bad]
            durs = [e.get("duration") for e in ents if e not in bad]
            pr.update(parts=len(ents) - len(bad), unavailable=len(bad), titles=titles,
                      duration=sum(float(x) for x in durs if x) or None)
            pc = info.get("playlist_count")
            if pc and pc != len(ents):
                pr["unavailable"] += abs(pc - len(ents))
            pr["order"] = A.title_order_problem(titles)
            c["type"] = "playlist"
            c["title"] = info.get("title") or c["title"]
            c["channel"] = info.get("channel") or info.get("uploader") or c["channel"]
            if None in durs and pr["duration"]:
                pr["partial_duration"] = True
            pr["ok"] = pr["parts"] > 0 and not pr["unavailable"]
            if pr["unavailable"]:
                pr["error"] = f"в плейлисте недоступно частей: {pr['unavailable']}"
            elif not pr["parts"]:
                pr["error"] = "плейлист пуст"
            return c
        proc, err = _ytdlp(["-J", "--no-playlist", url], 60)
        if err or proc.returncode != 0:
            pr["error"] = (err or A._ytdlp_error(proc))[:200]
            return c
        info = json.loads(proc.stdout)
        if info.get("live_status") in ("is_live", "is_upcoming"):
            pr["error"] = "это трансляция"
            return c
        fmts = info.get("formats") or []
        if fmts and not any((f.get("acodec") or "none") != "none" for f in fmts):
            pr["error"] = "нет аудиодорожки"
            return c
        c["title"] = info.get("title") or c["title"]
        c["channel"] = info.get("channel") or info.get("uploader") or c["channel"]
        c["views"] = info.get("view_count") or c.get("views")
        pr.update(ok=bool(info.get("duration")), duration=info.get("duration"), titles=[c["title"]])
        if not pr["ok"]:
            pr["error"] = "неизвестна длительность"
    except Exception as e:           # сеть, JSON, что угодно — кандидат просто не проходит
        pr["error"] = f"{type(e).__name__}: {e}"[:200]
    return c


# ------------------------------------------------------------------ поиск источника: оценка

def _good_narrators():
    with contextlib.suppress(Exception):
        return [w for w in re.split(r"[,;]\s*|\s+и\s+", A.load_brief().get("narrators") or "") if len(w) >= 4]
    return []


_LANGW = threading.local()   # баллы языков текущего профиля (abook_ai.lang_weights) — ставит воркер поиска


def assess(c, work, titles):
    """Итог по кандидату: годится ли, пометки, баллы. Меняет c на месте."""
    pr = c.get("probe") or {}
    flags, drop = [], None
    text = f"{c.get('title', '')} {c.get('channel', '')} {' '.join(pr.get('titles') or [])[:600]}"
    head = f"{c.get('title', '')} {c.get('note', '')}"
    rel = relevance(f"{c.get('title', '')} {' '.join((pr.get('titles') or [])[:3])}", titles) if titles else 1.0
    llm = any(x in ("Claude", "Antigravity") for x in c["found_by"])
    import abook_links as _L   # noqa: PLC0415
    rep = _L.is_reported(c.get("url"))
    if rep:
        drop = "вы пожаловались: " + rep
    elif not pr.get("ok"):
        drop = "недоступно: " + (pr.get("error") or "не проверено")
    elif _JUNK.search(c.get("title") or ""):
        drop = "похоже на пересказ/обзор/фрагмент"
    elif titles and rel < (0.5 if llm else 0.6):
        drop = "в названии записи нет этого произведения"
    kind = c.get("kind") or ("radioplay" if _RADIO.search(head) else "audiobook")
    c["kind"] = kind
    lang = c.get("lang") if c.get("lang") in ("ru", "uk", "en") else _lang_of(text)
    c["lang"] = lang
    if not c.get("narrator"):
        m = _TNARR.search(" ".join([c.get("title") or ""] + (pr.get("titles") or [])[:2]))
        if m:
            c["narrator"] = m.group(1).strip(" .")
    c["ai_voice"] = bool(_AIV.search(f"{c.get('narrator', '')} {c.get('title', '')} {c.get('note', '')}"))
    dur = pr.get("duration") or 0
    exp = float(work.get("expected_h") or 0) * 3600
    ratio = dur / exp if exp and dur else None
    c["ratio"] = round(ratio, 2) if ratio else None
    if drop is None and dur:
        if ratio is not None:
            lo = 0.12 if kind == "radioplay" else 0.55
            if ratio < lo:
                drop = f"слишком коротко: {dur / 3600:.1f} ч при ожидаемых ~{exp / 3600:.1f} ч — фрагмент или сокращение"
            elif kind != "radioplay" and ratio < 0.8:
                flags.append(f"короче ожидаемого (~{exp / 3600:.1f} ч): возможно сокращение")
            elif ratio > 1.9:
                flags.append(f"длиннее ожидаемого (~{exp / 3600:.1f} ч): возможно, несколько книг или лишнее")
        elif dur < 300:
            drop = "короче 5 минут"
    if pr.get("order"):
        flags.append("порядок частей: " + pr["order"][:160])
    if pr.get("partial_duration"):
        flags.append("длительность известна не для всех частей")
    if c["ai_voice"]:
        flags.append("ИИ-озвучка")
    if kind == "radioplay":
        flags.append("радиоспектакль — инсценировка, не полный текст")
    # баллы: полнота, язык, чтец, живой голос, кто нашёл, популярность, точность названия
    s = 50.0
    s += 20 * min(1.0, (ratio or 0.9) / 0.9) if (ratio or not exp) else 0
    if ratio is not None and kind != "radioplay" and ratio < 0.8:
        s -= 15
    s += (getattr(_LANGW, "w", None) or {"ru": 15, "uk": 15, "en": 3}).get(lang, 0)   # по анкете профиля
    want = _nt(work.get("narrator_wanted"))
    narr = _nt(c.get("narrator"))
    if want:
        hit = any(w[:5] in _nt(text + " " + narr) for w in want.split() if len(w) >= 4)
        c["narrator_match"] = hit
        s += 25 if hit else -6
    if narr and any(g.lower()[:5] in narr for g in _good_narrators()):
        s += 6
    if c["ai_voice"]:
        s -= 12
    kw = work.get("kind_wanted") or "any"
    if kind == "radioplay":
        s += 10 if kw == "radioplay" else -4
    elif kw == "radioplay":
        s -= 10
    if c["type"] == "video":
        s += 3
    if pr.get("order"):
        s -= 10
    s += min(6, 2 * len(set(c["found_by"])))
    if c.get("views"):
        s += min(6.0, math.log10(float(c["views"]) + 1))
    s += 10 * rel
    c["score"] = round(s, 1)
    c["flags"] = flags
    c["drop"] = drop
    c["rel"] = round(rel, 2)
    return c


def _key(url):
    return A.source_id(url) if url else ""


# ------------------------------------------------------------------ поиск источника: конвейер

_SJOBS = {}                  # id поиска -> живая задача
_SLOCK = threading.Lock()
MAX_SEARCHES = 2


def library_match(conn, author, title):
    """Эта книга уже есть? -> {"item", "state": downloaded|catalog|queued} или None."""
    if not title:
        return None
    best = None
    for it in A.get_items(conn, where="i.in_library=1 OR i.custom=1"):
        if same_book(author or "", title, it["author"], it["title"]):
            rank = 3 if it["has_file"] else 2 if it["in_library"] else 1
            if not best or rank > best[0]:
                best = (rank, it)
    if not best:
        return None
    it = best[1]
    st = "downloaded" if it["has_file"] else "downloading" if it["status"] == "in_progress" else \
        "catalog" if it["in_library"] and not it["custom"] else "known"
    return {"item": it, "state": st}


def start_search(conn, pid, q, auto=False):
    q = re.sub(r"\s+", " ", str(q or "")).strip()[:300]
    if len(q) < 2:
        raise ValueError("Введите название книги или запрос")
    with _SLOCK:
        if sum(1 for j in _SJOBS.values() if not j.get("done")) >= MAX_SEARCHES:
            raise ValueError("Уже идут два поиска — дождитесь их или отмените")
    with A._WRITE_LOCK, A._tx(conn):
        cur = conn.execute("INSERT INTO find_searches(profile_id,query,status,started,auto) VALUES(?,?,'running',?,?)",
                           (pid, q, _now(), 1 if auto else 0))
        sid = cur.lastrowid
    job = new_job(id=sid, pid=pid, q=q, auto=bool(auto), sources={})
    with _SLOCK:
        _SJOBS[sid] = job
    threading.Thread(target=_search_worker, args=(sid, job), daemon=True, name=f"abook-find-{sid}").start()
    return sid


def cancel_search(sid):
    with _SLOCK:
        job = _SJOBS.get(sid)
    if not job or job.get("done"):
        return False
    cancel_job(job)
    return True


def _src(job, name, state, n=None, note=""):
    with job["lock"]:
        job["sources"][name] = {"state": state, "n": n, "note": note[:160]}


def _merge(pool, cands, order):
    for c in cands:
        k = _key(c["url"])
        if not k:
            continue
        if k in pool:
            p = pool[k]
            p["found_by"] = sorted(set(p["found_by"]) | set(c["found_by"]))
            p["queries"] = (p["queries"] + [q for q in c["queries"] if q not in p["queries"]])[:4]
            for f in ("title", "channel", "duration", "narrator", "kind", "lang", "note", "views", "catalog"):
                if not p.get(f) and c.get(f):
                    p[f] = c[f]
            if len(c.get("urls") or []) > len(p.get("urls") or []):
                p["urls"], p["type"] = c["urls"], c["type"]
        else:
            pool[k] = c
            order.append(k)


def _llm_cands(data, who):
    out = []
    for x in (data or {}).get("candidates") or []:
        if not isinstance(x, dict):
            continue
        urls = [u.strip() for u in (x.get("urls") or []) if isinstance(u, str) and re.match(r"https?://", u.strip())]
        if not urls:
            continue
        narr = _s(x.get("narrator"), 120)
        if re.match(r"(неизвест|не указан|unknown|n/?a\b|нет\b|-$)", narr, re.I):
            narr = ""
        c = _cand(urls[0], who, narrator=narr,
                  kind=x.get("kind") if x.get("kind") in ("audiobook", "radioplay", "reading") else "",
                  lang=_s(x.get("lang"), 4).lower(), note=_s(x.get("note"), 300))
        if len(urls) > 1:
            c["urls"], c["type"] = urls[:40], "parts"
        if x.get("duration_h"):
            with contextlib.suppress(TypeError, ValueError):
                c["duration"] = float(x["duration_h"]) * 3600
        out.append(c)
    return out


def _run_platforms(job, queries, rnd):
    """Прямой поиск по площадкам (без ИИ), параллельно. queries: [(площадка, запрос)]."""
    fns = {"yt": search_youtube, "ytpl": search_youtube_playlists, "archive": search_archive,
           "vk": lambda q: search_ddg(q, "vk.com"), "rutube": lambda q: search_ddg(q, "rutube.ru"),
           "rutube_api": search_rutube, "kv": lambda q: _cat().site_cands("knigavuhe", q),
           "ak": lambda q: _cat().site_cands("akniga", q)}
    names = {"yt": "поиск YouTube", "ytpl": "плейлисты YouTube", "archive": "archive.org", "vk": "VK (через DuckDuckGo)",
             "rutube": "Rutube (через DuckDuckGo)", "rutube_api": "Rutube",
             "kv": "knigavuhe.org", "ak": "akniga.org"}
    res, errs = [], {}
    if NO_NET or not queries:
        return res

    def one(pq):
        p, q = pq
        if job.get("cancel"):
            return []
        try:
            r = fns[p](q)
            return r
        except Exception as e:
            errs.setdefault(p, f"{type(e).__name__}: {e}"[:140])
            return []
    with ThreadPoolExecutor(max_workers=6) as ex:
        outs = list(ex.map(one, queries))
    per = {}
    for (p, q), o in zip(queries, outs):
        res += o
        per[p] = per.get(p, 0) + len(o)
    for p in {p for p, _ in queries}:
        key = names[p] + (" · 2-й круг" if rnd == 2 else "")
        _src(job, key, "error" if p in errs and not per.get(p) else "done", per.get(p, 0), errs.get(p, ""))
    return res


def _cat():
    import abook_catalog as CAT   # noqa: PLC0415
    return CAT


def _catalog_cands(conn, job, qs):
    """L1: мгновенный поиск по «Каталогу источников» (без сети). Карточки — сразу в job["catalog"] (UI видит до
    live-поиска); кандидаты — дальше в общий конвейер (probe/assess). Только для спонсоров не попадают."""
    cands, pubs, ms = [], [], 0.0
    seen = set()
    for q in qs:
        if not q:
            continue
        try:
            res, t = _cat().search(conn, q, limit=10)
        except Exception as e:
            _src(job, "Каталог", "error", note=f"{type(e).__name__}: {e}")
            return []
        ms += t
        for d in res:
            if d["key"] in seen or d.get("in_library"):
                continue
            seen.add(d["key"])
            pubs.append(d)
            r = _cat().get_row(conn, d["key"])
            if r and r["downloadable"]:
                cands.append(_cat().to_cand(r))
    with job["lock"]:
        old = {x["key"] for x in job.get("catalog") or []}
        job["catalog"] = (job.get("catalog") or []) + [d for d in pubs if d["key"] not in old]
    _src(job, "Каталог", "done", len(job["catalog"]), f"{ms:.0f} мс")
    return cands


def _round2_queries(work, llm_queries):
    a, t = work.get("author") or "", work.get("title") or ""
    sur = a.split()[-1] if a else ""
    qs = []
    if t:
        qs += [f"{a} {t} аудиокнига".strip(), f"{t} аудиокнига полностью"]
        if work.get("narrator_wanted"):
            qs.append(f"{t} читает {work['narrator_wanted']}")
        if work.get("kind_wanted") != "audiobook":
            qs.append(f"{sur} {t} радиоспектакль".strip())
        for alt in (work.get("alt_titles") or [])[:2]:
            qs.append(f"{alt} аудіокнига" if _UK.search(alt) else f"{alt} аудиокнига")
        if work.get("original_title") and _nt(work["original_title"]) != _nt(t):
            qs.append(f"{work['original_title']} audiobook")
    qs += list(llm_queries)
    seen, out = set(), []
    for q in qs:
        k = _nt(q)
        if k and k not in seen:
            seen.add(k)
            out.append(q)
    return out


def _search_worker(sid, job):
    conn = A.db_connect()
    status, err, result, meta = "error", None, None, {"calls": []}
    q, pid = job["q"], job["pid"]
    try:
        A._PROFILE.id = pid
        with contextlib.suppress(Exception):
            _LANGW.w = AI.lang_weights(conn, pid) if AI else None
        pool, order = {}, []
        heur = heuristic_parse(q)
        # 1. параллельно: Claude, Antigravity, прямой поиск по сырому запросу
        out = {}

        def llm_claude():
            if not claude_ok():
                _src(job, "Claude", "skip", note="claude не найден")
                return
            _src(job, "Claude", "running")
            try:
                d, m, e = run_claude(find_prompt(conn, pid, q), FIND_SCHEMA, job, FIND_MODEL, WEB_TOOLS,
                                     timeout=FIND_TIMEOUT, budget=3.0, who="Claude")
            except Cancelled:
                return
            meta["calls"].append(m)
            out["claude"] = d
            _src(job, "Claude", "done" if d else "error", len((d or {}).get("candidates") or []), e or "")

        def llm_agy():
            if not agy_ok():
                _src(job, "Antigravity", "skip", note="agy не установлен или выключен")
                return
            _src(job, "Antigravity", "running")
            try:
                d, m, e = run_agy(agy_prompt(q), AGY_SCHEMA, job, keys=("candidates", "work"))
            except Cancelled:
                return
            meta["calls"].append(m)
            out["agy"] = d
            _src(job, "Antigravity", "done" if d else "error", len((d or {}).get("candidates") or []), e or "")

        # 0. L1: каталог источников — мгновенно, до ИИ и площадок
        cat0 = _catalog_cands(conn, job, [q])
        phase(job, "Ищу: площадки напрямую, Claude и Antigravity параллельно")
        ths = [threading.Thread(target=f, daemon=True) for f in (llm_claude, llm_agy)]
        for t in ths:
            t.start()
        raw = re.sub(r"\s+", " ", _NARR_RX.sub(" ", q)).strip()
        base = raw if re.search(r"аудиокниг|радиоспектакл|спектакл", raw, re.I) else f"{raw} аудиокнига"
        r1 = _run_platforms(job, [("yt", base), ("yt", q), ("ytpl", base), ("archive", raw),
                                  ("vk", base), ("rutube", base), ("rutube_api", raw), ("kv", raw), ("ak", raw)], 1)
        if job.get("cancel"):
            raise Cancelled()
        phase(job, "Жду ответа Claude и Antigravity")
        # Antigravity — помощник: как только ответил Claude, ждём его не дольше AGY_GRACE с, потом идём дальше без него
        t_claude = None
        while any(t.is_alive() for t in ths):
            time.sleep(0.5)
            if job.get("cancel"):
                raise Cancelled()
            if not ths[0].is_alive():
                t_claude = t_claude or time.time()
                if "claude" in out and ths[1].is_alive() and time.time() - t_claude > AGY_GRACE:
                    job["agy_late"] = True
                    for pr in list(job["procs"]):
                        threading.Thread(target=kill, args=(pr,), daemon=True).start()
                    _src(job, "Antigravity", "skip", note=f"не успел за {AGY_GRACE} с после Claude — без него")
                    break
        # 2. что это за запрос и что за книга
        c_d, a_d = out.get("claude"), out.get("agy")
        interp = c_d or a_d or heur
        kind = interp.get("kind") if interp.get("kind") in ("book", "prompt", "unclear") else "book"
        if c_d and a_d and c_d.get("kind") != a_d.get("kind"):
            kind = c_d.get("kind") or kind
        work = dict(heur["work"])
        for k, v in ((interp.get("work") or {}).items()):
            if v not in (None, "", [], 0):
                work[k] = v
        if not work.get("expected_h") and a_d and (a_d.get("work") or {}).get("expected_h"):
            work["expected_h"] = a_d["work"]["expected_h"]
        if not work.get("narrator_wanted") and heur["work"]["narrator_wanted"]:
            work["narrator_wanted"] = heur["work"]["narrator_wanted"]
        work = {"author": _s(work.get("author"), 200), "title": _s(work.get("title"), 300),
                "original_title": _s(work.get("original_title"), 300),
                "alt_titles": [_s(x, 200) for x in (work.get("alt_titles") or []) if _s(x)][:5],
                "expected_h": float(work.get("expected_h") or 0) if str(work.get("expected_h") or "0").replace(".", "", 1).isdigit() else 0,
                "narrator_wanted": _s(work.get("narrator_wanted"), 120),
                "kind_wanted": work.get("kind_wanted") if work.get("kind_wanted") in ("audiobook", "radioplay", "any") else "any"}
        result = {"kind": kind, "query": q, "work": work, "clarify": _s((c_d or a_d or {}).get("clarify"), 600),
                  "section": _s((c_d or {}).get("section"), 120), "about": _s((c_d or {}).get("about"), 800),
                  "why": _s((c_d or {}).get("why"), 600), "sources": job["sources"], "library": None,
                  "best": None, "choices": [], "rejected": [], "ambiguous": False, "notes": []}
        if not (c_d or a_d):
            result["notes"].append("ИИ недоступен — запрос разобран без него")
        if kind == "prompt":
            status = "done"
            return
        lm = library_match(conn, work["author"], work["title"])
        if lm:
            result["library"] = {"state": lm["state"], "item": lm["item"]}
        # 3. второй круг прямого поиска по запросам от ИИ
        _merge(pool, _llm_cands(c_d, "Claude"), order)
        _merge(pool, _llm_cands(a_d, "Antigravity"), order)
        _merge(pool, cat0, order)
        _merge(pool, r1, order)
        if kind == "book" and work["title"]:          # каталог ещё раз — по разобранному названию (ru/uk/оригинал)
            _merge(pool, _catalog_cands(conn, job, [f"{work['author']} {work['title']}".strip(), work["title"],
                                                    work.get("original_title")] + work.get("alt_titles", [])[:2]), order)
        if kind == "book" and work["title"]:
            lq = [x for x in ((c_d or {}).get("queries") or []) + ((a_d or {}).get("queries") or []) if isinstance(x, str)]
            qs = _round2_queries(work, lq)[:8]
            phase(job, "Второй круг поиска по площадкам: " + str(len(qs)) + " запросов")
            plan = [("yt", x) for x in qs[:7]] + [("ytpl", x) for x in qs[:2]] + [("archive", work["title"])]
            if work.get("original_title"):
                plan.append(("archive", work["original_title"]))
            plan += [("vk", qs[0]), ("rutube", qs[0])] if qs else []
            plan += [("kv", work["title"])] + ([("kv", work["alt_titles"][0])] if work.get("alt_titles") else [])
            _merge(pool, _run_platforms(job, plan, 2), order)
        if job.get("cancel"):
            raise Cancelled()
        # 4. отбор и проверка yt-dlp
        titles = [t for t in [work["title"], work.get("original_title")] + work.get("alt_titles", []) if t]
        cands = [pool[k] for k in order]
        for c in cands:            # предварительный балл: без сети
            txt = f"{c.get('title', '')} {c.get('channel', '')}"
            llm = any(x in ("Claude", "Antigravity") for x in c["found_by"])
            c["pre"] = (3 * (relevance(txt, titles) if titles and c.get("title") else (0.7 if llm else 0))
                        + (2.5 if llm else 0) + (1 if re.search(r"аудиокниг|аудіокниг|радиоспект|читает|читає", txt, re.I) else 0)
                        - (5 if _JUNK.search(c.get("title") or "") else 0) + 0.3 * len(c["found_by"])
                        + (1.5 if c.get("catalog") else 0)
                        - (8 if (c.get("catalog") or {}).get("availability") == "members" else 0))
            if work.get("expected_h") and c.get("duration"):
                r = c["duration"] / (work["expected_h"] * 3600)
                c["pre"] += 1.5 if 0.75 <= r <= 1.6 else -1.5 if r < 0.4 else 0
        cands.sort(key=lambda c: -c["pre"])
        unreach = []
        for c in cands:              # площадка не открывается отсюда (VK/Rutube из WSL) — сразу в отсеянные, без 15-с ожиданий
            h = urllib.parse.urlparse(c["url"]).hostname or ""
            if h and not reachable(h):
                probe(c)
                unreach.append(c)
            elif c.get("catalog") and not c["catalog"].get("downloadable"):   # akniga: только ссылка, без проверки
                _cat().probe_cached(c)
                unreach.append(c)
        cands = [c for c in cands if c not in unreach and c["pre"] > -2
                 and (c.get("catalog") or {}).get("availability") != "members"][:PROBE_MAX]
        phase(job, f"Проверяю скачиваемость: {len(cands)} кандидатов (yt-dlp без загрузки)")
        _src(job, "Проверка yt-dlp", "running", len(cands))
        with ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(lambda c: None if job.get("cancel") else _cat().probe_cached(c), cands))
        if job.get("cancel"):
            raise Cancelled()
        for c in cands + unreach:
            assess(c, work, titles)
        ok = sorted([c for c in cands if not c["drop"]], key=lambda c: -c["score"])
        _src(job, "Проверка yt-dlp", "done", len(ok), f"прошли {len(ok)} из {len(cands)}")
        result["checked"] = len(cands)
        result["catalog"] = job.get("catalog") or []
        result["rejected"] = [_pub(c) for c in cands + unreach if c["drop"]][:14]
        result["choices"] = [_pub(c) for c in ok[:8]]
        if ok:
            best = ok[0]
            amb = kind == "unclear" or any(f.startswith("короче ожидаемого") for f in best["flags"])
            if work.get("narrator_wanted") and not best.get("narrator_match"):
                amb = True
            if len(ok) > 1:
                sec = ok[1]
                nb, ns = _nt(best.get("narrator")), _nt(sec.get("narrator"))
                differ = bool(nb and ns and nb != ns) or sec["kind"] != best["kind"] or sec["lang"] != best["lang"]
                if sec["score"] >= best["score"] - 8 and differ:
                    amb = True
            result["ambiguous"] = bool(amb)
            result["best"] = _pub(best)
        status = "done"
    except Cancelled:
        status, err = "cancelled", "отменено"
    except Exception as e:
        import traceback
        A.log("WARN: abook_find: поиск упал: " + " | ".join(traceback.format_exc().strip().splitlines()[-4:]))
        status, err = "error", f"{type(e).__name__}: {e}"
    finally:
        job["done"] = True
        meta["seconds"] = round(time.time() - job["t0"], 1)
        meta["cost_usd"] = round(sum((m.get("cost_usd") or 0) for m in meta["calls"]), 3) or None
        try:
            with A._WRITE_LOCK, A._tx(conn):
                conn.execute("UPDATE find_searches SET status=?, finished=?, result=?, error=?, meta=? WHERE id=?",
                             (status, _now(), json.dumps(result, ensure_ascii=False) if result else None, err,
                              json.dumps(meta, ensure_ascii=False), sid))
            if status == "done" and job.get("auto") and result and result.get("best") and not result.get("ambiguous") \
                    and not (result.get("library") or {}).get("state") == "downloaded":
                with contextlib.suppress(Exception):
                    enqueue_candidate(conn, sid, result["best"]["key"])
        except Exception as e:
            A.log(f"WARN: abook_find: не сохранился поиск {sid}: {e}")
        finally:
            with _SLOCK:
                _SJOBS.pop(sid, None)
            conn.close()


def _pub(c):
    pr = c.get("probe") or {}
    return {"key": _key(c["url"]), "url": c["url"], "urls": c["urls"], "platform": c["platform"], "type": c["type"],
            "title": _line(c.get("title"), 200), "channel": _line(c.get("channel"), 120),
            "narrator": _line(c.get("narrator"), 120), "kind": c.get("kind") or "", "lang": c.get("lang") or "",
            "duration": pr.get("duration") or c.get("duration"), "parts": pr.get("parts") or 1,
            "verified": bool(pr.get("ok")), "found_by": c["found_by"], "flags": c.get("flags") or [],
            "drop": c.get("drop"), "score": c.get("score"), "ratio": c.get("ratio"), "ai_voice": c.get("ai_voice"),
            "note": _line(c.get("note"), 300), "narrator_match": c.get("narrator_match"),
            "link": c["url"], "catalog_id": (c.get("catalog") or {}).get("id"),
            "availability": (c.get("catalog") or {}).get("availability")}


def _search_row(conn, r):
    d = {"id": r["id"], "query": r["query"], "status": r["status"], "started": r["started"],
         "finished": r["finished"], "error": r["error"], "auto": bool(r["auto"])}
    for k in ("result", "meta"):
        try:
            d[k] = json.loads(r[k]) if r[k] else None
        except Exception:
            d[k] = None
    res = d.get("result") or {}
    lib = res.get("library")
    if lib and lib.get("item"):                   # живое состояние книги (могла докачаться)
        it = A.get_items(conn, ids=[lib["item"]["id"]])
        if it:
            lib["item"] = it[0]
            lib["state"] = "downloaded" if it[0]["has_file"] else lib["state"]
    with _SLOCK:
        job = _SJOBS.get(r["id"])
    if job and not job.get("done"):
        d["job"] = {"phase": job["phase"], "elapsed": round(time.time() - job["t0"], 1),
                    "events": list(job["events"])[-8:], "sources": dict(job["sources"]),
                    "catalog": list(job.get("catalog") or [])}
    return d


def searches_payload(conn, pid, limit=6):
    rows = conn.execute("SELECT * FROM find_searches WHERE profile_id=? ORDER BY id DESC LIMIT ?", (pid, limit)).fetchall()
    return [_search_row(conn, r) for r in rows]


# ------------------------------------------------------------------ очередь загрузок

_Q = {"loaded": False, "items": []}
_QLOCK = threading.RLock()
_QWAKE = threading.Event()
_QTHREAD = None
_QPROC = {}                   # key -> Popen текущего подпроцесса
_QCANCEL = set()
ACTIVE = ("queued", "downloading", "merging", "checking")
KEEP_DONE = 40


def _qload():
    if not _Q["loaded"]:
        d = _load_json(queue_file(), {}) or {}
        _Q["items"] = [e for e in (d.get("items") or []) if isinstance(e, dict) and e.get("key")]
        _Q["loaded"] = True
    return _Q["items"]


def _qsave():
    items = _Q["items"]
    fin = [e for e in items if e["state"] not in ACTIVE]
    if len(fin) > KEEP_DONE:
        drop = {id(e) for e in sorted(fin, key=lambda e: e.get("finished") or "")[:len(fin) - KEEP_DONE]}
        _Q["items"] = items = [e for e in items if id(e) not in drop]
    _atomic_json(queue_file(), {"version": 1, "updated": _now(), "items": items})


def _manifest_lock():
    return queue_file().with_name(".ui-requests.lock")


def manifest_put(item):
    """Добавить/заменить запись в ui-requests.json (формат обычных манифестов)."""
    p = ui_manifest()
    with _flock(_manifest_lock()):
        m = _load_json(p, None) or {}
        items = [x for x in (m.get("items") or []) if isinstance(x, dict) and x.get("id") != item["id"]]
        items.append(item)
        notes = dict(m.get("section_notes") or {})
        notes.setdefault(UI_SECTION, UI_SECTION_NOTE)
        _atomic_json(p, {"section_notes": notes, "items": items,
                         "total_hours": round(sum(float(x.get("duration_h") or 0) for x in items), 2)})


def manifest_drop(iid):
    p = ui_manifest()
    if not p.exists():
        return
    with _flock(_manifest_lock()):
        m = _load_json(p, None)
        if not isinstance(m, dict):
            return
        items = [x for x in (m.get("items") or []) if isinstance(x, dict) and x.get("id") != iid]
        if len(items) != len(m.get("items") or []):
            m["items"] = items
            m["total_hours"] = round(sum(float(x.get("duration_h") or 0) for x in items), 2)
            _atomic_json(p, m)


def _new_id(conn, author, title):
    sur = (author or "").split(",")[0].split()[-1] if author else ""
    base = A._translit_slug(f"{sur} {title}".strip() or "kniga", 48).strip("-") or "kniga"
    taken = {r[0] for r in conn.execute("SELECT id FROM items")}
    taken |= set((A.read_state_ro().get("items") or {}).keys())
    taken |= {e.get("item_id") for e in _qload()}
    iid, n = base, 2
    while iid in taken:
        iid, n = f"{base}-{n}", n + 1
    return iid


def _section_for(conn, res, cand):
    sec = _s(res.get("section"), 120)
    if sec and sec in set(_sections(conn)) | {UI_SECTION}:
        return sec
    if cand.get("kind") == "radioplay":
        return "Аудиоспектакли/По запросу"
    return UI_SECTION


def enqueue_candidate(conn, sid, key):
    r = conn.execute("SELECT * FROM find_searches WHERE id=?", (sid,)).fetchone()
    if not r or not r["result"]:
        raise ValueError("Поиск не найден")
    res = json.loads(r["result"])
    cand = next((c for c in (res.get("choices") or []) if c.get("key") == key), None) or \
        (res.get("best") if (res.get("best") or {}).get("key") == key else None)
    if not cand:
        raise ValueError("Вариант не найден в результатах поиска")
    w = res.get("work") or {}
    with _QLOCK:
        for e in _qload():
            if e["state"] in ACTIVE and e.get("source_key") == key:
                return {"ok": True, "key": e["key"], "already": True, "position": _position(e)}
    iid = _new_id(conn, w.get("author"), w.get("title") or cand.get("title"))
    item = {"id": iid, "section": _section_for(conn, res, cand), "author": w.get("author") or "Неизвестный автор",
            "title": w.get("title") or cand.get("title") or iid,
            "narrator": (cand.get("narrator") or "") + (" (ИИ-озвучка)" if cand.get("ai_voice") and "ИИ" not in (cand.get("narrator") or "") else ""),
            "kind": cand.get("kind") if cand.get("kind") in ("audiobook", "radioplay", "reading") else "audiobook",
            "lang": cand.get("lang") or "ru", "urls": cand.get("urls") or [cand["url"]],
            "duration_h": round(float(cand.get("duration") or 0) / 3600, 2) or (w.get("expected_h") or None),
            "source": f"{cand.get('platform')} · {cand.get('channel')}".strip(" ·"),
            "about": res.get("about") or "", "why": res.get("why") or "",
            "requested": {"query": res.get("query"), "at": _now(), "search_id": sid, "found_by": cand.get("found_by")}}
    return enqueue(item, parts=cand.get("parts") or len(item["urls"]), source_key=key, search_id=sid)


def enqueue_catalog(conn, item_id):
    """Книга из каталога, ещё не скачанная: качаем её собственную запись из её манифеста."""
    it = A.get_items(conn, ids=[item_id], full=True)
    if not it:
        raise ValueError("Книга не найдена")
    it = it[0]
    if it["has_file"]:
        raise ValueError("Книга уже скачана")
    src = conn.execute("SELECT source FROM items WHERE id=?", (item_id,)).fetchone()[0]
    mp = A.MANIFESTS_DIR / f"{src}.json"
    if src.endswith("(top)"):
        mp = A.F_TOP_PATH
    if not mp.exists():
        raise ValueError(f"Не нашёл манифест книги ({src})")
    return enqueue({"id": item_id, "author": it["author"], "title": it["title"], "narrator": it["narrator"],
                    "section": it["section"], "urls": it.get("urls") or [], "duration_h": it["hours"]},
                   parts=max(1, len(it.get("urls") or [])), manifest=str(mp))


def enqueue(item, parts=1, source_key=None, search_id=None, manifest=None):
    with _QLOCK:
        items = _qload()
        for e in items:
            if e["item_id"] == item["id"] and e["state"] in ACTIVE:
                return {"ok": True, "key": e["key"], "already": True, "position": _position(e)}
        items[:] = [e for e in items if not (e["item_id"] == item["id"] and e["state"] not in ACTIVE)]
        e = {"key": item["id"], "item_id": item["id"], "title": item.get("title"), "author": item.get("author"),
             "narrator": item.get("narrator") or "", "section": item.get("section") or "",
             "manifest": manifest or str(ui_manifest()), "own": manifest is None,
             "item": item if manifest is None else None, "parts": parts,
             "duration_h": item.get("duration_h"), "source_key": source_key, "search_id": search_id,
             "state": "queued", "stage": "", "k": 0, "n": parts, "pct": None, "added": _now(), "started": None,
             "finished": None, "message": "", "warn": "", "check": None, "pid": None, "resumed": False}
        items.append(e)
        _qsave()
        pos = _position(e)
    _ensure_worker()
    _QWAKE.set()
    return {"ok": True, "key": e["key"], "position": pos, "started": pos == 1}


def _position(e):
    act = [x for x in _Q["items"] if x["state"] in ACTIVE]
    return act.index(e) + 1 if e in act else None


def queue_remove(key):
    """Убрать стоящую, прервать текущую (SIGTERM группе процессов), снять пометку завершённой."""
    with _QLOCK:
        e = next((x for x in _qload() if x["key"] == key), None)
        if not e:
            return {"ok": False}
        if e["state"] == "queued":
            _Q["items"].remove(e)
            _qsave()
            return {"ok": True, "removed": True}
        if e["state"] in ACTIVE:
            _QCANCEL.add(key)
            p = _QPROC.get(key)
            if p is not None:
                threading.Thread(target=kill, args=(p,), daemon=True).start()
            elif e.get("pid"):
                with contextlib.suppress(Exception):
                    os.killpg(e["pid"], signal.SIGTERM)
            return {"ok": True, "cancelled": True}
        _Q["items"].remove(e)
        _qsave()
        return {"ok": True, "removed": True}


def queue_retry(key):
    with _QLOCK:
        e = next((x for x in _qload() if x["key"] == key), None)
        if not e or e["state"] in ACTIVE:
            return {"ok": False}
        e.update(state="queued", stage="", k=0, pct=None, message="", warn="", finished=None, started=None,
                 check=None, pid=None, resumed=False)
        _Q["items"].remove(e)
        _Q["items"].append(e)
        _qsave()
    _ensure_worker()
    _QWAKE.set()
    return {"ok": True}


def resume_queue():
    """Старт сервера: прерванные загрузки продолжаются. Живой осиротевший `abook get` не убиваем —
    ждём его по pid и state.json; мёртвый — книга снова встаёт в очередь (или сразу к проверке, если уже done)."""
    with _QLOCK:
        items = _qload()
        n = 0
        for e in items:
            if e["state"] in ("downloading", "merging", "checking"):
                e["resumed"] = True
                n += 1
                if e["state"] != "checking" and e.get("pid") and _alive(e["pid"]):
                    e["stage"] = "продолжается после перезапуска сервера"
                    e["orphan"] = True
                elif e["state"] != "checking":
                    st = (A.read_state_ro().get("items") or {}).get(e["item_id"]) or {}
                    e["state"] = "checking" if st.get("status") == "done" else "queued"
                    e["pid"] = None
            elif e["state"] == "queued":
                n += 1
        if items:
            _qsave()
    if n:
        _ensure_worker()
        _QWAKE.set()
    return n


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _ensure_worker():
    global _QTHREAD
    with _QLOCK:
        if _QTHREAD and _QTHREAD.is_alive():
            return
        _QTHREAD = threading.Thread(target=_qworker, daemon=True, name="abook-find-dl")
        _QTHREAD.start()


def _qworker():
    while True:
        with _QLOCK:
            e = next((x for x in _qload() if x["state"] in ("downloading", "merging", "checking")), None) or \
                next((x for x in _Q["items"] if x["state"] == "queued"), None)
        if not e:
            _QWAKE.wait(timeout=30)
            _QWAKE.clear()
            continue
        try:
            _process(e)
        except Exception as ex:
            import traceback
            A.log("WARN: abook_find: загрузка упала: " + " | ".join(traceback.format_exc().strip().splitlines()[-4:]))
            with _QLOCK:
                e.update(state="error", message=f"{type(ex).__name__}: {ex}"[:300], finished=_now(), pid=None)
                _qsave()
        finally:
            _QCANCEL.discard(e["key"])
            _QPROC.pop(e["key"], None)


def _set(e, **kw):
    with _QLOCK:
        e.update(kw)
        _qsave()


def _stage_bytes(iid):
    d = A.STAGING_DIR / iid
    tot = 0
    with contextlib.suppress(Exception):
        for p in d.rglob("*"):
            with contextlib.suppress(OSError):
                if p.is_file():
                    tot += p.stat().st_size
    return tot


def _process(e):
    iid = e["item_id"]
    if e["state"] in ("queued", "downloading", "merging"):
        if not _download(e):
            return
    if e["state"] == "checking":
        _check(e)
    # книга в библиотеке: база, файлы для ИИ (сервер сам; abook get делает то же, если не тестовый режим)
    with contextlib.suppress(Exception):
        conn = A.db_connect()
        try:
            with A._WRITE_LOCK:
                A.sync_db(conn, force=True)
                A.refresh_outputs(conn, "get")
        finally:
            conn.close()
    _set(e, state="done", finished=_now(), pid=None, stage="")
    A.log(f"[{iid}] вкладка «Найти»: готово")


_LOG_RX = re.compile(r"^\[[\d\- :]+\]\s+\[(?P<id>[^\]]+)\]\s+(?P<msg>.*)$")


def _logfile(iid):
    d = queue_file().parent / "find-logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{iid}.log"


def _download(e):
    """-> True, если книга скачана (e.state = checking); иначе состояние выставлено (error/cancelled).
    Вывод `abook get` идёт в файл find-logs/<id>.log, а не в трубу сервера: перезапуск сервера не обрывает загрузку
    (с трубой abook get упал бы на первой же строке лога), новый сервер подхватывает процесс по pid и дочитывает файл."""
    iid, key = e["item_id"], e["key"]
    lf = _logfile(iid)
    if e.get("orphan") and _alive(e.get("pid")):
        return _follow(e, None, lf, int(e.get("log_pos") or 0))
    e.pop("orphan", None)
    if e.get("own") and e.get("item"):
        manifest_put(e["item"])
    cmd = [get_bin(), "get", e["manifest"], "--only", iid, "--bitrate", str(BITRATE), "--retry-failed"]
    if A.STATE_PATH.resolve() != (A.ABOOK_DIR / "state.json").resolve():
        cmd += ["--state", str(A.STATE_PATH)]
    if A.AUDIOBOOKS_ROOT.resolve() != Path("/mnt/d/VideoDownloader/Аудиокниги").resolve():
        cmd += ["--library", str(A.AUDIOBOOKS_ROOT)]
    env = dict(os.environ, ABOOK_MANIFESTS=str(A.MANIFESTS_DIR), PYTHONUNBUFFERED="1")
    _set(e, state="downloading", stage="запускаю abook get", started=_now(), k=0, pct=None, message="", warn="",
         log=str(lf), log_pos=0)
    try:
        with open(lf, "w", encoding="utf-8") as out:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                    start_new_session=True, env=env, cwd=str(A.ABOOK_DIR))
    except OSError as ex:
        _set(e, state="error", message=f"abook get не запустился: {ex}", finished=_now(), stage="")
        _drop_own(e)
        return False
    _QPROC[key] = proc
    _set(e, pid=proc.pid)
    return _follow(e, proc, lf, 0)


def _follow(e, proc, lf, pos):
    """Читает лог abook get, пока процесс жив (свой — poll(), осиротевший — по pid), и обновляет прогресс."""
    iid, key = e["item_id"], e["key"]
    total = float(e.get("duration_h") or 0) * 3600
    last_fail, tail, buf, t_pct = "", [], "", 0.0
    playlist_n = int(e.get("playlist_n") or 0)

    def running():
        return proc.poll() is None if proc is not None else _alive(e.get("pid"))
    while True:
        alive = running()
        if key in _QCANCEL and proc is None and alive:
            with contextlib.suppress(Exception):
                os.killpg(int(e["pid"]), signal.SIGTERM)
        try:
            with open(lf, encoding="utf-8", errors="replace") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
        except OSError:
            chunk = ""
        buf += chunk
        lines = buf.split("\n")
        buf = lines.pop()
        for line in lines:
            line = line.rstrip()
            if line.strip():
                tail = (tail + [line])[-12:]
            m = _LOG_RX.match(line)
            if not m or m.group("id") != iid:
                continue
            msg = m.group("msg")
            mm = re.match(r"playlist url #\d+: (\d+) entries", msg)
            if mm:
                playlist_n += int(mm.group(1))
                with _QLOCK:
                    e["playlist_n"] = playlist_n
                    e["n"] = max(playlist_n + max(0, len((e.get("item") or {}).get("urls") or []) - 1), 1)
            elif msg.startswith("downloading part"):
                with _QLOCK:
                    e.update(k=e.get("k", 0) + 1, stage="скачиваю", state="downloading")
                    e["n"] = max(e.get("n") or 1, e["k"])
            elif msg.startswith("downloaded ") and "merging" in msg:
                with _QLOCK:
                    e.update(state="merging", stage="склеиваю и проверяю файл", pct=None)
            elif msg.startswith("FAILED:"):
                last_fail = msg[len("FAILED:"):].strip()
            elif msg.startswith(("skip (previously failed", "skip (already done")):
                last_fail = last_fail or msg
            elif "WARN" in msg or "retry" in msg.lower() or "bot" in msg.lower():
                with _QLOCK:
                    e["warn"] = msg[:200]
        if e["state"] == "downloading" and total > 0 and time.time() - t_pct > 2:
            t_pct = time.time()             # прогресс внутри части: размер staging против ожидаемого (~128 кбит/с)
            with _QLOCK:
                e["pct"] = round(min(0.99, _stage_bytes(iid) / (total * 16500)), 3)
        with _QLOCK:
            if e.get("log_pos") != pos:
                e["log_pos"] = pos
                _qsave()
        if not alive:
            break
        time.sleep(1.0)
    if proc is not None:
        with contextlib.suppress(Exception):
            proc.wait(timeout=10)
    _QPROC.pop(key, None)
    e.pop("orphan", None)
    st = (A.read_state_ro().get("items") or {}).get(iid) or {}
    if key in _QCANCEL:
        _set(e, state="cancelled", message="отменено", finished=_now(), pid=None, pct=None, stage="")
        _drop_own(e)
        return False
    if st.get("status") == "done":
        n = len(st.get("parts") or []) or e.get("n")
        _set(e, state="checking", stage="проверка полноты", k=n, n=n, pct=None, pid=None,
             message=f"{float(st.get('duration_sec') or 0) / 3600:.1f} ч".replace(".", ","),
             warn="; ".join(st.get("warnings") or [])[:300] or e.get("warn", ""))
        return True
    rc = proc.returncode if proc is not None else "?"
    why = st.get("error") or last_fail or next((x for x in reversed(tail) if x.strip()), "") or f"код {rc}"
    _set(e, state="error", message=_line(why, 400), finished=_now(), pid=None, pct=None, stage="")
    _drop_own(e)
    return False


def _drop_own(e):
    """Отменённое/неудачное уходит из ui-requests.json: в библиотеке не висит «не скачано»."""
    if e.get("own"):
        with contextlib.suppress(Exception):
            manifest_drop(e["item_id"])


def _check(e):
    """abook-check <id> --json; нет Claude, лимит, ошибка — предупреждение и без проверки."""
    iid = e["item_id"]
    if not os.environ.get("ABOOK_CHECK_BIN") and not shutil.which("claude"):
        _set(e, warn=_join(e.get("warn"), "проверка полноты пропущена: нет claude"))
        return
    if not Path(CHECK_BIN).exists():
        _set(e, warn=_join(e.get("warn"), f"проверка полноты пропущена: не найден {CHECK_BIN}"))
        return
    _set(e, stage="проверка полноты: распознавание фрагментов…")
    cmd = [CHECK_BIN, iid, "--json", "--timeout", str(max(60, CHECK_TIMEOUT - 120))]
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, cwd=str(A.ABOOK_DIR), start_new_session=True)
    except OSError as ex:
        _set(e, warn=_join(e.get("warn"), f"проверка полноты не запустилась: {ex}"))
        return
    _QPROC[e["key"]] = proc
    _set(e, pid=proc.pid)
    err_tail = []

    def read_err():
        for ln in proc.stderr:
            ln = ln.strip()
            if ln:
                err_tail[:] = (err_tail + [ln])[-8:]
                if "Claude" in ln:
                    e["stage"] = "проверка полноты: спрашиваю Claude…"
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    timer = threading.Timer(CHECK_TIMEOUT, lambda: kill(proc))
    timer.daemon = True
    timer.start()
    try:
        out = proc.stdout.read()
        proc.wait()
        t.join(timeout=5)
    finally:
        timer.cancel()
        _QPROC.pop(e["key"], None)
    if e["key"] in _QCANCEL:
        _set(e, warn=_join(e.get("warn"), "проверка прервана"), pid=None)
        return
    try:
        rep = json.loads(out)
        r = rep["result"]
        v = r.get("verdict")
        ru = {"complete": "полная", "probably_complete": "вероятно полная", "incomplete": "НЕПОЛНАЯ",
              "wrong_order": "неверный порядок частей", "wrong_work": "не то произведение",
              "cant_tell": "нельзя определить"}.get(v, v)
        chk = {"verdict": v, "verdict_ru": ru, "summary": _line(r.get("summary_ru"), 500),
               "problem": v in ("incomplete", "wrong_order", "wrong_work")}
        _set(e, check=chk, pid=None)
    except Exception:
        why = next((ln for ln in reversed(err_tail) if ln), "") or f"код {proc.returncode}"
        _set(e, warn=_join(e.get("warn"), "проверка полноты недоступна: " + _line(why, 200)), pid=None)


def _join(a, b):
    return "; ".join(x for x in (a, b) if x)


def queue_payload(conn=None):
    with _QLOCK:
        items = [dict(e) for e in _qload()]
    act = [e for e in items if e["state"] in ACTIVE]
    out = []
    for e in act + sorted([e for e in items if e["state"] not in ACTIVE], key=lambda e: e.get("finished") or "", reverse=True):
        e.pop("item", None)
        e["position"] = act.index(next(x for x in act if x["key"] == e["key"])) + 1 if e["state"] in ACTIVE else None
        e["has_file"] = False
        out.append(e)
    if conn is not None and out:
        have = {i["id"]: i for i in A.get_items(conn, ids=[e["item_id"] for e in out])}
        for e in out:
            it = have.get(e["item_id"])
            e["has_file"] = bool(it and it["has_file"])
            e["in_library"] = bool(it)
    return out


# ------------------------------------------------------------------ HTTP

def state_payload(conn, pid):
    from abook_links import map_status   # noqa: PLC0415
    return {"searches": searches_payload(conn, pid), "queue": queue_payload(conn), "claude": claude_ok(),
            "agy": agy_ok(), "map": map_status(conn), "test_mode": bool(A.TEST_MODE)}


# ------------------------------------------------------------------ переписывание запроса (другие названия)
# «Фундация Азимов» → «Основание», «Академия», «Foundation»: если по буквам ничего сильного не нашлось, быстрая
# модель один раз даёт варианты названия (переводы ru/uk, оригинал, другие издания); кэш навсегда (query_alias),
# повтор запроса — без ИИ. Пока варианты считаются — ответ сразу, с флагом expanding.

QV_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["variants"],
             "properties": {"variants": {"type": "array", "maxItems": 6, "items": {"type": "string"}}}}
_QV_BUSY = set()


def _strong(res, q):
    """Сильное совпадение — все слова запроса (≥ 3 букв) есть в авторе/названии ЦЕЛИКОМ: «Хоббит» ≠ «Хобби»."""
    qw = {w for w in _nt(q).split() if len(w) >= 3}
    if not qw:
        return True
    for w in res[:3]:
        have = set(_nt(f"{w.get('author') or ''} {w.get('title') or ''} {' '.join(w.get('alt_titles') or [])}").split())
        if qw <= have:
            return True
    return False


def query_variants(conn, q):
    """-> список вариантов | [] (их нет) | None (считаются сейчас)."""
    key = re.sub(r"\s+", " ", _nt(q)).strip()
    if len(key) < 3:
        return []
    conn.execute("CREATE TABLE IF NOT EXISTS query_alias(q TEXT PRIMARY KEY, variants TEXT, created TEXT)")
    r = conn.execute("SELECT variants FROM query_alias WHERE q=?", (key,)).fetchone()
    if r:
        return json.loads(r[0] or "[]")
    if key not in _QV_BUSY and (claude_ok() or True):
        _QV_BUSY.add(key)
        threading.Thread(target=_qv_worker, args=(key, q), daemon=True, name="abook-qv").start()
    return None


def _qv_worker(key, q):
    conn = A.db_connect()
    try:
        prompt = ("Запрос к каталогу аудиокниг: «" + q + "». Дай до 6 вариантов, как ЭТА книга (или автор) может называться "
                  "в каталоге: русский и украинский переводы названия, оригинал, другие издания и серии, полное имя автора "
                  "по-русски. Формат каждого варианта: «Автор Название» коротко. Если запрос — не книга и не автор, пустой список. "
                  "Только JSON по схеме.")
        data, meta, err = run_claude(prompt, QV_SCHEMA, new_job(), "haiku", timeout=60, budget=0.05)
        v = [str(x).strip()[:120] for x in (data or {}).get("variants") or [] if str(x).strip()][:6] if data else []
        with A._WRITE_LOCK, A._tx(conn):
            conn.execute("INSERT OR REPLACE INTO query_alias(q, variants, created) VALUES(?,?,?)",
                         (key, json.dumps(v, ensure_ascii=False), _now()))
    except Exception as e:
        A.log(f"WARN: abook_find: варианты запроса: {e}")
    finally:
        _QV_BUSY.discard(key)
        conn.close()


def handle_get(h, conn, p, arg):
    import abook_links as L   # noqa: PLC0415
    pid = A._pid()
    if p == "/api/find/state":
        return h._json(state_payload(conn, pid))
    if p == "/api/find/catalog" and arg("group") == "work":      # одна строка = произведение со списком записей
        q, lim = arg("q") or "", min(50, int(arg("limit") or 20))
        res, ms = _cat().search_works(conn, q, limit=lim, include_members=arg("members") == "1")
        out = {"q": q, "ms": ms, "group": "work", "items": res}
        if not _strong(res, q):                                    # слабое совпадение — переписать запрос
            alt = query_variants(conn, q)
            if alt is None:
                out["expanding"] = True                            # варианты считаются в фоне — UI перезапросит
            elif alt:
                seen = {w["work_id"] for w in res}
                extra = []
                for v in alt:
                    r2, _ = _cat().search_works(conn, v, limit=3, include_members=arg("members") == "1")
                    extra += [w for w in r2[:2] if w["work_id"] not in seen and not seen.add(w["work_id"])]
                out["items"] = (extra + res)[:lim] if extra else res
                out["variants"] = alt
        return h._json(out)
    if p == "/api/find/catalog":
        res, ms = _cat().search(conn, arg("q") or "", limit=min(50, int(arg("limit") or 20)),
                                include_members=arg("members") == "1")
        return h._json({"q": arg("q") or "", "ms": ms, "items": res})
    if p == "/api/find/catalog/status":
        return h._json(_cat().crawl_status(conn))
    if p == "/api/find/catalog/availability":
        return h._json({"url": arg("url"), "availability": _cat().availability(arg("url") or "", conn,
                                                                               check=arg("check") != "0")})
    if p == "/api/find/search":
        r = conn.execute("SELECT * FROM find_searches WHERE id=? AND profile_id=?", (int(arg("id") or 0), pid)).fetchone()
        return h._json(_search_row(conn, r)) if r else h._json({"error": "поиск не найден"}, 404)
    if p.startswith("/api/find/") or p in ("/api/llm", "/api/setup", "/api/sync"):
        return L.handle_get(h, conn, p, arg)
    return h._json({"error": "not found"}, 404)


def handle_post(h, conn, p, payload):
    import abook_links as L   # noqa: PLC0415
    pid = A._pid()
    if p == "/api/find/search":
        sid = start_search(conn, pid, payload.get("q"), auto=bool(payload.get("auto")))
        return h._json({"ok": True, "id": sid})
    if p == "/api/find/search/cancel":
        return h._json({"ok": cancel_search(int(payload.get("id") or 0))})
    if p == "/api/find/catalog":
        op = payload.get("op")
        if op == "crawl":
            return h._json(_cat().start_crawl(payload.get("source") or None, force=bool(payload.get("force"))))
        if op == "cancel":
            return h._json(_cat().cancel_crawl())
        if op == "site":           # поиск на knigavuhe/akniga на лету (с кэшем 14 дней) -> в каталог
            n = _cat().search_site(conn, str(payload.get("site") or "knigavuhe"), str(payload.get("q") or ""),
                                   force=bool(payload.get("force")))
            return h._json({"ok": True, "added": n, "cached": n is None})
        return h._json({"error": "op: crawl | cancel | site"}, 400)
    if p == "/api/find/download":
        if payload.get("catalog_key"):
            return h._json(_cat().enqueue_row(conn, str(payload["catalog_key"])))
        if payload.get("item_id"):
            return h._json(enqueue_catalog(conn, str(payload["item_id"])))
        return h._json(enqueue_candidate(conn, int(payload.get("search_id") or 0), str(payload.get("key") or "")))
    if p == "/api/find/queue":
        op, key = payload.get("op"), str(payload.get("key") or "")
        if op == "retry":
            return h._json(queue_retry(key))
        return h._json(queue_remove(key))
    return L.handle_post(h, conn, p, payload)


def inject_html(html):
    from abook_find_ui import CSS, NAV, VIEWS, JS   # noqa: PLC0415
    for mark, s in (("/*FIND:CSS*/", CSS), ("<!--FIND:NAV-->", NAV), ("<!--FIND:VIEWS-->", VIEWS), ("/*FIND:JS*/", JS)):
        if html.count(mark) != 1:
            raise RuntimeError(f"abook_find: маркер {mark} не найден в REVIEW_HTML")
        html = html.replace(mark, s)
    return html


def strip_markers(html):
    for m in ("/*FIND:CSS*/", "<!--FIND:NAV-->", "<!--FIND:VIEWS-->", "/*FIND:JS*/"):
        html = html.replace(m, "")
    return html
