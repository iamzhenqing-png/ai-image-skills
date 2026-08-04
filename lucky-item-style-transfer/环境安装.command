#!/bin/bash
# ============================================================
# 幸运物风格迁移 — 一键环境安装（macOS 双击运行）
# 作用：自动检测并安装运行所需的全部依赖，新同事上手只需双击这一个文件。
# 安装内容：Python3 检测、pip 依赖（playwright / rembg / Pillow / numpy）
# 说明：本流程用你本机已安装的 Google Chrome，无需额外下载浏览器。
# ============================================================

# 切到脚本所在目录
cd "$(dirname "$0")" || exit 1

echo "============================================================"
echo "  幸运物风格迁移 · 环境安装"
echo "============================================================"
echo ""

# ---------- 1. 检查 Python3 ----------
echo "[1/4] 检查 Python3 ..."
if ! command -v python3 >/dev/null 2>&1; then
    echo "  ❌ 未检测到 Python3。"
    echo "     请先安装 Python3：打开 https://www.python.org/downloads/ 下载安装后，"
    echo "     再重新双击本文件。"
    echo ""
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi
PY_VER=$(python3 --version 2>&1)
echo "  ✅ 已检测到 $PY_VER"
echo ""

# ---------- 2. 升级 pip ----------
echo "[2/4] 准备安装工具 ..."
python3 -m pip install --upgrade pip --quiet 2>/dev/null
echo "  ✅ 完成"
echo ""

# ---------- 3. 安装 Python 依赖 ----------
echo "[3/4] 安装依赖（playwright / rembg / Pillow / numpy）..."
echo "      首次安装较慢（rembg 含 AI 模型组件），请耐心等待，勿关闭窗口。"
python3 -m pip install --upgrade playwright Pillow numpy "rembg[cpu]"
if [ $? -ne 0 ]; then
    echo "  ⚠️  依赖安装出现问题。常见原因：网络不稳定。可重试一次本脚本。"
    echo ""
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi
echo "  ✅ Python 依赖安装完成"
echo ""

# ---------- 4. 检查 Google Chrome ----------
echo "[4/4] 检查 Google Chrome ..."
if [ -d "/Applications/Google Chrome.app" ]; then
    echo "  ✅ 已安装 Google Chrome"
else
    echo "  ⚠️  未检测到 Google Chrome。"
    echo "     本流程需要用 Chrome 登录 Gemini。"
    echo "     请到 https://www.google.com/chrome/ 下载安装 Chrome 后再使用。"
fi
echo ""

echo "============================================================"
echo "  ✅ 安装完成！现在可以双击「一键运行.command」开始使用。"
echo "============================================================"
echo ""
read -n 1 -s -r -p "按任意键关闭窗口..."
