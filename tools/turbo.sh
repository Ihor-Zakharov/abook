#!/usr/bin/env bash
# Турбо-режим: перезапуск скачивания с максимумом потоков + запрет сна Windows до конца.
# Запуск: bash ~/abook/turbo.sh [потоков, по умолчанию 12]
# Движок direct: yt-dlp + ffmpeg, AAC без перекодирования → .m4a (упирается в сеть, не в CPU).
set -u
JOBS=${1:-12}
cd ~/abook || exit 1
FLAG_WIN='C:\Users\Ihor\abook-awake.flag'; FLAG=/mnt/c/Users/Ihor/abook-awake.flag

# 1. Аккуратно остановить текущий abook get (и его vydra / yt-dlp / ffmpeg)
for p in $(pgrep -f '^python3 /home/ihor/.local/bin/abook get'); do
  for c in $(pgrep -P "$p"); do pkill -P "$c"; kill "$c"; done; kill "$p"
done
sleep 3
ps -eo pid,args | awk '/^ *[0-9]+ \/home\/ihor\/.local\/share\/uv\/tools\/vydra\/bin\/python \/home\/ihor\/.local\/bin\/vydra d /{print $1}' | xargs -r kill
rm -rf staging/*/

# 2. Запрет сна: флаг + PowerShell-хранитель (живёт, пока есть флаг)
touch "$FLAG"
if pgrep -f 'abook-keep-awak[e]' >/dev/null; then
  echo "keep-awake уже работает — второй не запускаю"
else
  powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File 'C:\Users\Ihor\abook-keep-awake.ps1' -Flag "$FLAG_WIN" >/dev/null 2>&1 &
fi

# 3. Скачивание с максимумом потоков; по окончании — sync и снятие запрета сна
setsid nohup bash -c '
  cd ~/abook
  nice -n 5 abook get manifests/D-discoveries.json manifests/E-works.json manifests/A-prose.json \
    manifests/B-scifi.json manifests/C-classics.json manifests/G2-russian-classics.json \
    manifests/G1-western-classics.json manifests/H-radioplays.json manifests/I-games.json manifests/J-extra.json F-buldakov-top.json \
    --jobs '"$JOBS"' --engine direct --bitrate 128 --retry-failed > ~/abook/run-turbo.out 2>&1
  abook sync >> ~/abook/run-turbo.out 2>&1
  rm -f /mnt/c/Users/Ihor/abook-awake.flag
' >/dev/null 2>&1 < /dev/null &
echo "turbo: jobs=$JOBS, engine=direct, запрет сна включён (флаг $FLAG). Прогресс: http://localhost:8791/"
