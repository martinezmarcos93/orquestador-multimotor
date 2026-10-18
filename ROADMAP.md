# Roadmap

Detalle, decisiones de diseño y criterios de aceptación en [`docs/propuestas.md`](docs/propuestas.md). Los riesgos concretos y la priorización conciliada de la revisión están en [`docs/revision-arquitectonica.md`](docs/revision-arquitectonica.md).

**Método de trabajo:** un incremento por vez; rama temporal única; tests automatizados y prueba en vivo cuando sea posible; documentar evidencia, bloqueos y lo que no pudo ejecutarse. `main` es la fuente de verdad y no se modifica durante esta etapa. No marcar un ítem como hecho por haber escrito el código: debe cumplir su criterio de aceptación. No integrar ni fusionar sin autorización explícita de Marcos.

## Requisito rector: autonomía supervisada

El objetivo operativo es reducir al mínimo la intervención de Marcos sin ampliar permisos de forma indiscriminada. Claude debe poder dirigir el ciclo de trabajo y resolver operaciones rutinarias dentro de una política explícita; las acciones fuera de alcance se deniegan por defecto. Este repositorio ahora incluye un modo optativo `motor = "codex"` que lanza Codex CLI con `--sandbox workspace-write --ask-for-approval never`; evita prompts interactivos y deja que el sandbox bloquee operaciones fuera de su alcance. No controla una sesión abierta manualmente en Codex Desktop/IDE ni aprueba acciones fuera del sandbox; esa vía debe ejecutarse mediante el despachador para beneficiarse de esta política.

Orden de implementación: controles preventivos y preview → trazabilidad y estados → contratos/dependencias de tareas → política de permisos y recuperación → aislamiento de sistema operativo → presupuesto/cooldown → cola desatendida. La autonomía nocturna queda bloqueada hasta demostrar aislamiento y recuperación ante interrupciones.

## Hecho (2026-10-13; según documentación existente)

- [x] Despachador de encargos con límite de rondas.
- [x] Agentes `tester`, `implementador`, `higiene`, `revisor` y skill `director-opencode`.
- [x] Prueba de mutación y veredicto `tests_debiles`.
- [x] Cola con paralelismo limitado y candado por proyecto.
- [x] Visor opcional en Herdr, `--reevaluar` y `--revisar-solo`.
- [x] Pruebas unitarias documentadas para el núcleo.

> Las casillas anteriores reflejan la documentación y pruebas registradas en el repositorio; no equivalen a una ejecución nueva en este cambio.

## Fase 0 — Integridad de la ejecución y límites de seguridad

Prioridad transversal: abordar antes de ampliar la autonomía.

- [ ] **S0.1 Base Git inmutable por corrida.** Implementación parcial en esta rama: `despachar.py` registra `base_ref`, `base_sha`, `head_sha_inicio`, `head_sha_fin`, `base_sha_actual_fin` y `base_movida`; crea worktrees nuevos desde el SHA fijado y rechaza worktrees reutilizados con rama o repositorio inesperados, además de detectar una base que ya no sea ancestro del worktree. Se agregaron pruebas para avance de la rama destino antes de crear el worktree y durante el trabajo. GitHub Actions run #60 aprobó 97 tests, incluida una prueba de `--dry-run` desde CLI que comprueba que no se invoca OpenCode ni se ejecuta el oráculo. También se verifica la persistencia de `estado.json` y los snapshots de una salida temprana `baseline_rojo`.
  - Aceptación pendiente: inspeccionar el `estado.json` de una corrida real que ejecute un trabajador; el `dry-run` no cubre ese camino.
- [ ] **S0.2 Aislamiento efectivo del trabajador.** Avance parcial: los symlinks a `.venv`/`node_modules` quedaron deshabilitados por defecto; solo se crean con `permitir_entornos_compartidos = true`, y el estado registra esa decisión. El README ya distingue worktree de sandbox. Esto reduce exposición accidental, pero no aísla el proceso de archivos externos ni limpia variables de entorno heredadas.
  - Aceptación pendiente: definir y probar un sandbox de SO compatible con OpenCode y el proxy configurado; medir acceso a home/config/credenciales, red, rutas fuera del worktree y escritura sobre el repo original. No afirmar aislamiento fuerte hasta esa prueba.
