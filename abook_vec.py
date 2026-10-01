"""abook_vec — семантические векторы для «Найти»: гибридный поиск (FTS + векторы, RRF), «вектор вкуса» и кандидаты
для RAG консультанта (abook_links.build_chat_prompt).

Два режима одного файла:
  • модуль сервера (системный python, только stdlib) — тексты для векторов, FTS-часть, RRF, вкус, HTTP;
  • демон `abook_vec.py --daemon` (venv ~/abook/.venv-vec: fastembed + onnxruntime + numpy) — модель, векторы, поиск
    полным перебором по матрице в памяти. Сервер запускает его лениво (первый гибридный запрос/чат) и общается
    JSON-строками по stdin/stdout: один запрос — одна строка ответа. Как abook_tg: тяжёлое — отдельным процессом.

Модель — intfloat/multilingual-e5-small (384 изм., ONNX через fastembed `add_custom_model`; префиксы «query: » /
«passage: »). Сравнение на 20 смысловых запросах по аннотациям библиотеки (01.10): e5-small hit@10 18/20, MRR 0,59;
paraphrase-multilingual-MiniLM-L12-v2 — 15/20, MRR 0,50 и вдвое медленнее. Считаем на CPU (16 потоков): для
библиотеки и каталога в тысячи записей GPU не нужен, а onnxruntime-gpu тянет ≈ 2 ГБ CUDA-библиотек.

Хранение: таблица vec_items(kind item|src|work, ref_id, model, sig, blob float16) в library.db; sig — хэш текста:
изменилась книга — пересчитается, исчезла — строка удаляется. Досчёт идёт в фоне демона, поиск работает по тому,
что уже посчитано. Нет venv/демона/numpy — всё работает как раньше: гибрид = только FTS, вкус = None, без ошибок.

Переменные: ABOOK_VEC=0 — выключить векторы; ABOOK_VEC_PY=<python> — другой интерпретатор демона;
ABOOK_VEC_MODEL=<имя> — другая модель (paraphrase-multilingual-MiniLM-L12-v2 из коробки fastembed).
"""
import contextlib
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

HOME = Path.home() / "abook"
VENV = Path(os.environ.get("ABOOK_VEC_VENV") or HOME / ".venv-vec")
MODEL = os.environ.get("ABOOK_VEC_MODEL") or "intfloat/multilingual-e5-small"
MODELS_DIR = VENV / "models"
RRF_K = 60
SYNC_EVERY = 1800                # с: не чаще — сверка текстов с vec_items без смены состава таблиц (фоном)
VEC_SQL = """CREATE TABLE IF NOT EXISTS vec_items(kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT NOT NULL,
  sig TEXT NOT NULL, blob BLOB NOT NULL, PRIMARY KEY(kind, ref_id, model))"""


def _prefixes(model):
    return ("query: ", "passage: ") if "e5" in model.lower() else ("", "")


# ======================================================================================== демон (venv)

