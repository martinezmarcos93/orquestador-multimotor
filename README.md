# orquestador-opencode

Claude Code dirige y OpenCode obedece. Claude escribe un **encargo**; el despachador lo ejecuta en OpenCode sin pantalla,
verifica el resultado con el oráculo y deja un veredicto en `runs/<proyecto>-<id>/ronda-N/estado.json`.
Claude lee ese veredicto, revisa y decide: integrar, escribir un encargo nuevo con feedback, o tomarlo él.
Comunicación solo por archivos: nada de controlar terminales en vivo. Stack: Python 3.11+ (solo librería estándar), `opencode`, `git`.

## Uso
```
./instalar.sh                          # copia agentes a ~/.config/opencode/agents y la skill a ~/.claude/skills
python3 despachar.py ENCARGO.md        # ejecuta (usar run_in_background desde Claude)
python3 despachar.py ENCARGO.md --dry-run   # prepara el worktree, muestra el mensaje, no gasta cuota
python3 -m unittest discover -s tests
```
El encargo empieza con un bloque `+++ ... +++` (TOML): `id, proyecto, repo, agente, tema, permitidos, oraculo` (+ `base`, `timeout_min`).
Ejemplo y ciclo completo: `skills/director-opencode/SKILL.md`.

## Veredictos (`resultado`)
`pasa` · `falla_oraculo` · `sin_cambios` · `trabajo_sin_commitear` · `fuera_de_alcance` · `dependencia_nueva` · `posible_secreto` · `timeout` · `error_opencode` · `tope_rondas` (2 rondas por encargo; la tercera la toma Claude).

## Lecciones de la primera práctica (2026-10-13, `mercado-sandbox`, agente `tester`)
1. **OpenCode desatendido rechaza leer fuera del worktree** (`external_directory ... auto-rejecting`) y se detiene en silencio. Por eso el encargo va *incrustado* en el mensaje y la ruta del repo original se reescribe por la del worktree.
2. **Un worktree no trae `.venv`/`node_modules`** (están en `.gitignore`): el despachador los enlaza y los excluye de git.
3. **`git status` colapsa carpetas nuevas** (`docs/`): usar `-uall` o el alcance da falsos positivos.
4. **No fiarse del "listo" ni de los "bugs encontrados" del trabajador.** El modelo gratuito afirmó asserts que contradecían su propia aritmética y los llamó bugs del código. Sirvió la regla de la ronda de feedback con la regla de negocio explícita.
5. **Prueba de mutación manual como compuerta de calidad de tests**: 13 mutaciones sobre una copia temporal; 2 sobrevivieron (bordes de RSI con casos de 4 puntos que no distinguen `<` de `<=`). Los tests "verdes" no bastan.
6. Un `--dry-run` no debe consumir rondas; solo cuentan las corridas que lanzaron OpenCode.

## Pendiente
Trabajadores `higiene` y `revisor`; paralelismo 2-3 con cola; automatizar la mutación como paso del despachador; integración con Herdr como visor.
