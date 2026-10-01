"""abook_tg.py — тонкий мост между сервером `abook review` и CLI `abook-tg`.

Сам сервер работает на системном python (без telethon), поэтому реальная отправка в Telegram
всегда идёт отдельным процессом `abook-tg send <id> --json-progress` (venv ~/abook/.venv-tg).
Этот модуль:
  • читает статус (telegram.json, tg-sent.json — оба read-only отсюда);
  • ведёт TG-очередь отправки ~/abook/tg-queue.json (персистентная, атомарная запись; переживает
    перезапуск сервера — незавершённое снова встаёт в очередь, уже отмеченное в tg-sent.json не шлётся);
  • перед отправкой каждой книги гоняет проверку полноты `abook-check <id> --json` (или берёт свежий
    отчёт ~/abook/check-reports/<id>.json, если файл книги с тех пор не менялся). Проверка нашла проблему —
    книга не отправляется («проверка: проблема», можно «всё равно отправить»); проверка недоступна
    (нет claude, лимит, таймаут, упал whisper…) — предупреждение и отправка без неё;
  • разбирает NDJSON-прогресс abook-tg для UI: «проверка…» → «сжатие k/n %» → «отправка k/n %».

Для проверок без реальной отправки (переменные окружения сервера):
    ABOOK_TG_BIN=<фейковый скрипт>     вместо abook-tg (эмуляция NDJSON)
    ABOOK_TG_DRY_RUN=1                 пробрасывать `--dry-run` (abook-tg только печатает план)
    ABOOK_CHECK_BIN=<скрипт>           вместо abook-check
    ABOOK_CHECK_REPORTS=<каталог>      где искать сохранённые отчёты проверки
    ABOOK_TG_QUEUE / ABOOK_TG_SENT     другие пути tg-queue.json / tg-sent.json
    ABOOK_CHECK_TIMEOUT=<сек>          таймаут проверки (900)

Импортируется из abook так же, как abook_ai.py:
    try:
        import abook_tg as TG
    except ImportError as _e:
        TG = None
"""
import atexit
import json
import os
import shutil
import signal
import sqlite3
import stat
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home() / "abook"
STATE = HOME / "state.json"
DB = HOME / "library.db"
SECRETS_FILE = HOME / "telegram.json"
SENT_FILE = Path(os.environ.get("ABOOK_TG_SENT") or HOME / "tg-sent.json")
QUEUE_FILE = Path(os.environ.get("ABOOK_TG_QUEUE") or HOME / "tg-queue.json")
CHECK_REPORTS = Path(os.environ.get("ABOOK_CHECK_REPORTS") or HOME / "check-reports")
ABOOK_TG_BIN = os.environ.get("ABOOK_TG_BIN") or shutil.which("abook-tg") or str(Path.home() / ".local/bin/abook-tg")
ABOOK_CHECK_BIN = (os.environ.get("ABOOK_CHECK_BIN") or shutil.which("abook-check")
                   or str(Path.home() / ".local/bin/abook-check"))
DRY_RUN = os.environ.get("ABOOK_TG_DRY_RUN") == "1"
CHECK_TIMEOUT = int(os.environ.get("ABOOK_CHECK_TIMEOUT") or 900)   # 15 мин на всю проверку
QUALITY_CHOICES = ["high", "speech", "small", "original"]   # держим в шаге с QUALITY_PROFILES в abook-tg
DEFAULT_QUALITY = "high"

CHECK_PROBLEM = {"incomplete": "неполная", "wrong_order": "неверный порядок частей", "wrong_work": "не то произведение"}
CHECK_VERDICTS = {"complete": "полная", "probably_complete": "вероятно полная", "cant_tell": "нельзя определить",
                  **CHECK_PROBLEM}
ACTIVE = ("queued", "checking", "sending")
HISTORY_KEEP = 30          # сколько завершённых записей держать в tg-queue.json (для пометок и списка)

_LOCK = threading.RLock()
_JOB = {                   # живое состояние текущей книги (не персистится; старые поля — для совместимости)
    "running": False,
    "kind": None,          # "send"
    "item_id": None,
    "title": None,
    "author": None,
    "stage": None,         # "check" | "send"
    "check_phase": None,   # «нарезка/распознавание…», «спрашиваю Claude…», «отчёт из кэша»
    "volume": None,        # {"index","of","pct","mbps","stage": encode|copy|upload|done|skip}
    "started": None,
    "finished": None,
    "error": None,
    "log": [],             # последние события (NDJSON abook-tg + предупреждения моста)
}
_Q = {"loaded": False, "items": []}   # записи TG-очереди (см. _new_entry)
_PROC = None               # текущий подпроцесс (abook-check или abook-tg), группа процессов
_CANCEL = set()            # item_id, которые надо прервать
_WORKER = None