def daemon_main(db_path, model):
    import numpy as np                                        # noqa: PLC0415
    from fastembed import TextEmbedding                        # noqa: PLC0415
    if model == "intfloat/multilingual-e5-small":
        from fastembed.common.model_description import ModelSource, PoolingType   # noqa: PLC0415
        with contextlib.suppress(Exception):                  # повторная регистрация — не ошибка
            TextEmbedding.add_custom_model(model=model, pooling=PoolingType.MEAN, normalization=True,
                                           sources=ModelSource(hf=model), dim=384, model_file="onnx/model.onnx")
    emb = TextEmbedding(model, cache_dir=str(MODELS_DIR), threads=os.cpu_count())
    qp, dp = _prefixes(model)
    lock = threading.Lock()
    st = {"keys": [], "pos": {}, "M": np.zeros((0, 384), np.float32), "todo": 0, "done": 0, "busy": False,
          "rate": None, "err": None}

    def db():
        c = sqlite3.connect(db_path, timeout=30)
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def vecs(texts, prefix):
        return np.asarray(list(emb.embed([prefix + t for t in texts], batch_size=32)), dtype=np.float32)

    def load():
        c = db()
        try:
            c.execute(VEC_SQL)
            c.commit()
            rows = c.execute("SELECT kind, ref_id, blob FROM vec_items WHERE model=?", (model,)).fetchall()
        finally:
            c.close()
        keys = [(k, r) for k, r, _ in rows]
        M = (np.frombuffer(b"".join(b for _, _, b in rows), np.float16).reshape(len(rows), -1).astype(np.float32) if rows
             else np.zeros((0, 384), np.float32))
        with lock:
            st.update(keys=keys, pos={k: i for i, k in enumerate(keys)}, M=M)

    def append(keys, V):
        with lock:
            new = []
            for k, v in zip(keys, V):
                i = st["pos"].get(k)
                if i is None:
                    st["pos"][k] = len(st["keys"]) + len(new)
                    new.append((k, v))
                else:
                    st["M"][i] = v
            if new:                        # новый список/матрица целиком: поиск в другом потоке видит старые
                st["keys"] = st["keys"] + [k for k, _ in new]
                st["M"] = np.vstack([st["M"], np.stack([v for _, v in new])])

    def sync_worker(todo):
        t0, n0 = time.time(), 0
        c = db()
        try:
            for i in range(0, len(todo), 64):
                ch = todo[i:i + 64]
                V = vecs([d[3] for d in ch], dp)
                with c:
                    c.executemany("INSERT OR REPLACE INTO vec_items(kind, ref_id, model, sig, blob) VALUES(?,?,?,?,?)",
                                  [(d[0], d[1], model, d[2], v.astype(np.float16).tobytes()) for d, v in zip(ch, V)])
                append([(d[0], d[1]) for d in ch], V)
                n0 += len(ch)
                st["done"] += len(ch)
                st["rate"] = round(n0 / max(0.001, time.time() - t0), 1)
        except Exception as e:
            st["err"] = str(e)[:300]
        finally:
            c.close()
            st["busy"] = False

    def sync(docs, kinds):
        """docs: [[kind, ref, sig, text]] — полный список по kinds; лишнее удаляется, новое/изменённое — в фон."""
        c = db()
        try:
            have = {(k, r): s for k, r, s in c.execute("SELECT kind, ref_id, sig FROM vec_items WHERE model=?", (model,))
                    if k in kinds}
            want = {(d[0], d[1]): d for d in docs}
            gone = [k for k in have if k not in want]
            with c:
                c.executemany("DELETE FROM vec_items WHERE kind=? AND ref_id=? AND model=?", [(k, r, model) for k, r in gone])
        finally:
            c.close()
        if gone:
            load()
        todo = [d for k, d in want.items() if have.get(k) != d[2]]
        if todo and not st["busy"]:
            st.update(busy=True, todo=len(todo), done=0, err=None)
            threading.Thread(target=sync_worker, args=(todo,), daemon=True).start()
        return {"todo": len(todo), "removed": len(gone)}

    def sync2(req):
        """Как sync, но разницу считает сервер: docs — только новые/изменённые, gone — удалённые ключи."""
        gone = [tuple(k) for k in req.get("gone") or []]
        if gone:
            c = db()
            try:
                with c:
                    c.executemany("DELETE FROM vec_items WHERE kind=? AND ref_id=? AND model=?", [(k, r, model) for k, r in gone])
            finally:
                c.close()
            load()
        todo = req.get("docs") or []
        if todo and st["busy"]:
            return {"todo": len(todo), "removed": len(gone), "busy": True}
        if todo:
            st.update(busy=True, todo=len(todo), done=0, err=None)
            threading.Thread(target=sync_worker, args=(todo,), daemon=True).start()
        return {"todo": len(todo), "removed": len(gone)}

    def qvec(req):
        if req.get("vec") is not None:
            v = np.asarray(req["vec"], np.float32)
        else:
            v = vecs([req["text"]], qp)[0]
        return v / (np.linalg.norm(v) or 1.0)

    def search(req):
        v = qvec(req)
        kinds = set(req.get("kinds") or ["item", "src", "work"])
        excl = {tuple(x) for x in req.get("exclude") or []}
        with lock:
            keys, M = st["keys"], st["M"]
        if not keys:
            return {"hits": []}
        s = M @ v
        want = int(req.get("k") or 20)
        m = min(len(keys), max(500, want * 8 + len(excl)))
        for full in (False, True):        # сначала частичная сортировка верхушки; не хватило после фильтра — вся
            if full or m >= len(keys):
                order = np.argsort(-s)
            else:
                top = np.argpartition(-s, m - 1)[:m]
                order = top[np.argsort(-s[top])]
            out = []
            for i in order:
                k = keys[i]
                if k[0] in kinds and k not in excl:
                    out.append([k[0], k[1], round(float(s[i]), 4)])
                    if len(out) >= want:
                        break
            if len(out) >= want or len(order) == len(keys):
                break
        return {"hits": out}

    def mix(req):
        """Взвешенная сумма векторов (вкус): weights [[kind, ref, w]], texts [[text, w]] — тексты без своих векторов."""
        acc = np.zeros(384, np.float32)
        used = 0
        with lock:
            for kind, ref, w in req.get("weights") or []:
                i = st["pos"].get((kind, ref))
                if i is not None:
                    acc += float(w) * st["M"][i]
                    used += 1
        tx = req.get("texts") or []
        if tx:
            V = vecs([t for t, _ in tx], dp)
            for (_, w), v in zip(tx, V):
                acc += float(w) * v
                used += 1
        n = float(np.linalg.norm(acc))
        return {"vec": [round(float(x), 5) for x in acc / n] if n > 0 else None, "used": used}

    def scores(req):
        v = qvec(req)
        out = []
        with lock:
            for kind, ref in req.get("keys") or []:
                i = st["pos"].get((kind, ref))
                out.append(None if i is None else round(float(st["M"][i] @ v), 4))
        return {"scores": out}

    tcache = {}

    def tvecs(texts):
        """Векторы текстов-сигналов (префикс запроса) с кэшем: анкета и профиль меняются редко."""
        miss = [t for t in dict.fromkeys(texts) if t not in tcache]
        if miss:
            for t, v in zip(miss, vecs(miss, qp)):
                tcache[t] = v / (np.linalg.norm(v) or 1.0)
            if len(tcache) > 20000:
                tcache.clear()
        return [tcache[t] for t in texts]

    def rank(req):
        """Модель вкуса (abook_rank): anchors [{key|text, w, sign, label}] -> грани (взвешенный k-means по косинусу
        положительных сигналов) и для каждой записи z-оценки: taste — лучшая грань, knn — среднее двух лучших
        отдельных сигналов, neg — ближайший «не моё». z — по всем записям выбранных kinds, чтобы грани и сигналы
        были сравнимы между собой. -> hits [[kind, ref, taste, knn, neg, грань]] (топ k + extra), facets."""
        with lock:
            keys, M, posd = st["keys"], st["M"], st["pos"]
        if not keys:
            return {"hits": [], "facets": []}
        an = req.get("anchors") or []
        V_ = [None] * len(an)
        for i, a in enumerate(an):
            j = posd.get(tuple(a["key"])) if a.get("key") else None
            if j is not None:
                V_[i] = M[j] / (np.linalg.norm(M[j]) or 1.0)
        need = [i for i, v in enumerate(V_) if v is None and an[i].get("text")]
        for i, v in zip(need, tvecs([an[i]["text"] for i in need]) if need else []):
            V_[i] = v
        P = [(V_[i], float(a["w"]), a.get("label") or "", bool(a.get("facet"))) for i, a in enumerate(an)
             if V_[i] is not None and a["sign"] > 0]
        N = [(V_[i], float(a["w"])) for i, a in enumerate(an) if V_[i] is not None and a["sign"] < 0]
        kinds = set(req.get("kinds") or ["item", "src", "work"])
        if st.get("kmask_n") != len(keys) or st.get("kmask_k") != kinds:
            st["kmask"] = np.array([k[0] in kinds for k in keys])
            st.update(kmask_n=len(keys), kmask_k=kinds)
        mask = st["kmask"]
        n = len(keys)
        if st.get("hub_n") != n or st.get("hub_M") is not M:
            # «хабы»: короткие шаблонные тексты («Аудиокнига-Триллер "…"») близки ко всему подряд и всплывают на
            # любой абстрактный сигнал. Поправка как в CSLS: средняя близость записи к 512 случайным записям.
            rng = np.random.default_rng(7)
            R = M[rng.choice(n, size=min(512, n), replace=False)]
            st.update(hub=(M @ R.T).mean(axis=1), hub_n=n, hub_M=M)
        hw = float(req.get("hub", 1.0))
        hub = st["hub"][:, None] * hw

        def z(S):
            S = S - hub
            sub = S[mask]
            mu, sd = sub.mean(axis=0), sub.std(axis=0) + 1e-6
            return (S - mu) / sd

        taste = np.zeros(n, np.float32)
        knn = np.zeros(n, np.float32)
        facet = np.full(n, -1)
        facets = []
        if P:
            X = np.stack([p[0] for p in P])
            w = np.array([p[1] for p in P], np.float32)
            Kc = int(req.get("centroids") or min(6, max(1, round(math.sqrt(len(P))))))
            cent = [int(np.argmax(w))]                          # farthest-first от самого весомого сигнала
            while len(cent) < Kc:
                d = (X @ X[cent].T).max(axis=1)
                cent.append(int(np.argmin(d)))
            C = X[cent].copy()
            for _ in range(8):
                lab = np.argmax(X @ C.T, axis=1)
                for j in range(len(C)):
                    m = lab == j
                    if m.any():
                        c = (X[m] * w[m, None]).sum(axis=0)
                        C[j] = c / (np.linalg.norm(c) or 1.0)
            lab = np.argmax(X @ C.T, axis=1)
            om = np.array([w[lab == j].sum() for j in range(len(C))], np.float32)
            om = om / (om.max() or 1.0)
            Zc = z(M @ C.T) * (0.5 + 0.5 * om)[None, :]
            taste = Zc.max(axis=1) + 0.2 * (Zc * om[None, :]).sum(axis=1) / (om.sum() or 1.0)
            facet = Zc.argmax(axis=1)
            Za = z(M @ X.T) * (0.6 + 0.4 * w / (w.max() or 1.0))[None, :]
            k2 = min(2, Za.shape[1])
            knn = -np.sort(-Za, axis=1)[:, :k2].mean(axis=1) if Za.shape[1] > 1 else Za[:, 0]
            for j in range(len(C)):
                mem = [i for i in np.argsort(-w) if lab[i] == j]
                mem.sort(key=lambda i: (not P[i][3], -w[i]))     # сначала словесные грани («любите», автор, память)
                facets.append({"label": " / ".join(P[i][2] for i in mem[:3]), "n": len(mem), "w": round(float(om[j]), 3)})
        neg = np.zeros(n, np.float32)
        if N:
            Y = np.stack([x[0] for x in N])
            wn = np.array([x[1] for x in N], np.float32)
            neg = (z(M @ Y.T) * (0.6 + 0.4 * wn / (wn.max() or 1.0))[None, :]).max(axis=1)
        comb = taste + float(req.get("knn_w", 0.6)) * knn - 0.5 * np.maximum(0, neg - 1.0)
        comb = np.where(mask, comb, -1e9)
        want = int(req.get("k") or 0)
        out = []
        if want > 0:
            top = np.argpartition(-comb, min(want, n - 1))[:want]
            top = top[np.argsort(-comb[top])]
            out = [[keys[i][0], keys[i][1], round(float(taste[i]), 4), round(float(knn[i]), 4), round(float(neg[i]), 4),
                    int(facet[i])] for i in top if comb[i] > -1e8]
        have = {(h[0], h[1]) for h in out}
        for kk in req.get("extra") or []:
            i = posd.get(tuple(kk))
            if i is not None and tuple(kk) not in have:
                out.append([kk[0], kk[1], round(float(taste[i]), 4), round(float(knn[i]), 4), round(float(neg[i]), 4),
                            int(facet[i])])
        return {"hits": out, "facets": facets, "anchors": len(P) + len(N)}

    load()
    ops = {"search": search, "mix": mix, "scores": scores, "rank": rank,
           "sync": lambda r: sync(r.get("docs") or [], set(r.get("kinds") or [])), "sync2": sync2,
           "embed": lambda r: {"vecs": [[round(float(x), 5) for x in v] for v in vecs(r["texts"], qp if r.get("query") else dp)]},
           "hello": lambda r: {"model": model, "n": len(st["keys"]), "busy": st["busy"], "todo": st["todo"],
                               "done": st["done"], "rate": st["rate"], "err": st["err"]}}
    sys.stdout.write(json.dumps({"ready": True, "model": model, "n": len(st["keys"])}) + "\n")
    sys.stdout.flush()
    for line in sys.stdin:
        try:
            req = json.loads(line)
            t0 = time.perf_counter()
            res = ops[req["op"]](req)
            res["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"[:400]}
        sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
        sys.stdout.flush()


