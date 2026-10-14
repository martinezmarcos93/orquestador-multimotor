# Propuestas de implementación

Ideas rescatadas de proyectos similares, convertidas en cambios concretos para este orquestador. Solo ideas: no se copia código ni se instala nada de terceros (varios no tienen licencia, uno es GPL-3.0, y los skills/agentes importados corren con `bash` permitido en modo desatendido).

Estado al 2026-10-14: se amplió el preflight para comprobar el ejecutable inicial del oráculo cuando es inferible; se añadieron timeout por comando de oráculo, bloqueo de worktrees reutilizados sucios, mejoras de concurrencia/trazabilidad de la cola y estado v1 con timestamps/acción siguiente. La tanda nueva de CI está pendiente de confirmación; el entorno real de OpenCode/LiteLLM queda para Claude/Marcos. Cada propuesta es un incremento independiente, con tests y prueba en vivo antes del siguiente.

## Fuentes revisadas

Se leyeron tres archivos por la API de GitHub (solo lectura):

| Archivo | Qué contiene | Qué nos sirve |
|---|---|---|
| `dirigent-skills/skills/verify-done/SKILL.md` (MIT) | Prompt de 1,8 KB: "no declares terminado sin evidencia fresca" | Nada nuevo. Nuestro oráculo ejecutable ya es la versión mecánica. Su señal de alarma "el test pasó a la primera, ¿prueba algo?" es justo lo que mide la mutación |
| `director-cli/director/cost.py` | Ledger JSONL append-only: rol, modelo, tokens, costo, nodo, timestamp; agrupa por rol y modelo | El patrón del registro de uso (propuesta 1) |
| `singular-lite/schemas/state-packet.v0.schema.json` (GPL-3.0) | Paquete de estado por tarea: refs git, archivos propios y cambiados, comandos con código de salida y log, tests por fase, evidencias, bloqueos, próxima acción | Los campos que le faltan a nuestro `estado.json` (propuesta 2). Se reimplementa con nombres propios, sin copiar el archivo |

## Resumen y orden sugerido

| # | Propuesta | Esfuerzo | Impacto | Depende de |
|---|---|---|---|---|
| 0 | `verificar.sh`: chequeo de mantenimiento en un comando | Muy bajo | Alto | nada |
| 1 | Historial y registro de uso (tokens, duración, veredicto) | Bajo | Alto | nada |
| 2 | `estado.json` v1 con `siguiente_accion` y evidencias | Bajo | Alto | 1 |
| 3 | Archivos `inmutables` en el encargo | Muy bajo | Alto | nada |
| 4 | Validador de encargos (`--validar`) | Bajo | Medio | nada |
| 5 | Encadenar encargos (`depende_de`) y ciclo tests → implementar | Medio | Alto | 3 |
| 6 | Presupuesto de tokens con corte en vivo | Medio | Alto | 1 |
| 7 | Vista previa de integración (¿choca con main?) | Muy bajo | Medio | nada |
| 8 | Cola nocturna con systemd | Medio | Medio | 1, 6 |
| 9 | Cooldown de modelos en LiteLLM | Bajo | Medio | verificar primero |

Lo que **no** conviene: daemon con manifiestos YAML y SQLite (contra "simplicidad técnica intencionada"; el repo de referencia está archivado), ejecución nocturna en GitHub Actions (el CI de repos privados está bloqueado por facturación y el código saldría a máquinas de terceros), un agente que mergee (el merge es decisión humana), gateways de modelos de terceros (tus prompts pasarían por intermediarios) e importar colecciones de skills o agentes (cadena de suministro).

---

## 0. `verificar.sh`: el mantenimiento como script, no como skill

**Problema.** Sin CI, nadie corre los tests salvo que se acuerde. Los bugs de esta etapa (`strip()` que comía una letra, stdout vacío de `herdr pane run`) pasaron los tests y aparecieron con trabajo real.

**Implementación.** Un `verificar.sh` en la raíz que corre, en orden y cortando en el primer fallo:
1. `python3 -m unittest discover -s tests` (unos 5 s).
2. Un `--dry-run` del encargo de ejemplo contra un repo temporal (comprueba worktree, enlaces y mensaje, sin gastar cuota).
3. Chequeos de entorno: `opencode` en el PATH, agentes instalados iguales a los del repo (`diff agents/ ~/.config/opencode/agents/`), proxy LiteLLM respondiendo.
4. Opcional `--vivo`: un encargo mínimo real contra un sandbox (cuesta cuota; se corre antes de cambios grandes).

Un hook `pre-push` opcional ejecuta solo el paso 1.

**Aceptación.** Un cambio que rompa el mensaje a OpenCode, o un agente desactualizado, hace fallar `verificar.sh` sin tocar cuota.

