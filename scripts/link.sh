#!/bin/bash
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
REPO=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd -P)
STAMP=$(date +%Y%m%d-%H%M%S)

link_into() {
    skills_dir=$1
    backup_dir="$skills_dir/.ai-image-skills-backups"

    echo "处理 skill 目录：$skills_dir"

    find "$skills_dir" -mindepth 1 -maxdepth 1 -type l -print | while IFS= read -r link_path; do
        link_target=$(readlink "$link_path" || true)
        case "$link_target" in
            "$REPO"/*)
                if [ ! -e "$link_path" ]; then
                    rm "$link_path"
                    echo "  已清理死链：$(basename "$link_path")"
                fi
                ;;
        esac
    done

    for skill_md in "$REPO"/*/SKILL.md; do
        [ -f "$skill_md" ] || continue
        skill_dir=$(dirname "$skill_md")
        skill_name=$(basename "$skill_dir")
        destination="$skills_dir/$skill_name"

        if [ -L "$destination" ]; then
            current_target=$(readlink "$destination" || true)
            if [ "$current_target" = "$skill_dir" ]; then
                echo "  已存在正确链接：$skill_name"
            else
                echo "  跳过指向其他位置的链接：$destination -> $current_target" >&2
            fi
            continue
        fi

        if [ -e "$destination" ]; then
            mkdir -p "$backup_dir"
            backup_path="$backup_dir/$skill_name.bak.$STAMP.$$"
            mv "$destination" "$backup_path"
            echo "  已备份原实体目录：$backup_path"
        fi

        ln -s "$skill_dir" "$destination"
        echo "  已建立链接：$destination -> $skill_dir"
    done
}

found=0
for skills_dir in "$HOME/.agents/skills" "$HOME/.codebuddy/skills" "$HOME/.claude/skills"; do
    if [ -d "$skills_dir" ]; then
        found=1
        link_into "$skills_dir"
    fi
done

if [ "$found" -eq 0 ]; then
    echo "未找到可用的 skills 目录；请先创建平台对应的用户级 skills 目录。" >&2
    exit 1
fi