# ======================================================================================== клиент (сервер, stdlib)

_D = {"proc": None, "db": None, "dead_until": 0.0, "synced": 0.0, "sig": None, "err": None}
_DLOCK = threading.Lock()


def _python():
    p = os.environ.get("ABOOK_VEC_PY") or str(VENV / "bin" / "python")
    return p if os.path.exists(p) else None


def enabled():
    return os.environ.get("ABOOK_VEC") != "0" and _python() is not None


def _db_path(conn):
    r = conn.execute("PRAGMA database_list").fetchone()
    return r[2] if r else str(HOME / "library.db")


def _start(dbp):
    py = _python()
    proc = subprocess.Popen([py, os.path.abspath(__file__), "--daemon", "--db", dbp, "--model", MODEL],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            bufsize=1, start_new_session=True)
    hello = proc.stdout.readline()          # загрузка модели ≈ 1–3 с (первый раз — ещё скачивание ≈ 470 МБ)
    if not hello or not json.loads(hello).get("ready"):
        with contextlib.suppress(Exception):
            proc.kill()
        raise RuntimeError("демон векторов не стартовал")
    return proc


def call(conn, op, timeout_dead=600, **kw):
    """Запрос к демону. None — векторов нет (venv не поставлен, демон упал — 10 мин не пытаемся снова)."""
    if not enabled():
        return None
    dbp = _db_path(conn)
    with _DLOCK:
        p = _D["proc"]
        if p and (p.poll() is not None or _D["db"] != dbp):
            with contextlib.suppress(Exception):
                p.kill()
            p = _D["proc"] = None
        if not p:
            if time.time() < _D["dead_until"]:
                return None
            try:
                p = _D["proc"] = _start(dbp)
                _D.update(db=dbp, synced=0.0, sig=None, err=None)
            except Exception as e:
                _D.update(dead_until=time.time() + timeout_dead, err=str(e)[:200])
                return None
        try:
            p.stdin.write(json.dumps({"op": op, **kw}, ensure_ascii=False) + "\n")
            p.stdin.flush()
            line = p.stdout.readline()
            res = json.loads(line) if line else None
        except Exception as e:
            res = None
            _D["err"] = str(e)[:200]
        if res is None:
            with contextlib.suppress(Exception):
                p.kill()
            _D.update(proc=None, dead_until=time.time() + 60)
            return None
        if res.get("error"):
            _D["err"] = res["error"]
            return None
        return res