## 1. Historial y registro de uso

**Origen.** `cost.py`: ledger append-only que sobrevive entre corridas.

**Dato verificado.** El stream `--format json` de OpenCode trae tokens por paso (`step-finish.tokens`). Una corrida real: 18 pasos, 155.214 tokens de entrada y 2.986 de salida. La entrada crece a cada paso porque se reenvía el contexto: es el costo que importa.

**Implementación.**
- `uso.py` con `resumir_stream(lineas) -> {pasos, entrada, salida, razon_final}` (función pura, testeable con un stream de muestra).
- El despachador lo aplica a `opencode.jsonl` y a `revision.jsonl`, y agrega `uso` al `estado.json`.
- Un `runs/historial.jsonl` append-only con una línea por corrida: fecha, proyecto, id, ronda, agente, veredicto, duración, tokens, puntaje de mutación, hallazgos altos del revisor.
- `historial.py` (CLI) para agrupar por agente o por veredicto: qué agentes fallan más, cuántos tokens cuesta cada tipo de tarea.

**Aceptación.** Después de una cola de 3 encargos, `historial.py --por agente` muestra veredictos y tokens, y los totales coinciden con la suma de los `estado.json`.

**Pendiente de verificar.** Si los eventos indican qué modelo respondió. Si no, el nombre real lo sabe LiteLLM (ver propuesta 9).

## 2. `estado.json` v1

**Origen.** El state packet: referencias git, archivos propios y cambiados, comandos con código de salida y log, tests por fase, evidencias, próxima acción.

**Qué tenemos.** Rama, worktree, archivos, commits, oráculo antes/después (solo booleanos), mutación, revisión.

**Qué falta, con nombres propios:**
- `esquema: "estado.v1"`, `base_sha`, `head_sha`, `permitidos` (los archivos propios del encargo).
- `comandos: [{cmd, codigo_salida, log}]` y `tests: [{fase: "antes"|"despues", ok, log}]`, en vez de booleanos sueltos.
- `evidencias: [{tipo, ref}]` (reporte, revisión, mutación, logs).
- **`siguiente_accion`**: hoy la tabla "veredicto → qué hace el director" vive solo en la skill y en el README. Pasarla a código la deja con una única fuente de verdad, y permite que `cola.py` o un futuro proceso nocturno la lea sin un LLM.
- `inicio` y `fin` en formato ISO.

**Implementación.** Una función pura `armar_estado(...)`, un `schemas/estado.v1.schema.json` propio y un validador mínimo con la librería estándar. Los campos actuales se conservan (no rompe nada).

**Aceptación.** Todo `estado.json` generado valida contra el esquema; un test recorre cada veredicto posible y comprueba que tenga `siguiente_accion`.

## 3. Archivos `inmutables`

**Problema.** "No aflojar asserts" y "no tocar los tests" hoy son una instrucción en el prompt, que un modelo gratuito puede ignorar.

**Implementación.** Un campo opcional `inmutables = ["tests/**"]` en el encargo. El despachador compara esos archivos contra la base: cualquier cambio da el veredicto `viola_inmutables`, igual que `fuera_de_alcance`. Es una variante de `fuera_de_alcance` que ya existe (`fuera_de_alcance()` con otra lista), así que son unas 20 líneas.

**Aceptación.** Un `implementador` que modifica un test existente queda rechazado sin leer el diff.

## 4. Validador de encargos

**Problema.** Los tres primeros intentos de la práctica fallaron por errores del encargo (ruta fuera del worktree, `.venv` inexistente), no del modelo.

**Implementación inicial en la rama de hardening.** `python3 despachar.py ENCARGO.md --validar` comprueba manualmente y la CLI aplica el mismo preflight automáticamente antes de despachar/revisar. Comprueba:
- Tipos y presencia de campos, lista de patrones permitidos relativos sin traversal, lista de comandos de oráculo no vacía, detección de rutas absolutas externas al repo en el cuerpo y ejecutable inicial cuando puede inferirse. Los comandos complejos de shell generan advertencia.
- Rutas de mutación relativas, umbral de mutación entre 0 y 1 y máximo positivo de mutantes.
- Existencia del repositorio Git, resolución de la referencia base y agente instalado en `~/.config/opencode/agents/`.
- Límite total de 30.000 caracteres.
- No crea worktrees, no ejecuta comandos del oráculo y no lanza OpenCode. Si `exige_baseline_verde = true`, informa que la comprobación ocurre durante el despacho.

**Pendiente para completar P4.** Probar encargos históricos representativos y validar con la instalación real; el preflight no puede demostrar la ejecutabilidad de cada etapa dentro de un pipeline o expansión compleja de shell.