- [ ] **S0.3 Veredicto estricto y revisión obligatoria.** Implementación parcial en esta rama: `despachar.py` valida las secciones, el veredicto y el formato/evidencia de hallazgos; trata timeout, salida no cero, respuesta vacía y worktree modificado como errores; separa `resultado` técnico de `aprobacion`. `cola.py` ya no devuelve éxito cuando la revisión bloquea. Se añadieron tests del proceso de revisión con OpenCode simulado para timeout, código no cero, salida vacía y mutación del worktree; GitHub Actions run #60 aprobó 97 tests.
  - Aceptación pendiente: probar con OpenCode real el formato de salida y un veredicto con hallazgo ALTA.
- [ ] **S0.4 Robustez de procesos y cola.** La cola impone timeout exterior y termina grupos con SIGTERM/SIGKILL. En este barrido, OpenCode, el revisor y cada comando de oráculo se ejecutan con timeout y terminación de grupo/descendientes. La cola normaliza rutas equivalentes al detectar conflictos, trata excepciones del runner como fallos de infraestructura, valida `--max` y conserva diagnóstico/error en el resumen. Se añadieron tests para timeout real de procesos, worktree sucio y fallos consecutivos. GitHub Actions run #227 aprobó 122 tests para el código de esta tanda; las pruebas reales de integración siguen pendientes.
  - Aceptación pendiente: probar una corrida real de cola que alcance el timeout exterior y revisar la recuperación ante interrupciones; el timeout de OpenCode directo todavía requiere validación de integración.
- [ ] **S0.5 Endurecer controles de alcance y secretos.** Implementación parcial en esta rama: el detector cubre más formatos de tokens y asignaciones de credenciales, incluso claves JSON, y la lista de dependencias reconoce manifiestos/lockfiles comunes de Python, Node, Rust, Go, Ruby, PHP, JVM, Swift y Dart. Las pruebas sintéticas de secretos y dependencias pasan en GitHub Actions run #60. Son filtros heurísticos, no garantía de ausencia de secretos ni catálogo exhaustivo.
  - Aceptación pendiente: revisar falsos positivos/negativos y documentar excepciones por ecosistema.