def stop():
    with _DLOCK:
        if _D["proc"]:
            with contextlib.suppress(Exception):
                _D["proc"].kill()
            _D["proc"] = None


# ------------------------------------------------------------------ тексты для векторов

def _has_table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone() is not None


def _cols(conn, table):
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _features(conn):
    out = {}
    if _has_table(conn, "book_features"):
        for r in conn.execute("SELECT item_id, features FROM book_features"):
            with contextlib.suppress(Exception):
                out[r[0]] = json.loads(r[1])
    return out


def _feat_text(f):
    tags = []
    for k in ("themes", "ideas", "motifs", "tone", "hook"):
        v = f.get(k)
        tags += v if isinstance(v, list) else ([v] if v else [])
    return ", ".join(str(t) for t in tags[:12])


def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n]


def _tidy(s):
    """Срезать эмодзи и метки рубрик канала («📘[SCI-FI] Harlan Ellison» → «Harlan Ellison»)."""
    return re.sub(r"^[^\w\[]*(?:\[[^\]]{1,30}\]\s*)?", "", str(s or "")).strip()


def docs(conn):
    """Все тексты для векторов: [[kind, ref, sig, text]]. «автор — название. чтец. аннотация. признаки карты»."""
    feats = _features(conn)
    out = []

    def add(kind, ref, parts):
        t = ". ".join(p for p in (_clip(x, 700) for x in parts) if p)
        if t:
            out.append([kind, str(ref), hashlib.sha1(t.encode()).hexdigest()[:12], t])

    for r in conn.execute("SELECT id, author, title, narrator, about, note FROM items WHERE in_library=1 OR custom=1"):
        f = feats.get(r[0])
        add("item", r[0], [f"{r[1]} — {r[2]}" if r[1] else r[2], r[3], r[4] or r[5], _feat_text(f) if f else ""])
    if _has_table(conn, "src_items"):
        cols = _cols(conn, "src_items")
        ann = "annotation" if "annotation" in cols else None
        for r in conn.execute("SELECT id, author, work, title, reader" + (f", {ann}" if ann else "")
                              + " FROM src_items WHERE availability!='members'"):
            a = _tidy(r[1])
            if a:             # без автора — анонсы, стримы, «100 000 подписчиков»: в векторы не идут (шум)
                add("src", r[0], [f"{a} — {_tidy(r[2] or r[3])}", r[4], r[5] if ann else ""])
    if _has_table(conn, "works"):                 # произведения (abook_catalog, этап 2 п. 2) — если таблица уже есть
        cols = _cols(conn, "works")
        pick = [c for c in ("author", "title", "genre", "annotation", "about") if c in cols]
        if "id" in cols and "title" in pick:
            for r in conn.execute(f"SELECT id, {', '.join(pick)} FROM works"):
                d = dict(zip(["id"] + pick, r))
                f = feats.get(f"w{d['id']}")       # признаки карты связей, досчитанные abook_rank для топа выдачи
                add("work", d["id"], [f"{d.get('author') or ''} — {d['title']}".strip(" —"), d.get("genre") or "",
                                      d.get("annotation") or d.get("about") or "", _feat_text(f) if f else ""])
    return out


