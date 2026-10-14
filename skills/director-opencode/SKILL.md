---
name: director-opencode
description: Claude como DIRECTOR de trabajadores OpenCode. Redactar encargos con bloque de configuración, lanzar el despachador en segundo plano, leer el veredicto y decidir (integrar, dar una orden nueva o tomarlo). Usar cuando Marcos pida delegar, orquestar, "que opencode haga X", "mandá a los trabajadores" o revisar lo que devolvió OpenCode. Complementa a delegacion-opencode.
---

# Director de OpenCode

Vos dirigís; los trabajadores obedecen. **Nunca controlás una terminal en vivo**: te comunicás por archivos.
Reglas de calibre y de obediencia: `delegacion-opencode` y `_metodologias/claude-code/calibre-y-delegacion.md` (A y B-sensible no se delegan).

## Trabajadores (agentes de OpenCode, `~/.config/opencode/agents/`)
- `tester`: solo escribe tests; no puede editar fuera de `tests/`/`test/`.
- `implementador`: una tarea acotada dentro de los archivos permitidos.

## Ciclo
1. **Elegí** proyecto (nivel C o D), trabajador y una tarea chica (los modelos gratuitos se pierden con contexto largo). Si no es git en ext4, se prepara primero un sandbox.
2. **Redactá** `_encargos/<proyecto>/NNN-tema.md` (vault de proyectos) con la plantilla `plantilla-encargo.md`, empezando por el bloque de configuración:
   ```
   +++
   id = "001"
   proyecto = "mercado-sandbox"
   repo = "/home/marcos/src/mercado-sandbox"
   agente = "tester"
   tema = "tests-nucleo"
   base = "main"
   permitidos = ["tests/**"]
   oraculo = [".venv/bin/python -m pytest -q"]
   timeout_min = 20
   +++
   ```
   El oráculo corre dentro del worktree, antes y después. El despachador enlaza `.venv`/`node_modules` del repo en el worktree, así que usá rutas **relativas**. Si el encargo menciona la ruta del repo original, el despachador la reescribe por la del worktree; el trabajador nunca puede leer fuera de él (OpenCode desatendido lo rechaza y se detiene).
3. **Lanzá** en segundo plano: `python3 ~/src/orquestador-opencode/despachar.py <encargo>` con `run_in_background`. Al terminar te reactivás solo: no hagas polling. `--dry-run` prepara el worktree sin gastar cuota.
4. **Leé en orden de costo:** JSON de `resultado` → `runs/<proyecto>-<id>/ronda-N/estado.json` → `REPORTE.md` → `git diff --stat` → diff completo. No confíes en el "listo": corré el oráculo vos.
5. **Decidí** según `resultado`:
   - `pasa`: revisá el diff y proponele a Marcos integrar. El merge a main es suyo. **Si son tests, hacé prueba de mutación** (ver abajo) antes de dar por buena la calidad.
   - `falla_oraculo`, `sin_cambios`, `trabajo_sin_commitear` (a veces es menor: documentos sueltos; commitealos vos): orden nueva (mismo `id`, misma `tema`, reutiliza el worktree) con el **feedback concreto** en el cuerpo del encargo. Cada `id` admite 2 rondas.
   - `fuera_de_alcance`, `dependencia_nueva`, `posible_secreto`: no leas el diff; descartá la rama o devolvela con la regla violada.
   - `timeout`, `error_opencode`: mirá `opencode.err`; probablemente cuota o proxy (`systemctl --user status litellm-opencode`).
   - `tope_rondas`: lo tomás vos.
6. **Bitácora:** anotá qué se delegó, qué se integró y qué se rechazó, con el motivo.

## Reglas
- Paralelismo máximo 2-3 trabajadores (comparten cuota gratuita). Un worktree por tema.
- Una tanda = un tema. Las tareas ambiguas las resolvés vos antes de delegar.
- Nada con secretos ni datos de terceros sale a modelos gratuitos.

## Prueba de mutación manual (para encargos de tests)
Copiá el código a un directorio temporal, cambiá una condición o constante (`<` por `<=`, un umbral, un peso, el orden) y corré los tests: tienen que fallar.
Aplicá la mutación en la función correcta (reemplazar "la primera coincidencia" puede caer en otra función). Los que sobreviven revelan bordes que el trabajador "probó" con casos que no distinguen.
No te fíes de los "bugs encontrados" del trabajador: contá vos la regla de negocio y contrastá con el código antes de aceptar un reporte de bug.