# --------------------------------------------------------------------------- файлы/статус

def _load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _atomic_write(p, data):
    p = Path(p)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _secrets():
    return _load_json(SECRETS_FILE, {}) or {}


def configured():
    s = _secrets()
    return bool(s.get("api_id") and s.get("api_hash") and s.get("target"))


def target():
    return _secrets().get("target")


def quality():
    q = _secrets().get("quality")
    return q if q in QUALITY_CHOICES else DEFAULT_QUALITY


def set_quality(q):
    """Сохранить профиль сжатия по умолчанию в telegram.json (несекретный ключ "quality").
    Секреты (api_id/api_hash/target) читает-модифицирует-пишет обратно, не трогая остальное."""
    if q not in QUALITY_CHOICES:
        return {"error": f"неизвестный профиль «{q}» (доступны: {', '.join(QUALITY_CHOICES)})"}
    s = _secrets()
    s["quality"] = q
    tmp = SECRETS_FILE.with_suffix(SECRETS_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(SECRETS_FILE)
    os.chmod(SECRETS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    return {"ok": True, "quality": q}


def _sent():
    return _load_json(SENT_FILE, {"target": None, "items": {}}) or {"target": None, "items": {}}


def _sent_rec(item_id):
    return (_sent().get("items") or {}).get(item_id)


def sent_summary():
    """Сводка для /api/tg/status: сколько книг/томов/данных отправлено."""
    d = _sent()
    items = d.get("items", {})
    books_done = sum(1 for r in items.values() if r.get("complete"))
    vols = sum(len(r.get("volumes", [])) for r in items.values())
    total_bytes = sum(v.get("bytes", 0) for r in items.values() for v in r.get("volumes", []))
    return {"target": d.get("target") or target(), "books_done": books_done,
            "started_books": len(items), "volumes": vols, "bytes": total_bytes}


def sent_items():
    """item_id -> {complete, volumes, of, updated, superseded} для каждой книги, по которой была хоть одна отправка.
    Используется кнопкой «В Telegram» в UI, чтобы показать ✓/частично без похода за каждой книгой отдельно."""
    d = _sent()
    sup = d.get("superseded") or {}
    out = {}
    for iid, r in (d.get("items") or {}).items():
        vols = r.get("volumes") or []
        of = max((v.get("of") or 0) for v in vols) if vols else None
        old = sum(len(x.get("volumes") or []) for x in sup.get(iid, []) if not x.get("deleted"))
        out[iid] = {"complete": bool(r.get("complete")), "volumes": len(vols), "of": of, "updated": r.get("updated"),
                    "superseded": old, "title": r.get("title"), "author": r.get("author")}
    return out


def item_tg_state(item_id, has_file):
    """Состояние одной книги для кнопки «В Telegram»: not_downloaded / not_configured / sent / partial / none."""
    if not has_file:
        return {"state": "not_downloaded"}
    if not configured():
        return {"state": "not_configured"}
    rec = _sent_rec(item_id)
    if not rec:
        return {"state": "none"}
    of = max((v.get("of") or 0) for v in rec["volumes"]) if rec.get("volumes") else None
    st = "sent" if rec.get("complete") else "partial"
    return {"state": st, "volumes": len(rec.get("volumes") or []), "of": of, "updated": rec.get("updated")}


def _state_items():
    return (_load_json(STATE, {}) or {}).get("items", {}) or {}


# --------------------------------------------------------------------------- TG-очередь (персистентная)

def _now():
    return time.time()


def _new_entry(item_id, it, force, skip_check):
    return {"item_id": item_id, "title": (it or {}).get("title"), "author": (it or {}).get("author"),
            "force": bool(force), "skip_check": bool(skip_check), "state": "queued",
            "added": _now(), "started": None, "finished": None,
            "message": None, "warn": None, "check": None, "resumed": False}


def _save():
    with _LOCK:
        done = [e for e in _Q["items"] if e["state"] not in ACTIVE]
        if len(done) > HISTORY_KEEP:
            drop = {id(e) for e in sorted(done, key=lambda e: e.get("finished") or 0)[:len(done) - HISTORY_KEEP]}
            _Q["items"] = [e for e in _Q["items"] if id(e) not in drop]
        try:
            _atomic_write(QUEUE_FILE, {"version": 1, "items": _Q["items"]})
        except OSError as e:
            _log({"event": "warn", "message": f"не удалось сохранить {QUEUE_FILE.name}: {e}"})


def _ensure_loaded():
    """Загрузить tg-queue.json один раз. Прерванные перезапуском (checking/sending) — снова в очередь;
    то, что уже полностью в tg-sent.json (и не переотправка), — сразу «готово»."""
    with _LOCK:
        if _Q["loaded"]:
            return
        _Q["loaded"] = True
        d = _load_json(QUEUE_FILE, {}) or {}
        items = [e for e in (d.get("items") or []) if isinstance(e, dict) and e.get("item_id")]
        changed = False
        for e in items:
            if e.get("state") in ("checking", "sending"):
                _kill_orphan(e)
                e.update(state="queued", resumed=True, started=None)
                changed = True
            if e.get("state") == "queued" and not e.get("force"):
                rec = _sent_rec(e["item_id"])
                if rec and rec.get("complete"):
                    e.update(state="done", finished=_now(), message="уже в Telegram (по журналу)")
                    changed = True
        _Q["items"] = items
        if changed:
            _save()


def _kill_orphan(e):
    """Сервер убили посреди проверки/отправки: подпроцесс (своя группа) мог пережить его. Прибиваем, чтобы
    не было двух отправок одной книги (продолжение пойдёт с неотправленного тома по tg-sent.json)."""
    pid = e.pop("pid", None)
    if not pid:
        return
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return
    if e["item_id"] in cmd:
        try:
            os.killpg(pid, signal.SIGTERM)
        except OSError:
            pass


@atexit.register
def _kill_on_exit():
    proc = _PROC
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass


def _active_entry(item_id):
    for e in _Q["items"]:
        if e["item_id"] == item_id and e["state"] in ACTIVE:
            return e
    return None


def _queued_positions():
    pos, k = {}, 0
    for e in _Q["items"]:
        if e["state"] == "queued":
            k += 1
            pos[e["item_id"]] = k
    return pos


def _log(ev):
    _JOB["log"] = (_JOB["log"] + [ev])[-30:]


def _kick():
    """Запустить воркер, если есть что отправлять и он ещё не идёт."""
    global _WORKER
    with _LOCK:
        if _WORKER and _WORKER.is_alive():
            return
        if not any(e["state"] == "queued" for e in _Q["items"]) or not configured():
            return
        _WORKER = threading.Thread(target=_worker, daemon=True, name="abook-tg-queue")
        _JOB.update(running=True, kind="send", started=_now(), finished=None, error=None)
        _WORKER.start()


def resume():
    """Вызывается сервером при старте: подхватить очередь, оставшуюся от прошлого запуска."""
    _ensure_loaded()
    _kick()
    with _LOCK:
        return sum(1 for e in _Q["items"] if e["state"] == "queued")


def enqueue(item_id, force=False, skip_check=False):
    """Поставить книгу в TG-очередь (если ничего не идёт — стартует сразу)."""
    _ensure_loaded()
    if not item_id:
        return {"error": "не указан item_id"}
    if not configured():
        return {"error": "Telegram не настроен. В терминале: abook-tg setup"}
    it = _state_items().get(item_id)
    if not it or it.get("status") != "done" or not it.get("final_path"):
        return {"error": "Файл ещё не скачан"}
    rec = _sent_rec(item_id)
    with _LOCK:
        e = _active_entry(item_id)
        if e:
            if e["state"] == "queued":          # «всё равно отправить» / «переслать» по уже стоящей в очереди
                e["force"] = e["force"] or bool(force)
                e["skip_check"] = e["skip_check"] or bool(skip_check)
                _save()
            return {"ok": True, "queued": True, "already": True, "position": _queued_positions().get(item_id),
                    "state": e["state"]}
        if rec and rec.get("complete") and not force:
            return {"error": "Книга уже в Telegram целиком — «переслать заново» (force)"}
        _Q["items"] = [x for x in _Q["items"] if x["item_id"] != item_id]   # старая пометка (проблема/ошибка)
        _Q["items"].append(_new_entry(item_id, it, force, skip_check))
        _save()
        running = bool(_WORKER and _WORKER.is_alive())
    _kick()
    with _LOCK:
        pos = _queued_positions().get(item_id)
    return {"ok": True, "queued": running, "started": not running, "position": pos}


def remove(item_id):
    """Убрать из TG-очереди: стоящую — просто убрать, текущую — прервать (проверку или отправку) и убрать,
    завершённую (проблема/ошибка/готово) — снять пометку."""
    _ensure_loaded()
    with _LOCK:
        e = next((x for x in _Q["items"] if x["item_id"] == item_id), None)
        if not e:
            return {"ok": True, "removed": False}
        if e["state"] in ("checking", "sending"):
            e["_remove"] = True
            _CANCEL.add(item_id)
            proc = _PROC
        else:
            _Q["items"] = [x for x in _Q["items"] if x is not e]
            proc = None
        _save()
    if proc:
        _kill(proc)
    return {"ok": True, "removed": True, "cancelled": bool(proc)}


def cancel():
    """«Остановить всё»: прервать текущую книгу и очистить очередь (завершённые пометки остаются)."""
    _ensure_loaded()
    with _LOCK:
        cur = next((x for x in _Q["items"] if x["state"] in ("checking", "sending")), None)
        _Q["items"] = [x for x in _Q["items"] if x["state"] != "queued"]
        if cur:
            _CANCEL.add(cur["item_id"])
        proc = _PROC
        _save()
    if proc:
        _kill(proc)
    return {"ok": True, "cancelled": bool(cur)}


def _kill(proc):
    """Прервать подпроцесс вместе с детьми (ffmpeg, whisper-venv, claude): у него своя группа процессов."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return

    def later():
        time.sleep(5)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    threading.Thread(target=later, daemon=True).start()


# --------------------------------------------------------------------------- совместимость со старым API

def start_send(item_id, force=False, skip_check=False):
    return enqueue(item_id, force=force, skip_check=skip_check)


def start_queue(n=3, profile="Основной", force=False):
    """Поставить в TG-очередь N скачанных и ещё не отправленных книг из очереди прослушивания профиля."""
    if not configured():
        return {"error": "Telegram не настроен. В терминале: abook-tg setup"}
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        row = con.execute("select id from profiles where name=? or slug=?", (profile, profile)).fetchone()
        ids = [r[0] for r in con.execute("select item_id from queue where profile_id=? order by position asc",
                                         (row[0],))] if row else []
        con.close()
    except sqlite3.Error as e:
        return {"error": f"library.db: {e}"}
    items, added = _state_items(), []
    for iid in ids:
        it = items.get(iid) or {}
        rec = _sent_rec(iid)
        if it.get("status") != "done" or (rec and rec.get("complete") and not force):
            continue
        r = enqueue(iid, force=force)
        if r.get("ok"):
            added.append(iid)
        if len(added) >= n:
            break
    return {"ok": True, "added": added}


# --------------------------------------------------------------------------- проверка полноты

def _fresh_report(item_id, it):
    """Сохранённый отчёт abook-check, если он про тот же файл (путь, sha256, размер/mtime) — иначе None."""
    rep = _load_json(CHECK_REPORTS / f"{item_id}.json")
    if not isinstance(rep, dict) or rep.get("id") != item_id or not isinstance(rep.get("result"), dict):
        return None
    p = Path(it.get("final_path") or "")
    try:
        fst = p.stat()
    except OSError:
        return None
    if rep.get("file") and rep["file"] != str(p):
        return None
    if rep.get("sha256") and it.get("sha256") and rep["sha256"] != it["sha256"]:
        return None
    if "file_size" in rep:
        if rep.get("file_size") != fst.st_size or rep.get("file_mtime") != int(fst.st_mtime):
            return None
    else:   # старые отчёты без размера/mtime: файл не должен быть новее отчёта
        try:
            if datetime.fromisoformat(rep["checked_at"]).timestamp() < fst.st_mtime:
                return None
        except (KeyError, TypeError, ValueError):
            return None
    return rep


def _check_summary(rep, source):
    r = rep.get("result") or {}
    v = r.get("verdict")
    return {"verdict": v, "verdict_ru": CHECK_VERDICTS.get(v, v), "confidence": r.get("confidence"),
            "summary": (r.get("summary_ru") or "")[:600], "source": source, "checked_at": rep.get("checked_at"),
            "problem": v in CHECK_PROBLEM}


def _run_check(e, it):
    """-> ("ok"|"problem", check) | ("unavailable", причина) | ("cancelled", None)."""
    iid = e["item_id"]
    rep = _fresh_report(iid, it)
    if rep:
        with _LOCK:
            _JOB["check_phase"] = "отчёт из кэша"
        c = _check_summary(rep, "cache")
        return ("problem" if c["problem"] else "ok"), c
    if not os.environ.get("ABOOK_CHECK_BIN") and not shutil.which("claude"):
        return "unavailable", "нет claude в PATH"
    if not Path(ABOOK_CHECK_BIN).exists():
        return "unavailable", f"не найден {ABOOK_CHECK_BIN}"
    cmd = [ABOOK_CHECK_BIN, iid, "--json", "--timeout", str(max(60, CHECK_TIMEOUT - 120))]
    global _PROC
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                cwd=str(HOME), start_new_session=True)
    except OSError as ex:
        return "unavailable", f"не запустилась: {ex}"
    with _LOCK:
        _PROC = proc
        e["pid"] = proc.pid
        _save()
        _JOB["check_phase"] = "нарезка и распознавание…"
    timed_out = []
    err_tail = []

    def watchdog():
        timed_out.append(1)
        _kill(proc)
    timer = threading.Timer(CHECK_TIMEOUT, watchdog)
    timer.daemon = True
    timer.start()

    def read_err():
        for line in proc.stderr:
            line = line.strip()
            if not line:
                continue
            err_tail[:] = (err_tail + [line])[-8:]
            with _LOCK:
                if "Claude" in line:
                    _JOB["check_phase"] = "спрашиваю Claude…"
                elif "распозна" in line:
                    _JOB["check_phase"] = "распознавание речи…"
    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    try:
        out = proc.stdout.read()
        proc.wait()
        t.join(timeout=5)
    finally:
        timer.cancel()
        with _LOCK:
            _PROC = None
    if iid in _CANCEL:
        return "cancelled", None
    if timed_out:
        return "unavailable", (f"таймаут {CHECK_TIMEOUT // 60} мин" if CHECK_TIMEOUT >= 120 else f"таймаут {CHECK_TIMEOUT} с")
    if proc.returncode != 0:
        why = next((ln for ln in reversed(err_tail) if not ln.startswith(("Промпт:", "  "))), "") or f"код {proc.returncode}"
        return "unavailable", f"abook-check: {why.removeprefix(iid + ': ')[:300]}"
    try:
        rep = json.loads(out)
        assert isinstance(rep.get("result"), dict)
    except (ValueError, AssertionError, AttributeError):
        return "unavailable", "abook-check вернул не JSON-отчёт"
    c = _check_summary(rep, "fresh")
    return ("problem" if c["problem"] else "ok"), c


# --------------------------------------------------------------------------- отправка (abook-tg)

def _apply_event(ev, e):
    t = ev.get("event")
    if t == "plan":
        if ev.get("volumes"):
            _JOB["volume"] = {"index": 0, "of": ev["volumes"], "pct": 0, "mbps": 0, "stage": "prep"}
    elif t in ("volume_start", "volume_skip"):
        _JOB["volume"] = {"index": ev.get("index"), "of": ev.get("of"), "pct": 0, "mbps": 0,
                          "stage": ev.get("stage") or ("skip" if t == "volume_skip" else "copy")}
        if e.get("force"):
            # abook-tg уже убрал старую запись из журнала — после перезапуска не надо снова --force
            e["force"] = False
            e["forced"] = True
            _save()
    elif t == "encode_progress":
        v = _JOB.get("volume") or {}
        v.update(index=ev.get("index"), of=ev.get("of"), pct=ev.get("pct", 0), stage="encode")
        _JOB["volume"] = v
    elif t == "progress":
        v = _JOB.get("volume") or {}
        v.update(index=ev.get("index"), of=ev.get("of"), pct=ev.get("pct", 0), mbps=ev.get("mbps", 0), stage="upload")
        _JOB["volume"] = v
    elif t == "volume_done":
        v = _JOB.get("volume") or {}
        v.update(index=ev.get("index"), of=ev.get("of"), pct=100, stage="done")
        _JOB["volume"] = v
    elif t == "error":
        _JOB["error"] = ev.get("message")
    _log(ev)


def _run_send(e):
    """-> (state, message)."""
    global _PROC
    iid = e["item_id"]
    cmd = [ABOOK_TG_BIN, "send", iid, "--json-progress"] + (["--force"] if e.get("force") else []) \
        + (["--dry-run"] if DRY_RUN else [])
    seen = set()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                cwd=str(HOME), start_new_session=True)
    except OSError as ex:
        return "error", f"abook-tg не запустился: {ex}"
    with _LOCK:
        _PROC = proc
        e["pid"] = proc.pid
        _save()
    tail = []
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                tail = (tail + [line])[-3:]
                continue
            with _LOCK:
                seen.add(ev.get("event"))
                _apply_event(ev, e)
        proc.wait()
    finally:
        with _LOCK:
            _PROC = None
    if iid in _CANCEL:
        return "cancelled", "отменено"
    if "error" in seen or proc.returncode != 0:
        return "error", _JOB.get("error") or (tail[-1] if tail else f"abook-tg завершился с кодом {proc.returncode}")
    if DRY_RUN:
        return "dry_run", "dry-run: только план, в канал ничего не ушло"
    if "already_sent" in seen:
        return "done", "уже в Telegram"
    rec = _sent_rec(iid)
    if "book_done" in seen or (rec and rec.get("complete")):
        return "done", None
    return "error", "abook-tg закончил, но книга не отмечена отправленной"


def _worker():
    global _WORKER
    while True:
        with _LOCK:
            e = next((x for x in _Q["items"] if x["state"] == "queued"), None)
            if not e:
                _WORKER = None   # под тем же замком, что и enqueue → _kick не пропустит новую книгу
                _JOB.update(running=False, finished=_now(), item_id=None, title=None, author=None,
                            stage=None, check_phase=None, volume=None)
                return
            _CANCEL.discard(e["item_id"])
            e.update(state="checking", started=_now(), message=None, warn=None, check=None)
            _JOB.update(running=True, item_id=e["item_id"], title=e.get("title"), author=e.get("author"),
                        stage="check", check_phase=None, volume=None, error=None)
            _save()
        try:
            state, msg = _process(e)
        except Exception as ex:   # воркер не должен умирать молча — книга в «ошибку», очередь идёт дальше
            state, msg = "error", f"{type(ex).__name__}: {ex}"
        with _LOCK:
            e.update(state=state, finished=_now())
            e.pop("pid", None)
            if msg:
                e["message"] = msg
            if e.pop("_remove", False):
                _Q["items"] = [x for x in _Q["items"] if x is not e]
            _CANCEL.discard(e["item_id"])
            _log({"event": "book_state", "item_id": e["item_id"], "state": state, "message": msg})
            _save()


def _process(e):
    iid = e["item_id"]
    rec = _sent_rec(iid)
    if rec and rec.get("complete") and not e.get("force"):
        return "done", "уже в Telegram (по журналу)"
    it = _state_items().get(iid) or {}
    if it.get("status") != "done" or not Path(it.get("final_path") or "").is_file():
        return "error", "файл книги не найден"
    if e.get("skip_check"):
        e["check"] = {"skipped": True}
    else:
        res, c = _run_check(e, it)
        if res == "cancelled" or iid in _CANCEL:
            return "cancelled", "отменено на проверке"
        if res == "unavailable":
            e["check"] = {"unavailable": c}
            e["warn"] = f"проверка недоступна: {c}, отправляю без неё"
            with _LOCK:
                _log({"event": "warn", "item_id": iid, "message": e["warn"]})
        else:
            e["check"] = c
            if res == "problem":
                return "problem", f"проверка: {c['verdict_ru']}" + (f" — {c['summary']}" if c.get("summary") else "")
    with _LOCK:
        if iid in _CANCEL:
            return "cancelled", "отменено"
        e["state"] = "sending"
        _JOB.update(stage="send", volume=None, check_phase=None)
        _save()
    return _run_send(e)


# --------------------------------------------------------------------------- статус для UI

def queue_list():
    with _LOCK:
        pos = _queued_positions()
        out = []
        for e in _Q["items"]:
            d = {k: v for k, v in e.items() if not k.startswith("_")}
            d["position"] = pos.get(e["item_id"]) if e["state"] == "queued" else None
            if e["state"] in ("checking", "sending") and _JOB.get("item_id") == e["item_id"]:
                d["check_phase"] = _JOB.get("check_phase")
                d["volume"] = _JOB.get("volume")
            out.append(d)
        return out


def job_status():
    _ensure_loaded()
    with _LOCK:
        job = {k: (list(v) if isinstance(v, list) else v) for k, v in _JOB.items()}
        q = queue_list()
    pending = sum(1 for e in q if e["state"] == "queued")
    return {"available": True, "configured": configured(), "target": target(), "quality": quality(),
            "quality_choices": QUALITY_CHOICES, "job": job, "pending": pending, "queue": q, "dry_run": DRY_RUN,
            "sent": sent_summary(), "sent_items": sent_items()}