def _content_sig(conn):
    parts = [tuple(conn.execute("SELECT count(*), max(rowid) FROM items").fetchone())]
    for t in ("src_items", "works", "book_features"):
        if _has_table(conn, t):
            parts.append(tuple(conn.execute(f"SELECT count(*), max(rowid) FROM {t}").fetchone()))
    return json.dumps(parts)


def _sync_diff(dbp):
    """Сверка текстов с vec_items на своём соединении: демону уходят только новые/изменённые тексты и удалённые ключи."""
    c = sqlite3.connect(dbp, timeout=30)
    try:
        sig = _content_sig(c)
        ds = docs(c)
        kinds = {"item", "src"} | ({"work"} if _has_table(c, "works") else set())
        have = {}
        if _has_table(c, "vec_items"):
            have = {(k, r): s for k, r, s in c.execute("SELECT kind, ref_id, sig FROM vec_items WHERE model=?", (MODEL,))
                    if k in kinds}
        want = {(d[0], d[1]): d for d in ds}
        todo = [d for k, d in want.items() if have.get(k) != d[2]]
        gone = [list(k) for k in have if k not in want]
        r = call(c, "sync2", docs=todo, gone=gone)
        if r is not None and not r.get("busy"):
            _D.update(sig=sig, synced=time.time())
        return r
    finally:
        c.close()
        _D["syncing"] = False


