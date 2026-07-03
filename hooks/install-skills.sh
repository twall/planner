#!/usr/bin/env bash
# Symlink planner skills into ~/.claude/commands/ so they're available as /planner-* slash commands
COMMANDS_DIR="${HOME}/.claude/commands"
SKILLS_DIR="${CLAUDE_PLUGIN_ROOT}/skills"
mkdir -p "$COMMANDS_DIR"
for skill in "$SKILLS_DIR"/*.md; do
    name="$(basename "$skill")"
    link="$COMMANDS_DIR/$name"
    if [ ! -e "$link" ]; then
        ln -s "$skill" "$link"
    fi
done
