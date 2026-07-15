#!/usr/bin/env bash
set -e

# 切换到脚本所在目录
cd "$(dirname "$0")"

VENV=".venv"
MARKER="$VENV/.installed"

# 查找可用的 Python（需要 >=3.10）
PYTHON=""
for py in python3.12 python3.11 python3.10 python3; do
    if command -v $py &>/dev/null; then
        ver=$($py -c 'import sys; print(sys.version_info[:2])' 2>/dev/null)
        if [ "$ver" = "(3, 12)" ] || [ "$ver" = "(3, 11)" ] || [ "$ver" = "(3, 10)" ] || [ "$ver" = "(3, 13)" ] || [ "$ver" = "(3, 14)" ]; then
            PYTHON=$py
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "错误: 需要 Python >= 3.10，请安装后重试。"
    exit 1
fi

# 初次安装：创建虚拟环境并安装依赖
if [ ! -f "$MARKER" ]; then
    echo "首次运行，正在初始化环境 (使用 $PYTHON)..."
    $PYTHON -m venv "$VENV"
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