def ensure_sync(conn, force=False):
    """Сверить vec_items с текущими текстами: фоном (force — сразу), когда сменился
    состав таблиц (count/max(rowid)) или раз в SYNC_EVERY. Запрос не ждёт: docs() по 60 тыс. записей ≈ 5 с."""
    if not enabled():
        return None
    sig = _content_sig(conn)
    if not force and _D["sig"] == sig and time.time() - _D["synced"] < SYNC_EVERY:
        return None
    if _D.get("syncing"):
        return None
    _D["syncing"] = True
    dbp = _db_path(conn)
    if force:
        return _sync_diff(dbp)
    threading.Thread(target=_sync_diff, args=(dbp,), daemon=True, name="abook-vec-sync").start()
    return {"background": True}


def status(conn):
    h = call(conn, "hello") if enabled() else None
    return {"enabled": enabled(), "model": MODEL, "daemon": h, "error": _D["err"]}


# ------------------------------------------------------------------ FTS-часть (библиотека и каталог источников)

_STOP = {"про", "что", "как", "это", "или", "для", "без", "все", "всё", "мне", "его", "так", "очень", "хочу", "книга",
         "книгу", "книги", "аудиокнига", "послушать", "посоветуй", "что-то", "нибудь", "чтобы", "где", "коротко"}


def _lib_fts(conn, q, limit=40):
    toks = [t for t in re.findall(r"\w+", q.lower().replace("ё", "е")) if len(t) >= 3 and t not in _STOP]
    if not toks:
        return [], []
    alts = set()
    for t in toks:
        alts |= {t} | ({t[:-1]} if len(t) >= 5 else set()) | ({t[:-2]} if len(t) >= 7 else set())
    def run(expr):
        with contextlib.suppress(sqlite3.OperationalError):
            return [r[0] for r in conn.execute(
                "SELECT f.id FROM items_fts f JOIN items i ON i.id=f.id WHERE items_fts MATCH ? AND (i.in_library=1 OR "
                "i.custom=1) ORDER BY bm25(items_fts,0,6.0,10.0,1,1,2,1) LIMIT ?", (expr, limit))]
        return []

    def alt(t):
        return "(" + " OR ".join(f'"{a}"*' for a in sorted({t} | ({t[:-1]} if len(t) >= 5 else set())
                                                          | ({t[:-2]} if len(t) >= 7 else set()))) + ")"
    strict = run(" AND ".join(alt(t) for t in toks)) if len(toks) > 1 else []
    loose = [i for i in run(" OR ".join(f'"{a}"*' for a in sorted(alts))) if i not in strict]
    return strict, loose


def _src_fts(conn, q, limit=40):
    if not _has_table(conn, "src_items"):
        return []
    with contextlib.suppress(Exception):
        import abook_catalog as C   # noqa: PLC0415
        return [r["id"] for r in C._fts(conn, q, limit) if r["availability"] != "members"][:limit]
    return []


# ------------------------------------------------------------------ гибрид (RRF)

def _rrf(lists, k=RRF_K):
    """lists: [(ключи по рангу, вес)]."""
    sc = {}
    for lst, w in lists:
        for rank, key in enumerate(lst):
            sc[key] = sc.get(key, 0.0) + w / (k + rank + 1)
    return sorted(sc, key=lambda x: -sc[x]), sc


def _hours(s):
    return round(s / 3600, 1) if s else None


def describe(conn, keys):
    """[(kind, ref)] -> карточки {kind, ref, key, author, title, reader, hours, ...} в том же порядке."""
    out = {}
    iids = [r for k, r in keys if k == "item"]
    if iids:
        q = ",".join("?" * len(iids))
        for r in conn.execute(f"SELECT i.id, i.author, i.title, i.narrator, i.hours, i.section, i.in_library, i.lang, "
                              f"i.about, (SELECT count(*) FROM files f WHERE f.item_id=i.id) AS nf FROM items i "
                              f"WHERE i.id IN ({q})", iids):
            out[("item", r[0])] = {"kind": "item", "ref": r[0], "id": r[0], "author": r[1], "title": r[2], "reader": r[3],
                                   "hours": r[4], "section": r[5], "in_library": bool(r[6]), "lang": r[7],
                                   "about": _clip(r[8], 240), "has_file": bool(r[9])}
    sids = [r for k, r in keys if k == "src"]
    if sids and _has_table(conn, "src_items"):
        q = ",".join("?" * len(sids))
        for r in conn.execute(f"SELECT id, source_id, author, work, title, reader, duration_s, availability, url, platform, "
                              f"channel, lang, downloadable FROM src_items WHERE id IN ({q})", [int(x) for x in sids]):
            out[("src", str(r[0]))] = {"kind": "src", "ref": str(r[0]), "id": f"s{r[0]}", "src_key": r[1],
                                       "author": _tidy(r[2]), "title": _tidy(r[3] or r[4]), "raw_title": r[4], "reader": r[5],
                                       "hours": _hours(r[6]), "availability": r[7], "url": r[8], "platform": r[9],
                                       "channel": r[10], "lang": r[11], "downloadable": bool(r[12]),
                                       "in_library": False, "has_file": False}
    wids = [r for k, r in keys if k == "work"]
    if wids and _has_table(conn, "works"):
        cols = _cols(conn, "works")
        pick = [c for c in ("author", "title") if c in cols]
        q = ",".join("?" * len(wids))
        with contextlib.suppress(sqlite3.Error):
            for r in conn.execute(f"SELECT id, {', '.join(pick)} FROM works WHERE id IN ({q})", wids):
                d = dict(zip(["id"] + pick, r))
                out[("work", str(d["id"]))] = {"kind": "work", "ref": str(d["id"]), "id": f"w{d['id']}",
                                               "author": d.get("author") or "", "title": d.get("title") or "",
                                               "in_library": False, "has_file": False}
    return [out[k] for k in keys if k in out]


