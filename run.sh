#!/usr/bin/env bash
# 開前台 Streamlit。可重複執行:已在跑就只開瀏覽器,沒在跑才啟動。WSL 友善。
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
PORT="${PORT:-8501}"
URL="http://localhost:${PORT}"

open_browser() {
  ( command -v wslview >/dev/null 2>&1 && wslview "$URL" ) \
    || explorer.exe "$URL" 2>/dev/null \
    || cmd.exe /c start "" "$URL" 2>/dev/null \
    || echo ">> 瀏覽器沒自動開的話,手動開: $URL"
}

# 已在執行 → 只開瀏覽器就好(不重複啟動)
if curl -s --max-time 2 "$URL" -o /dev/null 2>/dev/null; then
  echo ">> Event Radar 已在執行,開啟瀏覽器…"
  open_browser
  exit 0
fi

[ -d .venv ] || bash setup.sh

# 背景:等 server 起來後開瀏覽器
( for _ in $(seq 1 30); do
    curl -s --max-time 1 "$URL" -o /dev/null 2>/dev/null && break
    sleep 1
  done
  open_browser ) &

echo ">> Event Radar 啟動中… 瀏覽器會自動開 ($URL)。"
echo ">> 關閉此視窗即停止伺服器。"
PYTHONPATH=code .venv/bin/streamlit run code/app/streamlit_app.py \
  --server.headless true --server.port "$PORT" --browser.gatherUsageStats false
