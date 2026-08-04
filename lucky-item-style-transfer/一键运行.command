#!/bin/bash
# ============================================================
# 幸运物风格迁移 — 一键运行（macOS 双击运行）
# 串联：Step1 生成prompt → Step2 Gemini风格迁移+自动下载+自动抠图
# Step2 完成后成品直接输出到 输出-幸运物/
# 可脱离 AI 对话独立使用；换项目只需把素材文件夹拖进来即可。
# ============================================================

# 切到脚本所在目录（即 Skill 目录）
cd "$(dirname "$0")" || exit 1
SKILL_DIR="$(pwd)"
SCRIPTS="$SKILL_DIR/scripts"

# ---------- 默认项目目录（可选）----------
# 这里不写死任何人的个人路径。想固定一个常用目录，在终端里设一次环境变量即可：
#   export LUCKY_ITEM_ROOT="/你的/素材目录"
DEFAULT_ROOT="${LUCKY_ITEM_ROOT:-}"

echo "============================================================"
echo "  幸运物风格迁移 · 一键运行"
echo "============================================================"
echo ""
echo "项目目录 = 放素材的文件夹，里面应包含："
echo "  · 准备-幸运物截图/      （按明星分子文件夹，文件名就是物品名）"
echo "  · 准备-风格迁移参考图/   （放 1 张风格参考图）"
echo ""
if [ -n "$DEFAULT_ROOT" ]; then
    echo "默认项目目录：$DEFAULT_ROOT"
    echo ""
    echo "👉 直接按 Enter 用默认目录；"
    echo "   或把你的项目文件夹【拖进本窗口】再按 Enter（换项目时这样做）。"
else
    echo "👉 把你的项目文件夹【拖进本窗口】，然后按 Enter。"
    echo "   （没有设置默认目录，这一项必须填）"
fi
echo ""
read -r -p "项目目录: " INPUT_ROOT

# 去掉拖拽路径可能带的引号/空格
INPUT_ROOT="$(echo "$INPUT_ROOT" | sed "s/^['\"]//;s/['\"]$//" | xargs)"
if [ -z "$INPUT_ROOT" ]; then
    ROOT="$DEFAULT_ROOT"
else
    ROOT="$INPUT_ROOT"
fi

if [ -z "$ROOT" ]; then
    echo "❌ 没有指定项目目录，无法继续。请把素材文件夹拖进窗口后重新运行。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

if [ ! -d "$ROOT" ]; then
    echo "❌ 目录不存在：$ROOT"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi
echo ""
echo "✅ 使用项目目录：$ROOT"
echo ""

# ---------- 可选：只处理某个明星/物品 ----------
echo "只想先跑某个明星/物品做验证？输入关键字（如：龚俊）；"
read -r -p "全量跑则直接按 Enter: " FILTER
FILTER="$(echo "$FILTER" | xargs)"
FILTER_ARG=""
if [ -n "$FILTER" ]; then
    FILTER_ARG="--prompt-filter $FILTER"
    echo "  → 仅处理包含「$FILTER」的项"
fi
echo ""

# ============================================================
# Step 1 — 生成 Prompt
# ============================================================
echo "------------------------------------------------------------"
echo "  Step 1 / 2 · 生成 Prompt 文案"
echo "------------------------------------------------------------"
python3 "$SCRIPTS/generate_prompts.py" --root "$ROOT"
if [ $? -ne 0 ]; then
    echo "❌ Step1 失败，请检查上面的提示。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi
echo ""
echo "👀 上面是生成的 prompt 概览。"
read -r -p "确认无误，按 Enter 进入风格迁移；想先改 prompt 就先去改再回来按 Enter..."
echo ""

# ============================================================
# Step 2 — Gemini 风格迁移 + 自动下载 + 自动抠图标准化
# ============================================================
echo "------------------------------------------------------------"
echo "  Step 2 / 2 · Gemini 风格迁移 + 自动抠图"
echo "------------------------------------------------------------"
echo "  首次会让你登录 Gemini（登一次以后免登）。"
echo "  每张图脚本会自动：上传【源图+参考图】→ 填 prompt → 发送 → 下载 → 抠图标准化"
echo "  成品直接输出到 输出-幸运物/"
echo "  如果自动下载失败，会提示你手动保存。"
echo ""
python3 "$SCRIPTS/nano_banana2_transfer.py" --root "$ROOT" $FILTER_ARG
if [ $? -ne 0 ]; then
    echo "⚠️ Step2 未正常结束（可能你中途退出了）。可重新运行继续，已完成的会自动跳过。"
fi
echo ""

echo "============================================================"
echo "  ✅ 全部完成！成品在：$ROOT/输出-幸运物/"
echo "============================================================"
echo ""
echo "💡 如需单独重跑抠图（调参数等），可运行："
echo "   python3 $SCRIPTS/process_image.py --root \"$ROOT\""
echo ""
read -n 1 -s -r -p "按任意键关闭窗口..."