SCOPES = {"library": ["item"], "catalog": ["src", "work"], "all": ["item", "src", "work"]}


def hybrid(conn, q, k=20, scope="all"):
    """RRF(FTS, векторы). -> {q, scope, k, ms, vec: bool, items:[карточка + fts/vec ранги]}."""
    t0 = time.perf_counter()
    kinds = SCOPES.get(scope, SCOPES["all"])
    lists, ranks = [], {}
    if "item" in kinds:
        strict, loose = _lib_fts(conn, q, 40)
        lf = [("item", i) for i in strict + loose]
        lists += [([("item", i) for i in strict], 1.0), ([("item", i) for i in loose], 0.5)]   # «хоть одно слово» — слабее
        ranks.update({x: {"fts": n + 1} for n, x in enumerate(lf)})
    if "src" in kinds:
        sf = [("src", str(i)) for i in _src_fts(conn, q, 40)]
        lists.append((sf, 1.0))
        ranks.update({x: {"fts": n + 1} for n, x in enumerate(sf)})
    vec = None
    with contextlib.suppress(Exception):
        ensure_sync(conn)
        vec = call(conn, "search", text=q, k=60, kinds=kinds)
    if vec:
        vl = [(h[0], h[1]) for h in vec["hits"]]
        lists.append((vl, 1.0))
        for n, (x, h) in enumerate(zip(vl, vec["hits"])):
            ranks.setdefault(x, {}).update(vec=n + 1, sim=h[2])
    order, sc = _rrf(lists)
    cards = describe(conn, order[:k * 2])
    out = []
    for c in cards:
        key = (c["kind"], c["ref"])
        if c.get("availability") == "members":
            continue
        out.append({**c, "rrf": round(sc[key], 5), **ranks.get(key, {})})
        if len(out) >= k:
            break
    return {"q": q, "scope": scope, "k": k, "vec": bool(vec), "ms": round((time.perf_counter() - t0) * 1000, 1),
            "items": out}


# ------------------------------------------------------------------ вектор вкуса

_TASTE = {}


def taste_vector(conn, pid):
    """Вкус профиля одним вектором (для колонки «вкус» в гибриде): Σ ± вес · v(сигнал) по всем сигналам модели
    вкуса abook_rank (анкета, профиль ИИ, отзывы, память, реакции). Многогранный вкус и ранжирование — abook_rank.rank.
    -> (вектор | None, сколько сигналов). Кэш — по составу сигналов."""
    import abook_rank as R   # noqa: PLC0415
    pr = R.profile(conn, pid)
    weights, texts = [], []
    for sign, lst in ((1.0, pr["pos"]), (-0.5, pr["neg"])):
        for s in lst:
            if s.get("key"):
                weights.append([s["key"][0], s["key"][1], round(sign * s["w"], 4)])
            texts.append([s.get("text") or s["label"], round(sign * s["w"] * (0.5 if s.get("key") else 1.0), 4)])
    sig = json.dumps([weights, texts], ensure_ascii=False)
    hit = _TASTE.get(pid)
    if hit and hit[0] == sig and time.time() - hit[2] < 3600:
        return hit[1], hit[3]
    if not weights and not texts:
        _TASTE[pid] = (sig, None, time.time(), 0)
        return None, 0
    ensure_sync(conn)
    r = call(conn, "mix", weights=weights, texts=texts[:80])
    v = r and r.get("vec")
    n = r.get("used", 0) if r else 0
    _TASTE[pid] = (sig, v, time.time(), n)
    return v, n


def taste_scores(conn, pid, keys):
    """«Понравится ли» для любых записей: косинус с вектором вкуса (−1..1) или None."""
    v, _ = taste_vector(conn, pid)
    if not v:
        return [None] * len(keys)
    r = call(conn, "scores", vec=v, keys=[list(k) for k in keys])
    return r["scores"] if r else [None] * len(keys)


