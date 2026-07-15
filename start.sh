#!/usr/bin/env bash
set -e

# 切换到脚本所在目录
cd "$(dirname "$0")"

VENV=".venv"
MARKER="$VENV/.installed"

# 初次安装：创建虚拟环境并安装依赖
if [ ! -f "$MARKER" ]; then
    echo "首次运行，正在初始化环境..."
    python3 -m venv "$VENV"
    source "$VENV/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt
    touch "$MARKER"
    echo "依赖安装完成。"
else
    source "$VENV/bin/activate"
fi

# 启动主程序
.venv/bin/python run.py "$@"