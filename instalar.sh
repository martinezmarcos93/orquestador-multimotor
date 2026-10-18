#!/usr/bin/env bash
# Copia (no symlink) los agentes a OpenCode y la skill del director a Claude Code.
set -euo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.config/opencode/agents" "$HOME/.claude/skills/director-opencode"
cp -v "$AQUI"/agents/*.md "$HOME/.config/opencode/agents/"
# La skill lleva el marcador @@ORQUESTADOR@@; se reemplaza por la ruta real del repo.
sed "s#@@ORQUESTADOR@@#$AQUI#g" "$AQUI"/skills/director-opencode/SKILL.md > "$HOME/.claude/skills/director-opencode/SKILL.md"
echo "skill -> $HOME/.claude/skills/director-opencode/SKILL.md"