**Aceptación.** Cada error de la práctica tiene un test que el validador atrapa; ningún encargo inválido lanza OpenCode.

## 5. Encadenar encargos y ciclo tests → implementar

**Origen.** El planner/ejecutor de `director-cli` (tests de aceptación primero, luego implementación).

**Idea.** El `tester` escribe tests que fallan por la razón correcta; esos tests son el oráculo del `implementador`, que no puede tocarlos (propuesta 3).

**Implementación.**
- Campo `depende_de = ["001"]`: `cola.py` ordena por dependencia y fija la `base` del encargo B a la rama del A. Ya existe `base` configurable, así que es planificación.
- Un encargo B con `inmutables = ["tests/**"]` y `permitidos = ["src/**"]`.
- Un campo `espera_rojo = true` en A: el oráculo "antes" debe fallar (tests nuevos) y "después" debe fallar solo en los tests nuevos, para no aceptar tests que ya pasan sin código.

**Aceptación.** Ejemplo real en el sandbox: el `tester` escribe tests de una función nueva, el `implementador` la escribe, y el oráculo pasa sin que el segundo haya modificado un test.

## 6. Presupuesto de tokens con corte en vivo

**Hueco real.** Hoy el único límite es `timeout_min`.

**Implementación.** Campo `presupuesto_tokens = 400000` (entrada). El despachador deja de redirigir stdout a un archivo y lo lee en vivo con `Popen`, sumando `step-finish.tokens`; si se supera, termina el proceso y da el veredicto `presupuesto_agotado` (el trabajo hecho hasta ahí se conserva para evaluarlo). Con la propuesta 1, el presupuesto por defecto sale del historial (percentil 90 de tareas similares).

**Aceptación.** Un trabajador de prueba con presupuesto bajo se corta con el veredicto correcto y el estado queda consistente.

## 7. Vista previa de integración

**Origen.** Disciplina de "merge-conflict safety" de `dirigent-skills`, sin el agente que mergea.

**Implementación.** Al terminar con `pasa`, `git merge-tree --write-tree base rama` (solo lectura) y se guarda `integracion: {conflictos: [archivos]}` en el estado. El merge sigue siendo tuyo; llegás sabiendo si va a chocar. En la práctica real los tres `REPORTE.md` chocaron: esto lo habría avisado.

## 8. Cola nocturna con systemd

**Tu modelo.** "OpenCode corre desatendido hasta agotar su cuota y Claude revisa después en lote."

**Implementación.** `cola.py --carpeta _encargos/<proyecto>/pendientes --hasta-cuota` mueve cada encargo a `en-curso/` y después a `listos/` o `fallidos/`, y se detiene sola con la regla de corte por fallos de infraestructura que ya existe. Un servicio de usuario con timer (systemd, como pide tu convención) la dispara de noche. Al despertar, Claude lee `historial.jsonl` y `siguiente_accion` de cada encargo y revisa en lote.

**Depende de** 1 y 6, para no gastar la cuota de golpe y saber qué pasó.

## 9. Cooldown de modelos fallidos

**Problema.** Un modelo gratuito que da timeouts o respuestas vacías sigue entrando en la cadena.

**Antes de agregar un gateway nuevo, verificar si LiteLLM ya lo resuelve.** Suele traer configuración de reintentos, fallos permitidos y enfriamiento por modelo (`router_settings`); hay que confirmar los nombres exactos en la versión instalada y probarlo con un modelo caído a propósito. Si alcanza, es solo configuración y no suma ninguna dependencia ni intermediario.

---

## ¿Hace falta una flota de skills para mantener esto funcionando?

**No.** Lo que mantiene el proyecto en pie son el código y los tests (64, corren en 5 s), y las instrucciones de cada trabajador (`agents/*.md`). Los bugs reales de esta etapa los encontraron el oráculo y el uso real, no la falta de un skill.

Un skill es un documento que el modelo carga en su contexto. Cada uno que se suma cuesta contexto y es otro texto que puede ser ambiguo, quedar desactualizado o (si viene de terceros) llevar instrucciones ajenas con acceso a una shell.

Lo mínimo útil:

| Pieza | Para qué | Dónde |
|---|---|---|
| `director-opencode` | El ciclo del director (ya existe) | Claude |
| `delegacion-opencode` | Reglas de obediencia del trabajador (ya existe) | OpenCode |
| `verificar.sh` (propuesta 0) | Mantenimiento: comprobar que todo sigue andando | Script |
| `agents/*.md` | Una definición por rol | OpenCode |

Regla práctica: si algo se puede comprobar con un comando que devuelve éxito o error, va en un script con tests, no en un skill. Un skill se justifica solo para criterio humano (cuándo delegar, cómo escribir el feedback), y eso ya lo cubre `director-opencode`.