- [ ] **S0.6 Codex CLI sin prompts rutinarios.** Implementación inicial: `motor = "codex"` invoca `codex exec --approve-for-me --json -`, inyecta las instrucciones del rol local y aplica timeout con terminación del grupo. Los overrides fijan `sandbox_workspace_write.writable_roots=[]` y `network_access=false`; las aprobaciones se someten a la revisión automática de Codex dentro de `workspace-write`. El modo es optativo; OpenCode sigue siendo el predeterminado. Se rechaza `presupuesto_tokens` en Codex hasta implementar un parser de su stream de uso. GitHub Actions run [#398](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39078431122) aprobó 163 tests.
  - Aceptación pendiente: probar con Codex CLI instalado en el equipo anfitrión que edita y ejecuta tests dentro del worktree sin pedir aprobación, y que una acción fuera del sandbox falla sin prompt. No es una aprobación delegada literalmente a Claude y no afecta sesiones de Codex Desktop/IDE abiertas manualmente; Claude revisa el resultado final y el sandbox debe denegar acciones fuera de su alcance.

## Fase 1 — Mantenimiento reproducible y trazabilidad básica

- [x] **P0 `verificar.sh`** *(aceptado en host 2026-10-17: `--installed` y `--tools` OK).* Implementación parcial en esta rama: modo básico compila Python, valida sintaxis shell, ejecuta `--help` y la suite sin modelos ni red; `--installed` compara agentes/skill instalados y `--tools` comprueba binarios. Se agregó GitHub Actions para ejecutar la verificación en PR/push. GitHub Actions run #60 completó `bash verificar.sh` con éxito (97 tests). La prueba CLI de `--dry-run` usa un binario OpenCode falso que deja una marca si se ejecuta; la marca no aparece y no se consume cuota.
  - Aceptación pendiente: ejecutar un `--dry-run` con un encargo real en el equipo anfitrión para confirmar rutas y permisos locales.
- [x] **P1 Historial y registro de uso** *(aceptado 2026-10-17: cola real de 3 encargos; el ledger de esa cola, 230 774 tokens de entrada, coincide exacto con la suma de sus `estado.json`).* Implementación inicial: `uso.py` suma tokens de eventos `step-finish` en JSONL y marca campos ausentes como desconocidos; `historial.py` anexa registros compactos con bloqueo/fsync y agrupa por agente, resultado o proyecto. `despachar.py` incorpora uso del trabajador/revisor al estado y registra cada invocación sin guardar prompts ni diffs. CI run [#298](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39077280761) aprobó 141 tests, incluidos fixtures sintéticos del parser y ledger.
  - Aceptación pendiente: una cola real de tres encargos debe cuadrar con sus `estado.json`; confirmar el formato del stream OpenCode/LiteLLM instalado y que los campos disponibles coincidan con el parser. No se inventan valores cuando faltan eventos.
- [x] **P3 Archivos inmutables.** `inmutables` es opcional, valida patrones relativos y genera `viola_inmutables` si una ruta cambiada coincide; `git diff --no-renames` detecta origen/destino de renombres. Una violación bloquea la aprobación y omite oráculo/mutación para evitar efectos secundarios de pruebas. GitHub Actions run [#370](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39078076954): 158 tests aprobados, incluidos patrones inválidos, traversal, borrado/renombre y prioridad del veredicto. La integración real con un worker sigue pendiente.
- [ ] **S1.1 Contrato de mutación y lectura de resultados.** Avance parcial: la evaluación de mutación que devuelve error o cero candidatos ya no puede acabar en `pasa`; se distinguen `error_mutacion` y `mutacion_sin_candidatos`. Sigue pendiente mostrar con claridad universo completo/truncado, mutación equivalente probable y límites de interpretación del puntaje.
  - Aceptación: pruebas de universo truncado, cero candidatos y oráculo que falla; no presentar el puntaje como porcentaje general de calidad.

## Fase 2 — Estado estructurado y validación preventiva

- [ ] **P2 `estado.json` v1.** Implementación ampliada: el esquema documenta metadatos Git, resultados del oráculo, duración, uso de tokens, mutación, revisión e integración previa. `validar_estado_v1` valida contra las propiedades declaradas, incluyendo tipos (sin aceptar booleanos como enteros), `const`, `enum`, rangos, longitud, patrones, fechas con zona horaria, `required`, `properties` e `items`. Se permiten campos adicionales por compatibilidad; es un validador del subconjunto usado por este esquema, no un motor JSON Schema completo. CI run [#298](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39077280761) aprobó 141 tests, incluidos controles de restricciones anidadas.
  - Aceptación pendiente: cubrir todos los veredictos/retornos tempranos con estados persistidos y verificar una corrida real de OpenCode; decidir si hace falta adoptar una implementación completa de JSON Schema.
- [ ] **P4 Validador de encargos (`--validar`).** Comprueba tipos, patrones relativos sin traversal, mutación, repo/base, agentes requeridos, rutas absolutas externas en el cuerpo, límite de 30.000 caracteres y el ejecutable inicial de cada comando cuando puede inferirse. La CLI aplica el preflight antes del despacho/revisión; no crea worktree ni ejecuta el oráculo/modelo. Los encargos de `higiene` requieren `exige_baseline_verde = true`. Los comandos complejos de shell se advierten, no se declaran verificados. GitHub Actions run #227 aprobó 122 tests para el código de esta tanda.
  - Aceptación pendiente: probar encargos históricos representativos y ejecutar `--validar` con la instalación real. Si se exige baseline verde, el oráculo se comprueba durante el despacho real, no en `--validar`.
- [x] **P7 Vista previa de integración.** Tras `pasa`, ejecuta `git merge-tree --write-tree` contra el SHA actual de la base y el HEAD de trabajo; registra `integracion_previa` como `limpia`, `conflictos` o `error`. `siguiente_accion` orienta la recuperación. La operación es de solo lectura. GitHub Actions run [#264](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39076991455) aprobó 129 tests, incluidos casos sintéticos limpios y conflictivos que comprueban que HEAD/worktree de destino no cambian. La integración real con un worker sigue pendiente.

## Fase 3 — Calidad y eficiencia de la delegación

- [x] **P5 Encargos dependientes y ciclo tests → implementación** *(aceptado 2026-10-17: cadena real tester → implementador por `cola.py`, sandbox bwrap: `tests_preparados` → `pasa`; la rama del implementador cuelga de la del tester y su diff no toca `tests/`).* Implementación inicial: `depende_de` valida IDs únicos, dependencias presentes, mismo proyecto/repositorio, ciclos y una sola rama predecesora; `cola.py` espera al predecesor aprobado y crea un encargo temporal que hereda su rama sin modificar el archivo original. `espera_rojo = true` exige agente tester, alcance de tests y marcadores literales; baseline debe ser verde y el oráculo posterior debe fallar con esos marcadores para producir `tests_preparados`. La cola permite esa etapa intermedia y continúa con el implementador. CI run [#370](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39078076954) aprobó 158 tests.
  - Aceptación pendiente: ejecutar una cadena real tester → implementador en sandbox, comprobar que la rama B parte de A y que el implementador no modifica tests protegidos. No se soportan dependencias múltiples por ahora.
- [ ] **P6 Presupuesto de tokens con corte en vivo.** Implementación inicial en `docs/roadmap-hardening`: `presupuesto_tokens` es opcional y positivo; cuando se configura, un lector concurrente cuenta tokens de entrada en cada evento `step-finish` y termina el grupo al alcanzar el límite. Conserva JSONL parcial, registra tokens observados y distingue `presupuesto_agotado` de `presupuesto_no_verificable`; si faltan eventos/campos necesarios, falla cerrado. El timeout existente sigue activo. CI pendiente para este incremento.
  - Aceptación: CI verde sin fugas de descriptores; pruebas sintéticas de corte, stream incompleto y timeout; después, confirmar el esquema real de eventos de OpenCode/LiteLLM instalado.
- [ ] **P9 Cooldown de modelos en LiteLLM.** Inspeccionar la versión y configuración instaladas antes de cambiar nada; probar reintentos, cooldown y recuperación de un modelo simulado como fallido.
  - Aceptación: la cadena evita temporalmente el modelo fallido y vuelve a probarlo según política; no se incorpora gateway externo.
- [ ] **S1.2 Medición comparativa de agentes.** Con el historial, agrupar éxito, rondas, duración, tokens y hallazgos por agente/modelo y clase de tarea; documentar sesgos y tamaño de muestra.
  - Aceptación: reporte reproducible que distingue datos ausentes y no atribuye causalidad a simples correlaciones.

## Fase 4 — Automatización desatendida

- [ ] **P8 Cola nocturna con systemd.** Carpetas `pendientes/`, `en-curso/`, `listos/` y `fallidos/`; reanudación segura, corte ante fallos de infraestructura y resumen de mañana.
  - Dependencias: historial, presupuesto en vivo, estados estructurados, timeout de procesos y controles de seguridad suficientes.
  - Aceptación: simulación de interrupción y corrida prolongada en sandbox; no duplica encargos ni oculta fallos. Solo después realizar una prueba nocturna real supervisada.

## Descartado a propósito

- Daemon con manifiestos YAML y SQLite: complejidad innecesaria para la escala actual.
- GitHub Actions para ejecutar código privado: no sacar código/prompt a máquinas de terceros sin decisión explícita.
- Agente que haga merge: la integración sigue siendo decisión humana.
- Gateway de modelos de terceros: evitar intermediarios para prompts.
- Importación masiva de skills/agentes de terceros: riesgo de cadena de suministro y licencias.

## Criterios globales de cierre

- [ ] Cada cambio tiene tests de regresión pertinentes y evidencia registrada.
- [ ] Separar siempre: implementado, probado automáticamente, probado en vivo y pendiente de ejecutar en el PC de Marcos.
- [ ] Ninguna prueba se declara ejecutada si solo se inspeccionó el código.
- [ ] Mantener una sola rama temporal de trabajo por ciclo; no modificar `main` ni fusionar sin autorización.
- [ ] Actualizar este roadmap y `docs/propuestas.md` al terminar cada incremento.

## Bitácora — contratos de instrucciones (2026-10-14)

Estado: **corrección documental implementada y verificada** (GitHub Actions run #73; los dos tests de contrato pasaron).

- Se corrigió `skills/director-opencode/SKILL.md`: deja de afirmar que OpenCode impide de forma garantizada leer fuera del worktree y deja de indicar que `.venv`/`node_modules` se enlazan siempre. Ahora documenta el opt-in y explicita que el worktree no constituye un sandbox de seguridad.
- Se corrigió `agents/revisor.md`: cada hallazgo debe llevar una sola severidad, `[ALTA]`, `[MEDIA]` o `[BAJA]`, consistente con el validador de `despachar.py`.
- Se agregó `tests/test_instrucciones.py` para evitar que vuelvan las dos contradicciones detectadas.
- No se añadieron roles ni skills: la prioridad es mantener consistentes los contratos existentes antes de aumentar la autonomía.
- Validación automatizada: pendiente del workflow de GitHub Actions para este commit. No se declara ejecutada localmente ni en el equipo de Marcos.


## Bitácora — validador preventivo P4 (2026-10-14)

Estado: **implementación inicial y pruebas automatizadas aprobadas; aceptación completa pendiente**.

- Se agregó `despachar.py ENCARGO.md --validar`. Comprueba configuración, tipos, patrones de alcance, rutas de mutación, repositorio Git, referencia base y agentes requeridos.
- La CLI aplica la validación antes de despachar o revisar; `--validar` ejecuta solo el preflight. No crea worktree, no ejecuta el oráculo ni lanza OpenCode.
- Los encargos del agente `higiene` se bloquean si no declaran `exige_baseline_verde = true`; el oráculo se ejecuta durante el despacho real, no en el preflight.
- Se impuso un máximo de 30.000 caracteres al encargo para evitar instrucciones descontroladamente extensas.
- GitHub Actions run #130: **106 tests aprobados**, incluida la cobertura del preflight automático, rutas absolutas externas, agente/base ausentes, baseline de higiene y límite del cuerpo.
- Pendiente: validar con la instalación real y comprobar ejecutabilidad del oráculo antes de marcar P4 como completo.


## Bitácora — barrido transversal adicional (2026-10-14)

**Implementado en `docs/roadmap-hardening`; GitHub Actions run #227 aprobó 122 tests.**

- Runtime/oráculos: cada comando tiene timeout propio; al agotarse, el proceso y sus descendientes se terminan con SIGTERM y escalado a SIGKILL. El log deja constancia del timeout.
- Preflight: se comprueba el ejecutable inicial del oráculo cuando es inferible; se advierte cuando una construcción de shell impide verificarlo estáticamente. Se normalizan finales de línea CRLF en encargos.
- Worktrees: un worktree reutilizado con cambios sin commitear queda bloqueado antes de ejecutar el oráculo/modelo.
- Cola: normaliza rutas de repositorio antes de decidir concurrencia; las excepciones del runner cuentan para el corte de fallos; valida `--max` (1–3), evita colisiones de nombres de resumen y conserva diagnósticos en el JSON de cola.
- Estado: se añadió `schemas/estado.v1.schema.json`, timestamps UTC, versión del estado y `siguiente_accion`; el contrato mínimo se valida antes de persistir. Esto es una primera versión, no una implementación completa del estándar JSON Schema.
- Pendiente para Claude/entorno anfitrión: prueba real OpenCode/LiteLLM, inspección de `estado.json` de trabajador, sandbox de sistema operativo, validación de la cola completa e inspección de encargos históricos. Ver [handoff para Claude](docs/handoff-claude.md) para pasos concretos.


## Bitácora — aceptación en el equipo anfitrión (2026-10-17)

Primera corrida **real** (OpenCode + LiteLLM locales, agente `tester`, repo sintético de dos funciones). Estado: **probado en vivo**.

- `bash verificar.sh --installed` y `--tools`: OK en el host (163 tests, entonces).
- `--validar` y `--dry-run` con encargo real: OK.
- **Parser de uso (P1):** el JSONL real de OpenCode coincide con `uso.py`: 3 pasos / 3 eventos con tokens en la ronda 1 y 18 pasos / 18 eventos en la ronda 2, `razon_final = stop`, 0 líneas inválidas. `estado.json` validó contra el esquema v1 y la corrida quedó anexada a `runs/historial.jsonl`.
- **Hallazgo 1 (ronda 1, `sin_cambios`):** el modelo cargó la skill `delegacion-opencode`, ejecutó `git fetch` y terminó con `stop` sin escribir nada (197 s, 47 k tokens de entrada). El despachador lo clasificó bien. La ronda 2 con feedback concreto sí produjo `tests/test_calc.py`, commits y oráculo verde.
- **Hallazgo 2 (ronda 2, `fuera_de_alcance`):** el oráculo dejó `__pycache__/*.pyc` y el worker los commiteó (el repo no tenía `.gitignore`). Corregido: `excluir_artefactos()` agrega `__pycache__/` y `*.pyc` a `info/exclude` del repo antes de crear el worktree (test incluido).
- `REPORTE.md` y `docs/opencode/**` ya estaban en `SIEMPRE_PERMITIDOS`: no hubo falsos positivos de alcance por ellos.
- Aún no cubierto: veredicto del revisor con OpenCode real, hallazgo ALTA, cola completa con timeout exterior (ver fases siguientes).

- **S0.2 (avance, probado en vivo):** `sandbox.py` + `sandbox = "bwrap"` (opt-in). Corrida real del trabajador `tester` y del `revisor` dentro de bwrap contra LiteLLM local: el worker commiteó y el oráculo pasó; un archivo centinela en `$HOME` y `auth.json` no fueron accesibles. Límites: red compartida (proxy en 127.0.0.1) y `.git` común escribible. Falta decidir si pasa a ser el valor por defecto.
- **Hallazgo 3 (revisor real):** el modelo escribió `APTO.` y el validador estricto rechazó el formato. Ahora `normalizar_veredicto` tolera `**`, backticks y puntuación final, pero no palabras nuevas. Tras el cambio la revisión real dio `aprobado / APTO`.

- **S0.6 Codex (probado en vivo, codex-cli 0.163.0):** `--approve-for-me` existe y `motor = "codex"` completó el encargo de práctica en 23 s con veredicto `pasa`, sin ningún prompt. Sondeo directo del sandbox: **escribir fuera del worktree falla** (`Read-only file system`), **la red falla** (curl rc 6), pero **leer `$HOME` sí está permitido** (un archivo centinela fue leído, rc 0; solo el modelo se negó a repetirlo). Decisión: Codex queda opcional y **solo para proyectos sin secretos ni datos de terceros**; `sandbox = "bwrap"` no se combina con Codex. Hallazgo: el sandbox no puede escribir el gitdir del worktree, así que el trabajador no puede commitear; ahora el despachador commitea lo pendiente (`commitear_pendientes`) y el alcance, los inmutables y el oráculo se verifican sobre ese commit.

- **Cadena real (P5/P1/S0.4 parcial):** `cola.py --max 2` con 3 encargos (tester `espera_rojo` → implementador `depende_de`, más un tester independiente en paralelo), todos con `sandbox = "bwrap"`: 211 s, resultados `tests_preparados`, `pasa`, `pasa`. Una primera tanda reveló `trabajo_sin_commitear` espurio: el encargo pide dejar `REPORTE.md` y luego se penalizaba por no estar commiteado. Ahora `commitear_reporte` lo commitea cuando es lo único sucio (si hay archivos ajenos no toca nada).
- Sigue sin probarse en vivo: timeout exterior de la cola y recuperación ante interrupción (cubiertos solo por tests sintéticos).

- **S0.5 (medido sobre repos reales):** el detector de secretos se midió sobre las últimas 150 commits de 6 repos locales (líneas añadidas). Antes: 656 coincidencias en total, casi todas falsas (base64 de imágenes que contenían `aKIA`, `os.environ.get`, `csrfTokenFor`, fixtures `csrf-*`). Cambios: prefijos de proveedor sensibles a mayúsculas y con límite de palabra, patrón JWT propio, y descarte de marcadores de prueba (`test`, `mock`, `csrf`, `prueba`…) y de expresiones sin dígitos cuando el valor no va entre comillas. Resultado: ~71 coincidencias, que son contraseñas/secretos literales de fixtures (`SESSION_SECRET: "…"`, `password = "…"`) y los JWT de `croco-main`. Se prefirió un falso positivo ocasional a perder un secreto real: la cola trata `posible_secreto` como descarte de la rama, no como juicio.
