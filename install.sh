#!/usr/bin/env bash
# Установка abook на новый компьютер (Linux или WSL2). Повторный запуск безопасен: только досоздаёт недостающее.
#   ./install.sh            — ядро: папки ~/abook, запускалки в ~/.local/bin, проверка зависимостей
#   ./install.sh --vec      — + векторы для смыслового поиска (~650 МБ: fastembed + модель e5-small)
#   ./install.sh --tg       — + Telegram (telethon в ~/abook/.venv-tg)
#   ./install.sh --desktop  — + ярлык «Аудиотека» на рабочем столе Windows (только WSL)
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
DATA="$HOME/abook"
say() { printf '\033[1m%s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1; }

say "abook → $REPO"
mkdir -p "$BIN" "$DATA/manifests" "$DATA/db-backups"
[ -f "$DATA/sources.json" ] || cp "$REPO/docs/sources.example.json" "$DATA/sources.json" 2>/dev/null || true

# запускалки: ~/.local/bin/abook → этот репозиторий
for f in abook abook-check abook-progress abook_ai.py abook_ai_ui.py abook_tg.py; do ln -sfn "$REPO/$f" "$BIN/$f"; done
cat > "$BIN/abook-ui" <<EOF
#!/usr/bin/env bash
# Веб-интерфейс аудиотеки. Флаги передаются в \`abook review\` (--port, --no-browser, ...).
exec "$REPO/abook" review "\$@"
EOF
cat > "$BIN/abook-ui-desktop" <<'EOF'
#!/usr/bin/env bash
# Ярлык на рабочем столе: сервер уже работает на 8790 — только открыть браузер; иначе запустить.
PORT=8790; URL="http://127.0.0.1:$PORT/"
if ! python3 -c "import socket;s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);s.bind(('127.0.0.1',$PORT))" 2>/dev/null; then
    if curl -s -m 3 -o /dev/null "$URL"; then cd /mnt/c && cmd.exe /c start "" "$URL" >/dev/null 2>&1; exit 0; fi
fi
exec "$HOME/.local/bin/abook-ui"
EOF
cat > "$BIN/abook-tg" <<EOF
#!/usr/bin/env bash
# Telegram-часть работает в своём окружении (telethon): ./install.sh --tg
PY="$DATA/.venv-tg/bin/python3"
[ -x "\$PY" ] || { echo "Telegram не установлен: $REPO/install.sh --tg"; exit 1; }
exec "\$PY" "$REPO/abook-tg" "\$@"
EOF
chmod +x "$BIN/abook-ui" "$BIN/abook-ui-desktop" "$BIN/abook-tg"
case ":$PATH:" in *":$BIN:"*) ;; *) say "Добавьте в ~/.bashrc:  export PATH=\"\$HOME/.local/bin:\$PATH\"";; esac

say "Проверяю зависимости"
for c in python3 ffmpeg ffprobe yt-dlp; do need "$c" && echo "  ✓ $c" || echo "  ✗ $c — нужен (см. docs/ЗАПУСК.md)"; done
need claude && echo "  ✓ claude (Claude Code)" || echo "  · claude — не найден (ИИ можно взять Antigravity)"
need agy && echo "  ✓ agy (Antigravity)" || echo "  · agy — не найден"
need gh && echo "  ✓ gh (скачать снимок каталога из GitHub)" || echo "  · gh — без него каталог: положить catalog.db в ~/abook или обойти заново"

for a in "$@"; do case "$a" in
  --vec)
    say "Векторы (смысловой поиск)"
    need uv || { curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH="$HOME/.local/bin:$PATH"; }
    uv venv -q "$DATA/.venv-vec" --python 3.12
    uv pip install -q --python "$DATA/.venv-vec/bin/python" fastembed onnxruntime numpy
    echo "  ✓ ~/abook/.venv-vec — модель скачается при первом поиске" ;;
  --tg)
    say "Telegram"
    python3 -m venv "$DATA/.venv-tg" && "$DATA/.venv-tg/bin/pip" install -q telethon cryptg
    echo "  ✓ теперь: abook-tg setup   (api_id и api_hash — https://my.telegram.org)" ;;
  --desktop)
    say "Ярлык на рабочем столе Windows"
    need wslpath || { echo "  только для WSL"; continue; }
    WIN_DESK="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%\Desktop' 2>/dev/null | tr -d '\r')")"
    DISTRO="${WSL_DISTRO_NAME:-Ubuntu}"
    printf '@echo off\r\nchcp 65001 >nul\r\ntitle Аудиотека\r\necho Аудиотека работает. Закройте это окно, чтобы остановить сервер.\r\nwsl.exe -d %s -e bash -lc "~/.local/bin/abook-ui-desktop"\r\nif errorlevel 1 pause\r\n' "$DISTRO" > "$WIN_DESK/Аудиотека.bat"
    echo "  ✓ $WIN_DESK/Аудиотека.bat" ;;
esac; done

say "Готово. Запуск: abook-ui  (или ярлык). Первый запуск откроет «Настройку»: ИИ, папка библиотеки, каталог, вкус, Telegram."
