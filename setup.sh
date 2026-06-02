#!/usr/bin/env bash
# 一鍵建環境。任何機器:進到本資料夾 → bash setup.sh。路徑全動態。
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if ! command -v uv >/dev/null 2>&1; then
  echo "需要 uv (https://docs.astral.sh/uv/)。或改用: python3 -m venv .venv && .venv/bin/pip install requests pyyaml streamlit"
  exit 1
fi

uv venv .venv
uv pip install --python .venv/bin/python requests pyyaml streamlit
echo
echo "✓ 環境就緒。常用指令:"
echo "  bash run.sh                                              # 開前台網站"
echo "  PYTHONPATH=code .venv/bin/python -m event_radar.pipeline # 收集+規則篩"
echo "  PYTHONPATH=code .venv/bin/python -m event_radar.scoring export  # 匯出待打分"
