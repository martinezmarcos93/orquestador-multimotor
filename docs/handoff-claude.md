# Handoff para Claude — barrido del orquestador

Fecha: 2026-10-14  
Repositorio: `martinezmarcos93/orquestador-opencode`  
Rama única de trabajo: `docs/roadmap-hardening`  
PR: https://github.com/martinezmarcos93/orquestador-opencode/pull/1  
Base `main` conocida antes del barrido: `e183a3328cc7ef0194556b32064d594769ecfc51`

## Reglas de trabajo

- No fusionar ni modificar `main` sin autorización explícita de Marcos.
- Mantener esta rama temporal única; no crear ramas auxiliares.
- No declarar integración real probada si no se ejecutó OpenCode/LiteLLM en el equipo anfitrión.
- Registrar evidencia concreta, comandos, resultados y limitaciones en el roadmap.
- Antes de reescribir historia o consolidar commits, comprobar la punta de la rama y conservar todos los cambios.

## Cambios implementados en el barrido

1. **Preflight P4:** `despachar.py ENCARGO.md --validar`; compuerta automática antes del despacho y revisión; valida tipos, rutas/patrones, base Git, agentes, límite del encargo, requisito de baseline para `higiene`, rutas absolutas externas y ejecutable inicial de comandos cuando es inferible. Las construcciones complejas de shell quedan como advertencia, no como verificación garantizada.
2. **Timeouts:** OpenCode, revisor y oráculos se ejecutan en grupos de procesos propios; se termina el grupo con SIGTERM y se escala a SIGKILL. `mutacion.py` aplica la misma política a sus oráculos.
3. **Worktrees:** un worktree reutilizado con cambios sin commitear se bloquea antes de ejecutar oráculo/modelo; la revisión también rechaza un worktree sucio.
4. **Cola:** compara rutas de repo normalizadas antes de paralelizar, incluye excepciones del runner en el corte de fallos, limita `--max` a 1–3, evita colisiones de nombre en resúmenes y conserva diagnósticos.
5. **Mutación:** una excepción, error de evaluación o ausencia de candidatos no puede terminar como `pasa`; devuelve `error_mutacion` o `mutacion_sin_candidatos`.
6. **Estado:** `estado.json` incorpora `schema_version = 1`, timestamps UTC, `siguiente_accion` y su propia ruta; `schemas/estado.v1.schema.json` define el contrato mínimo y la CLI lo valida antes de persistir.
7. **Validación/documentación:** pruebas para CRLF, comandos de oráculo inexistentes, procesos descendientes, worktree sucio, rutas equivalentes, errores consecutivos, estado v1 y mutación; README, roadmap y revisión arquitectónica actualizados.

## Validación

GitHub Actions run #227 sobre el commit consolidado `eda41d6e1918070159598733efdcf6ba485d15fb`: **122 tests aprobados**, `bash verificar.sh` completado. No equivale a pruebas locales ni de integración real.

Link de ejecución reciente a revisar: https://github.com/martinezmarcos93/orquestador-opencode/actions

## Trabajo que requiere el equipo anfitrión / Claude

### Bloqueantes de aceptación

- Ejecutar `bash verificar.sh` y `python3 -m unittest discover -s tests` en la máquina de Marcos, y registrar la salida real.
- Ejecutar un encargo inocuo con OpenCode real y LiteLLM: comprobar JSONL, código de salida, resultado del revisor, archivos creados y estado persistido.
- Inspeccionar un `estado.json` de una corrida que realmente ejecute al trabajador (no solo dry-run/baseline rojo).
- Ejecutar `cola.py` completa, incluyendo timeout exterior, corte por fallos consecutivos, diagnóstico y recuperación ante interrupción.
- Probar `--validar` contra los agentes instalados, los oráculos y varios encargos históricos representativos.
- Diseñar y probar un sandbox real de sistema operativo con mounts y variables explícitos. Un worktree NO es un sandbox; no afirmar aislamiento fuerte.
- Confirmar que los timeouts no dejan procesos descendientes y que el proxy/configuración de LiteLLM sigue funcionando tras el confinamiento.

### Mejoras que siguen en roadmap

- Completar `estado.json` v1 con validación completa de JSON Schema, fases/evidencias normalizadas y acciones para todos los veredictos.
- Historial append-only de corridas y consumo/tokens sin inventar datos ausentes.
- Patrones `inmutables` para proteger tests/archivos; rechazar cambios, borrados y renombres protegidos.
- Contrato de mutación más explícito: universo completo/truncado, cero candidatos, error de oráculo, mutantes sobrevivientes y posibles equivalentes; no interpretar el puntaje como calidad general.
- Vista previa de integración de solo lectura con `git merge-tree`.
- Encargos dependientes y flujo tester → implementador, con pruebas protegidas.
- Presupuesto de tokens en vivo, cola nocturna y cooldown de modelos solo después de verificar si LiteLLM ya resuelve el problema.
- Revisar falsos positivos/negativos de secretos, rutas y dependencias con diffs reales.

## Criterio para cerrar la PR

No cerrar por cantidad de tests solamente. Cerrar los criterios de aceptación con evidencia de CI y del equipo anfitrión, actualizar el roadmap y pedir revisión humana de los riesgos de seguridad. La PR debe seguir abierta hasta autorización explícita de Marcos para integrar.
