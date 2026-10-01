"""abook_setup — мастер «Настройка» первого запуска и снимок каталога для другого компьютера.

Шаги (каждый можно пройти позже, приложение работает и без них):
  1. ИИ — провайдер Claude Code или Antigravity (abook_llm), проверка: CLI найден и отвечает (короткий вызов
     быстрой моделью).
  2. Библиотека — куда класть аудиокниги на этом компьютере (~/abook/config.json → library, staging).
  3. Каталог — книги со всего интернета: скачать готовый снимок (без личных данных: src_items, works, векторы
     каталога) или обойти источники заново (~2,5 ч в фоне).
  4. Профиль — анкета по шагам или рассказом (экран «Анкета»).
  5. Telegram — необязательно; гайд `abook-tg setup`, можно «позже».

Снимок каталога: `python3 abook_setup.py snapshot --db ~/abook/library.db --out catalog.db` — отдельная SQLite
только с общими таблицами каталога; на другом компьютере «Скачать каталог» берёт его из релиза приватного
репозитория (`gh release download`) или из файла рядом, и вливает в локальную базу (INSERT OR IGNORE).
"""
import contextlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

CATALOG_TABLES = ("src_items", "works", "src_crawls", "src_sitemap", "probe_cache")
VEC_KINDS = ("src", "work")
REPO = os.environ.get("ABOOK_REPO", "Ihor-Zakharov/abook")
ASSET = "catalog.db"


def _A():
    import abook_find as F   # noqa: PLC0415
    return F.A


def cfg_path():
    return _A().ABOOK_DIR / "config.json"


def load_cfg():
    with contextlib.suppress(OSError, ValueError):
        return json.loads(cfg_path().read_text(encoding="utf-8"))
    return {}


def save_cfg(**kw):
    c = load_cfg()
    c.update({k: v for k, v in kw.items() if v is not None})
    cfg_path().parent.mkdir(parents=True, exist_ok=True)
    cfg_path().write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    return c


def _count(conn, table):
    with contextlib.suppress(Exception):
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    return 0


def status(conn):
    import abook_llm as LLM   # noqa: PLC0415
    A = _A()
    c = load_cfg()
    lib = Path(str(A.AUDIOBOOKS_ROOT))
    tg = None
    with contextlib.suppress(Exception):
        tg = bool(A.TG and A.TG.configured())
    n_src = _count(conn, "src_items")
    answered = 0
    with contextlib.suppress(Exception):
        answered = conn.execute("SELECT count(*) FROM questionnaire WHERE status='submitted'").fetchone()[0]
    sy = {}
    with contextlib.suppress(Exception):
        import abook_sync as SY   # noqa: PLC0415
        sy = SY.status()
    steps = [
        {"k": "llm", "t": "ИИ", "done": bool(c.get("llm_ok")), "info": LLM.status()},
        {"k": "library", "t": "Библиотека", "done": lib.exists() and os.access(lib, os.W_OK),
         "info": {"path": str(lib), "windows": _win(lib), "exists": lib.exists()}},
        {"k": "catalog", "t": "Каталог", "done": n_src >= 1000,
         "info": {"records": n_src, "works": _count(conn, "works"), "job": dict(_JOB) if _JOB else None,
                  "snapshot": _snapshot_source()}},
        {"k": "profile", "t": "Профиль", "done": answered > 0, "info": {"answered": answered}},
        {"k": "telegram", "t": "Telegram", "done": bool(tg) or bool(c.get("tg_skipped")),
         "info": {"configured": bool(tg), "skipped": bool(c.get("tg_skipped"))}},
        {"k": "sync", "t": "Другие компьютеры", "done": bool(sy.get("configured")) or bool(c.get("sync_skipped")), "info": sy}]
    return {"steps": steps, "complete": all(s["done"] for s in steps), "dismissed": bool(c.get("setup_dismissed"))}


def _win(p):
    s = str(p)
    if s.startswith("/mnt/") and len(s) > 6:
        return s[5].upper() + ":\\" + s[7:].replace("/", "\\")
    return s


def test_llm():
    """Короткий вызов быстрой моделью выбранного провайдера: CLI есть, вход выполнен, ответ приходит."""
    import abook_find as F   # noqa: PLC0415
    schema = {"type": "object", "additionalProperties": False, "required": ["ok"], "properties": {"ok": {"type": "string"}}}
    t0 = time.time()
    data, meta, err = F.run_claude('Ответь JSON {"ok": "да"}.', schema, F.new_job(), "haiku", timeout=120, budget=0.05)
    ok = bool(data) and not err
    if ok:
        save_cfg(llm_ok=True)
    return {"ok": ok, "error": err, "seconds": round(time.time() - t0, 1), "model": (meta or {}).get("model")}


def set_library(path):
    p = Path(str(path or "").strip().strip('"'))
    s = str(p)
    if len(s) > 2 and s[1] == ":":                     # D:\Книги → /mnt/d/Книги
        s = "/mnt/" + s[0].lower() + "/" + s[3:].replace("\\", "/")
        p = Path(s)
    if not s or not p.is_absolute():
        raise ValueError("Укажите полный путь к папке, например D:\\Аудиокниги")
    p.mkdir(parents=True, exist_ok=True)
    if not os.access(p, os.W_OK):
        raise ValueError("В эту папку нельзя писать")
    staging = p.parent / ".abook-staging"
    save_cfg(library=str(p), staging=str(staging))
    return {"ok": True, "path": str(p), "restart": True}


# ------------------------------------------------------------------ снимок каталога