def foryou(conn, pid, k=20, q=""):
    """Топ нескачанного «для вас» со всего каталога (произведения каталога источников + библиотека без файла):
    двухэтапный отбор abook_rank.rank — модель вкуса, качество, доступность, язык, длительность."""
    import abook_rank as R   # noqa: PLC0415
    res = R.rank(conn, pid, q, k=k, mode="foryou")
    res.update(k=k, signals=len(R.profile(conn, pid)["pos"]))
    return res


# ------------------------------------------------------------------ кандидаты для RAG консультанта

def _as_src(c):
    """Произведение каталога -> карточка его лучшей записи (id «s<id>»: так её принимает validate_recs и скачивает
    POST /api/find/download {catalog_key: src_key})."""
    if c["kind"] != "work" or not c.get("best_src"):
        return c
    return {**c, "kind": "src", "ref": str(c["best_src"]), "id": f"s{c['best_src']}", "work_id": c["ref"]}


def rag_candidates(conn, pid, text, lib, excluded, bridges=(), n=40):
    """~n кандидатов для промпта консультанта одним ранжированием abook_rank.rank (mode=rag): запрос, грани вкуса,
    мосты карты связей, качество, доступность. Каталог источников (нескачанное) — не больше половины.
    -> карточки (kind item|src) с полем why: откуда кандидат."""
    import abook_rank as R   # noqa: PLC0415
    res = R.rank(conn, pid, text, k=n * 2, mode="rag", bridges=bridges, lib=lib, exclude_ids=excluded)
    out, n_src = [], 0
    for c in res["items"]:
        c = _as_src(c)
        if c["kind"] == "work":
            continue                       # произведение без открытой записи — советовать нечего
        if c["kind"] == "src":
            if n_src >= n // 2:
                continue
            n_src += 1
        p = c.get("parts") or {}
        c["why"] = ("запрос" if p.get("query", 0) >= 0.3 else "мост" if p.get("bridge", 0) >= 0.3
                    else "вкус: " + _clip(re.split(r" / ", c.get("facet_label") or "")[0], 32) if c.get("facet_label") else "вкус")
        out.append(c)
        if len(out) >= n:
            break
    return out


def cand_line(c, feats=None):
    """Строка кандидата для промпта (≈ 25 токенов): id | автор — название | ч | чтец | признаки/пометки."""
    fid = c["ref"] if c["kind"] == "item" else (f"w{c['work_id']}" if c.get("work_id") else None)
    f = (feats or {}).get(fid) if fid else None
    tags = []
    if f:
        for k in ("motifs", "ideas", "themes", "tone"):
            tags += [str(x) for x in (f.get(k) or [])][:1]
    h = c.get("hours")
    parts = [c["id"], f"{_clip(c.get('author'), 28)} — {_clip(c.get('title'), 50)}", f"{h:.1f} ч" if h else "? ч",
             _clip(re.sub(r"\s*\(.*", "", c.get("reader") or ""), 22) or "—"]
    if c["kind"] == "src":
        parts.append("нет на диске, " + (c.get("platform") or "запись") + (", доступ?" if c.get("availability") == "unknown" else ""))
    elif not c.get("has_file"):
        parts.append("в каталоге, не скачано")
    if tags:
        parts.append(", ".join(tags[:3]))
    elif c.get("about"):
        parts.append(_clip(c["about"], 55))
    ql = c.get("quality") or {}
    if ql.get("canon", 0) >= 0.5 or (ql.get("rating") or 0) >= 0.75:
        parts.append("★")                 # канон Wikidata или высокий сглаженный рейтинг (abook_rank.quality_bulk)
    parts.append(c.get("why") or "")
    return " | ".join(p for p in parts if p)


# ------------------------------------------------------------------ HTTP (через abook_links.handle_get)

def handle_get(h, conn, p, arg, pid):
    if p == "/api/find/hybrid":
        k = max(1, min(100, int(arg("k") or 20)))
        res = hybrid(conn, arg("q") or "", k=k, scope=arg("scope") or "all")
        ks = [(c["kind"], c["ref"]) for c in res["items"]]
        for c, s in zip(res["items"], taste_scores(conn, pid, ks) if ks and res["vec"] else [None] * len(ks)):
            c["taste"] = s
        return h._json(res)
    if p in ("/api/find/foryou", "/api/find/feedback", "/api/find/quality/status"):     # модель вкуса — abook_rank.py
        import abook_rank as R   # noqa: PLC0415
        return R.handle_get(h, conn, p, arg, pid)
    if p == "/api/find/vec/status":
        return h._json(status(conn))
    return None


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        a = sys.argv
        daemon_main(a[a.index("--db") + 1], a[a.index("--model") + 1] if "--model" in a else MODEL)
