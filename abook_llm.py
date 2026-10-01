"""abook_llm — выбор ИИ-провайдера для всего приложения: Claude Code (`claude -p`) или Antigravity (`agy`, Gemini).

Все вызовы ИИ в abook идут через две функции: abook_find.run_claude (ответ JSON по схеме) и abook_links.stream_claude
(потоковый ответ). Обе в начале спрашивают provider(); для «agy» работа уходит сюда — с тем же контрактом
(data | None, meta, error | None), теми же событиями для UI (job["live"], F.phase/F.event) и отменой.

Модели — по уровню, а не по имени: «claude-модель» из вызова переводится в ступень и на Antigravity берётся
соответствующая Gemini:
    opus   → gemini-3.1-pro-high      (консультант, подбор, поиск — где важно качество)
    sonnet → gemini-3.8-flash-high    (анкета из рассказа, карта связей)
    haiku  → gemini-3.8-flash-low     (вопросы анкеты, сводка памяти, резюме разговора)
Переопределить: ABOOK_AGY_MODEL_SMART / _MID / _FAST.

Длинный промпт у agy передаётся файлом в рабочем каталоге (аргумент командной строки в Linux ≤ 128 КБ), модель
читает его своим инструментом чтения. Выбор провайдера — ~/abook/llm.json (общий для всех профилей); переменная
ABOOK_LLM=claude|agy его перекрывает.
"""
import contextlib
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import abook_find as F

AGY_BIN = os.environ.get("ABOOK_FIND_AGY") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")
TIERS = {"smart": os.environ.get("ABOOK_AGY_MODEL_SMART", "gemini-3.1-pro-high"),
         "mid": os.environ.get("ABOOK_AGY_MODEL_MID", "gemini-3.8-flash-high"),
         "fast": os.environ.get("ABOOK_AGY_MODEL_FAST", "gemini-3.8-flash-low")}
INLINE_MAX = 60_000            # байт: короче — аргументом -p, длиннее — файлом
PROVIDERS = {"claude": "Claude (Claude Code)", "agy": "Antigravity (Gemini)"}


def _cfg_path():
    return Path(F.A.STATE_PATH).parent / "llm.json" if F.A and hasattr(F.A, "STATE_PATH") else Path.home() / "abook/llm.json"


def provider():
    env = os.environ.get("ABOOK_LLM")
    if env in PROVIDERS:
        return env
    with contextlib.suppress(Exception):
        p = json.loads(_cfg_path().read_text(encoding="utf-8")).get("provider")
        if p in PROVIDERS:
            return p
    return "claude"


def available():
    return {"claude": F.claude_ok(), "agy": bool(shutil.which(AGY_BIN) or Path(AGY_BIN).exists())}


def set_provider(p):
    if p not in PROVIDERS:
        raise ValueError("Провайдер: claude или agy")
    if not available()[p]:
        raise ValueError(f"{PROVIDERS[p]}: CLI не найден")
    path = _cfg_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"provider": p}, ensure_ascii=False), encoding="utf-8")
    return status()


def status():
    p = provider()
    return {"provider": p, "label": PROVIDERS[p], "providers": PROVIDERS, "available": available(),
            "models": {"claude": {"smart": "opus", "mid": "sonnet", "fast": "haiku"}, "agy": TIERS}}


def tier_of(model):
    m = str(model or "").lower()
    return "fast" if "haiku" in m else "mid" if "sonnet" in m else "smart"


def model_label(model):
    return TIERS[tier_of(model)] if provider() == "agy" else model


# ------------------------------------------------------------------ вызов agy

def run(prompt, job, model, schema=None, timeout=360, stream=False, who="Antigravity"):
    """Один вызов agy. stream=True — текст до строки <<<DATA копится в job["live"] (как у stream_claude).
    -> (data | None, meta, error | None); без схемы data = {"text": полный ответ}."""
    wd = F.workdir()
    gm = TIERS[tier_of(model)]
    raw = prompt.encode("utf-8")
    pf = None
    if len(raw) > INLINE_MAX:
        pf = wd / f"prompt-{uuid.uuid4().hex[:10]}.md"
        pf.write_bytes(raw)
        arg = (f"Полное задание — в файле {pf.name} в рабочем каталоге. Прочитай его целиком своим инструментом "
               "чтения файлов и выполни точно; кроме чтения этого файла и (если задание разрешает) поиска в интернете "
               "ничего не делай.")
    else:
        arg = prompt
    cmd = [AGY_BIN, "--add-dir", str(wd), "--model", gm, "--output-format", "stream-json", "--disable-slash-commands"]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    cmd += [f"-p={arg}"]
    t0 = time.time()
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                cwd=str(wd), env=F._clean_env(), start_new_session=True)
    except OSError as e:
        return None, {"seconds": 0, "who": who}, f"{who} не запустился: {e}"
    job["procs"].add(proc)
    final, err_tail, buf, usage = {}, [], [""], {}

    def read_out():
        for line in proc.stdout:
            try:
                ev = json.loads(line.decode("utf-8", "replace"))
            except Exception:
                continue
            kind = ev.get("event")
            if kind == "step_update":
                su = ev.get("step_update") or {}
                if su.get("step_type") == "agent_response" and su.get("text_delta"):
                    buf[0] += su["text_delta"]
                    if stream:
                        if not job.get("streaming"):
                            job["streaming"] = True
                            F.phase(job, "Пишет ответ")
                        job["live"] = buf[0].split("<<<DATA", 1)[0].rstrip("<").rstrip()
                elif su.get("step_type") and su.get("state") == "ACTIVE" and su.get("step_type") != "agent_response":
                    F.event(job, "step", su.get("step_type"), who)
                if su.get("usage"):
                    usage.update(su["usage"])
            elif kind == "result":
                final.update(ev.get("result") or {})

    def read_err():
        for line in proc.stderr:
            err_tail.append(line.decode("utf-8", "replace").rstrip())
            del err_tail[:-20]

    ths = [threading.Thread(target=f, daemon=True) for f in (read_out, read_err)]
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
    for th in ths:
        th.join(timeout=5)
    job["procs"].discard(proc)
    if pf:
        with contextlib.suppress(Exception):
            pf.unlink()
    u = final.get("usage") or usage
    meta = {"who": who, "provider": "agy", "model": gm, "seconds": round(time.time() - t0, 1), "rc": proc.returncode,
            "tokens_in": u.get("input_tokens"), "tokens_out": u.get("output_tokens"),
            "tokens_cached": u.get("cache_read_tokens"), "cost_usd": None, "stream": stream}
    if reason == "cancel" or job.get("cancel"):
        raise F.Cancelled()
    if reason == "timeout":
        return None, meta, f"{who}: нет ответа за {timeout // 60} мин"
    if not final:
        tail = " / ".join(x for x in err_tail[-3:] if x)
        return None, meta, f"{who} завершился без результата (код {proc.returncode}){': ' + tail[:300] if tail else ''}"
    if str(final.get("status") or "").upper() not in ("SUCCESS", "OK", ""):
        return None, meta, f"{who}: {final.get('status')}: {str(final.get('error') or final.get('response') or '')[:300]}"
    text = final.get("response") or buf[0]
    if schema:
        data = final.get("structured_output") or F.parse_json_loose(text)
        if not isinstance(data, dict):
            return None, meta, f"{who}: ответ не разобрать как JSON"
        return data, meta, None
    return {"text": text}, meta, None