def snapshot(db, out):
    """Общие таблицы каталога (без личных данных) → отдельная SQLite."""
    out = Path(out)
    if out.exists():
        out.unlink()
    src = sqlite3.connect(db)
    src.execute(f"ATTACH DATABASE ? AS snap", (str(out),))
    for t in CATALOG_TABLES:
        if src.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t,)).fetchone():
            src.execute(f"CREATE TABLE snap.{t} AS SELECT * FROM main.{t}")
    if src.execute("SELECT 1 FROM sqlite_master WHERE name='vec_items'").fetchone():
        src.execute("CREATE TABLE snap.vec_items AS SELECT * FROM main.vec_items WHERE kind IN ('src','work')")
    src.commit()
    src.execute("DETACH DATABASE snap")
    src.close()
    s = sqlite3.connect(out)
    s.execute("VACUUM")
    s.close()
    return {"path": str(out), "mb": round(out.stat().st_size / 1e6, 1)}


def _snapshot_source():
    local = _A().ABOOK_DIR / ASSET
    if local.exists():
        return {"kind": "file", "path": str(local)}
    if shutil.which("gh"):
        return {"kind": "release", "repo": REPO}
    return None


_JOB = {}


def import_snapshot_async(conn_factory):
    if _JOB.get("running"):
        raise ValueError("Каталог уже загружается")
    _JOB.clear()
    _JOB.update(running=True, phase="готовлюсь", started=time.time())
    threading.Thread(target=_import_worker, args=(conn_factory,), daemon=True, name="abook-snapshot").start()
    return dict(_JOB)


def _import_worker(conn_factory):
    A = _A()
    try:
        path = A.ABOOK_DIR / ASSET
        if not path.exists():
            if not shutil.which("gh"):
                raise RuntimeError("Нет файла каталога и не установлен gh — положите catalog.db в ~/abook или запустите обход")
            _JOB["phase"] = "скачиваю снимок каталога из GitHub"
            r = subprocess.run(["gh", "release", "download", "--repo", REPO, "--pattern", ASSET, "--dir", str(A.ABOOK_DIR),
                                "--clobber"], capture_output=True, text=True, timeout=3600)
            if r.returncode != 0:
                raise RuntimeError("gh: " + (r.stderr or r.stdout).strip()[:300])
        _JOB["phase"] = "вливаю каталог в базу"
        conn = conn_factory()
        try:
            import abook_catalog as C   # noqa: PLC0415
            with contextlib.suppress(Exception):
                C.migrate(conn)                       # таблицы каталога в этой базе
            conn.execute("ATTACH DATABASE ? AS snap", (str(path),))
            done = {}
            for t in CATALOG_TABLES + ("vec_items",):
                if not conn.execute("SELECT 1 FROM snap.sqlite_master WHERE name=?", (t,)).fetchone():
                    continue
                if not conn.execute("SELECT 1 FROM main.sqlite_master WHERE name=?", (t,)).fetchone():
                    conn.execute(f"CREATE TABLE main.{t} AS SELECT * FROM snap.{t} WHERE 0")
                cols = [r[1] for r in conn.execute(f"PRAGMA main.table_info({t})")]
                scols = {r[1] for r in conn.execute(f"PRAGMA snap.table_info({t})")}
                cl = ",".join(c for c in cols if c in scols)
                cur = conn.execute(f"INSERT OR IGNORE INTO main.{t}({cl}) SELECT {cl} FROM snap.{t}")
                done[t] = cur.rowcount
            conn.commit()
            conn.execute("DETACH DATABASE snap")
            _JOB["phase"] = "строю поисковый индекс"
            conn.execute("DELETE FROM src_crawls WHERE source='_fts'")   # снимок принёс отметку чужого индекса
            conn.commit()
            C.reindex(conn)                           # FTS по записям
            with A._WRITE_LOCK, A._tx(conn):          # FTS произведений: rebuild_works пишет его только для изменившихся
                conn.execute("DELETE FROM works_fts")
                for w in conn.execute("SELECT * FROM works").fetchall():
                    conn.execute("INSERT INTO works_fts(rowid, norm) VALUES(?,?)", (w["id"], C._works_text(dict(w))))
            _JOB.update(done=done)
        finally:
            conn.close()
        _JOB["phase"] = "готово"
    except Exception as e:
        _JOB.update(error=str(e)[:400], phase="ошибка")
    finally:
        _JOB["running"] = False


def handle_get(h, conn):
    return h._json(status(conn))


def handle_post(h, conn, payload):
    op = payload.get("op")
    if op == "test_llm":
        return h._json(test_llm())
    if op == "library":
        return h._json(set_library(payload.get("path")))
    if op == "catalog_download":
        return h._json(import_snapshot_async(_A().db_connect))
    if op == "catalog_crawl":
        import abook_catalog as C   # noqa: PLC0415
        return h._json(C.start_crawl(source=None))
    if op == "skip_tg":
        save_cfg(tg_skipped=True)
        return h._json({"ok": True})
    if op == "skip_sync":
        save_cfg(sync_skipped=True)
        return h._json({"ok": True})
    if op == "dismiss":
        save_cfg(setup_dismissed=True)
        return h._json({"ok": True})
    return h._json({"error": "неизвестная операция"}, 400)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Снимок каталога abook (без личных данных)")
    ap.add_argument("cmd", choices=["snapshot"])
    ap.add_argument("--db", default=str(Path.home() / "abook/library.db"))
    ap.add_argument("--out", default="catalog.db")
    a = ap.parse_args()
    print(json.dumps(snapshot(a.db, a.out), ensure_ascii=False))
    sys.exit(0)
