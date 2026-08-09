#!/bin/bash
set -e

usage() {
    echo "用法：$0 <skill-name>" >&2
    exit 2
}

[ "$#" -eq 1 ] || usage
skill_name=$1
case "$skill_name" in
    *[!a-z0-9-]*|'')
        echo "skill 名只能包含小写字母、数字和连字符：$skill_name" >&2
        exit 2
        ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
REPO=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
destination="$REPO/$skill_name"

if [ -e "$destination" ] || [ -L "$destination" ]; then
    echo "仓库内已存在同名 skill，请先手动比对：$destination" >&2
    exit 1
fi

source_dir=
for skills_dir in "$HOME/.agents/skills" "$HOME/.codebuddy/skills" "$HOME/.claude/skills"; do
    candidate="$skills_dir/$skill_name"
    if [ -d "$candidate" ] && [ ! -L "$candidate" ] && [ -f "$candidate/SKILL.md" ]; then
        if [ -n "$source_dir" ]; then
            echo "多个 skills 目录里都存在同名实体 skill，请先手动确认：" >&2
            echo "  $source_dir" >&2
            echo "  $candidate" >&2
            exit 1
        fi
        source_dir=$candidate
    fi
done

if [ -z "$source_dir" ]; then
    echo "没有找到包含 SKILL.md 的同名实体 skill：$skill_name" >&2
    exit 1
fi

mkdir "$destination"
rsync -a \
    --exclude '.git' \
    --exclude '.git/' \
    --exclude '.DS_Store' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '*.pyo' \
    "$source_dir/" "$destination/"

skills_dir=$(dirname "$source_dir")
backup_dir="$skills_dir/.ai-image-skills-backups"
backup_path="$backup_dir/$skill_name.bak.$(date +%Y%m%d-%H%M%S).$$"
mkdir -p "$backup_dir"
mv "$source_dir" "$backup_path"
echo "已收纳到仓库：$destination"
echo "原目录已留档：$backup_path"

"$SCRIPT_DIR/link.sh"
