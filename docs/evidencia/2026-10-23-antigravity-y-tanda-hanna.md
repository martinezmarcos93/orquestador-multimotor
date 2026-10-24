# Evidencia — Antigravity en modo desatendido y tanda Hanna (23/10/2026)

Primera tanda real con los tres motores: 12 encargos sobre un clon de Hanna sin datos personales (`cola.py --max 3`). Resultado final: Codex y OpenCode entregaron todo; **Antigravity no produjo ningún cambio** y sus 4 encargos se reasignaron a Codex.

## 1. Antigravity CLI: qué funciona y qué no

| Comprobación | Resultado |
|---|---|
| Ejecutable y versión | `agy` 1.4.5 en `~/.local/bin/agy` |
| Autenticación | Aprobada |
| Contrato JSON (petición inocua del paso 3 de la validación) | `status: SUCCESS`, `response` no vacío. Campos observados: `conversation_id`, `status`, `response`, `duration_seconds`, `num_turns`, `usage` (`input_tokens`, `output_tokens`, `thinking_tokens`, `cache_read_tokens`, `total_tokens`) y, cuando corresponde, `denied_actions` |
| Sandbox (paso 4) | **No verificado** |
| Encargo real a través del adaptador | **Fallido**: no puede ejecutar comandos ni editar archivos |

### El bloqueo: permisos en modo `--print`

En modo desatendido, Antigravity **deniega automáticamente** toda herramienta que normalmente pediría confirmación. Lo que se observó:

- **Ronda 1** (encargo normal): la primera acción fue un comando (`git`/tests) → `denied_actions: [{"action": "command", "display_name": "RunCommand"}]`. `agy.err`: *"a tool required the "command" permission that headless mode cannot prompt for, so it was auto-denied. Add an allow-rule under permissions.allow in settings.json (e.g. command(<target>))"*.
- **Ronda 2** (encargo reescrito para trabajar solo leyendo y editando archivos): `denied_actions: [{"action": "write_file", "display_name": "EditFile"}]`. Consumió unos 79k tokens de entrada y 34k de salida (28k de razonamiento) y no escribió nada.
- En ambos casos `agy` devuelve **`status: SUCCESS` con `response` vacío** y código de salida 0. Un proceso en 0 no basta: el adaptador lo marca correctamente como `INVALID_OUTPUT` ("agy indicó SUCCESS pero no devolvió response textual").

### Opciones (decisión pendiente de Marcos)

1. **Reglas de permiso acotadas** en `~/.gemini/antigravity-cli/settings.json` (`permissions.allow`, p. ej. `command(git)`, `command(.venv/bin/python)`, `write_file(<ruta del worktree>)`). Es una configuración **del host**: afecta a todo uso de `agy`, no solo al orquestador. Claude no la aplica por su cuenta; el clasificador de seguridad de Claude Code bloqueó el intento, con razón.
2. **`--dangerously-skip-permissions`**: descartado por el procedimiento de validación del host.
3. **Usar Antigravity solo para tareas de lectura** (análisis o revisión) cuyo producto sea la respuesta textual, sin editar archivos.
4. **No usarlo** hasta que exista una forma de acotar permisos por directorio de trabajo.

Hasta decidir, Antigravity **no sirve como motor de escritura desatendido**.

## 2. Bugs e incidentes del orquestador en la tanda

| # | Incidente | Estado |
|---|---|---|
| 1 | Todo veredicto de Antigravity terminaba en `error_estado_invalido`: `schemas/estado.v1.schema.json` no tenía `antigravity` en el enum de `motor` | **Corregido** (enum + test de regresión) |
| 2 | Tras un error de Antigravity, la siguiente ejecución del mismo `id` volvió a registrarse como «ronda 1» en el mismo directorio y pisó la evidencia anterior | **Corregido**: cada intento toma el siguiente `ronda-N`; los errores de motor/entorno dejan evidencia sin consumir el tope de dos rondas de trabajo |
| 3 | Integrar en la rama `base` entregas aprobadas mientras otros encargos esperan su ronda 2 provoca `worktree_base_divergente` | Mitigado: fijar `base` en una rama inmóvil (p. ej. `base/<tanda>`) y acumular lo aprobado en otra rama |
| 4 | Codex no puede escribir el índice git del worktree (`.git/worktrees/...` queda fuera de su sandbox, *Read-only file system*). El auto-commit del despachador no incluye archivos ignorados (Hanna ignora `docs/`): un documento nuevo quedó sin commitear y lo commiteó el director | **Corregido**: rutas exactas permitidas se agregan con `git add -f`; los ignorados que solo coinciden con comodines quedan listados en `ignorados_sin_commitear` y producen `trabajo_sin_commitear` |
| 5 | El sandbox de Codex no ve el `.venv` enlazado, así que el worker corre los tests con el Python del sistema y reporta «faltan dependencias». El oráculo del despachador sí pasa | Abierto: documentado; el oráculo manda |
| 6 | OpenCode cargó la skill y terminó con 0 tokens de salida (`sin_cambios`); en el reintento dejó el trabajo sin commitear | Abierto: inestabilidad del modelo gratuito |
| 7 | OpenCode commiteó en una rama con otro nombre (`gui-saludo-neuronas` en vez de `gui-bitacora`); el despachador evaluó el HEAD del worktree correctamente | Abierto: el despachador podría rechazar o advertir un cambio de rama |

## 3. Balance de la tanda

- **Codex:** 10 encargos (6 propios y 4 reasignados de Antigravity). Todos pasaron; 5 necesitaron una segunda ronda por hallazgos de la revisión del director.
- **OpenCode:** 2 encargos. Uno pasó; el otro agotó sus rondas y lo terminó el director.
- **Antigravity:** 4 encargos, 0 cambios.
- Lo aprobado se integró en `main` de Hanna con la autorización de Marcos.
