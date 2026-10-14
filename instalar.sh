#!/usr/bin/env bash
# Copia (no symlink) los agentes a OpenCode y la skill del director a Claude Code.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.config/opencode/agents" "$HOME/.claude/skills/director-opencode"
cp -v "$AQUI"/agents/*.md "$HOME/.config/opencode/agents/"
cp -v "$AQUI"/skills/director-opencode/SKILL.md "$HOME/.claude/skills/director-opencode/SKILL.md"
