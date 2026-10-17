# Roadmap

Detalle, decisiones de diseño y criterios de aceptación en [`docs/propuestas.md`](docs/propuestas.md). Los riesgos concretos y la priorización conciliada de la revisión están en [`docs/revision-arquitectonica.md`](docs/revision-arquitectonica.md).

**Método de trabajo:** un incremento por vez; rama temporal única; tests automatizados y prueba en vivo cuando sea posible; documentar evidencia, bloqueos y lo que no pudo ejecutarse. `main` es la fuente de verdad y no se modifica durante esta etapa. No marcar un ítem como hecho por haber escrito el código: debe cumplir su criterio de aceptación. No integrar ni fusionar sin autorización explícita de Marcos.

## Requisito rector: autonomía supervisada

El objetivo operativo es reducir al mínimo la intervención de Marcos sin ampliar permisos de forma indiscriminada. Claude debe poder dirigir el ciclo de trabajo y resolver operaciones rutinarias dentro de una política explícita; las acciones fuera de alcance se deniegan por defecto. Este repositorio controla el despachador de OpenCode, no necesariamente las solicitudes de permiso de la aplicación Codex: esa integración debe investigarse por separado y no declararse resuelta solo por cambiar la política de OpenCode.

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

## Fase 1 — Mantenimiento reproducible y trazabilidad básica

- [ ] **P0 `verificar.sh`.** Implementación parcial en esta rama: modo básico compila Python, valida sintaxis shell, ejecuta `--help` y la suite sin modelos ni red; `--installed` compara agentes/skill instalados y `--tools` comprueba binarios. Se agregó GitHub Actions para ejecutar la verificación en PR/push. GitHub Actions run #60 completó `bash verificar.sh` con éxito (97 tests). La prueba CLI de `--dry-run` usa un binario OpenCode falso que deja una marca si se ejecuta; la marca no aparece y no se consume cuota.
  - Aceptación pendiente: ejecutar un `--dry-run` con un encargo real en el equipo anfitrión para confirmar rutas y permisos locales.
- [ ] **P1 Historial y registro de uso.** Añadir `uso.py`, ledger append-only `runs/historial.jsonl` y `historial.py`; parsear tokens por paso, duración, rol, veredicto y puntuación de mutación. Identificar modelo solo si el stream o una fuente local lo confirma.
  - Aceptación: tras tres encargos, los totales cuadran con sus estados; campos no disponibles se registran como desconocidos, no se inventan.
- [x] **P3 Archivos inmutables.** `inmutables` es opcional, valida patrones relativos y genera `viola_inmutables` si una ruta cambiada coincide; `git diff --no-renames` detecta origen/destino de renombres. Una violación bloquea la aprobación y omite oráculo/mutación para evitar efectos secundarios de pruebas. GitHub Actions run [#264](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39076991455): 129 tests aprobados, incluidos patrones inválidos, traversal, borrado/renombre y prioridad del veredicto. La integración real con un worker sigue pendiente.
- [ ] **S1.1 Contrato de mutación y lectura de resultados.** Avance parcial: la evaluación de mutación que devuelve error o cero candidatos ya no puede acabar en `pasa`; se distinguen `error_mutacion` y `mutacion_sin_candidatos`. Sigue pendiente mostrar con claridad universo completo/truncado, mutación equivalente probable y límites de interpretación del puntaje.
  - Aceptación: pruebas de universo truncado, cero candidatos y oráculo que falla; no presentar el puntaje como porcentaje general de calidad.

## Fase 2 — Estado estructurado y validación preventiva

- [ ] **P2 `estado.json` v1.** Implementación inicial: `schema_version = 1`, timestamps UTC, `siguiente_accion`, referencia al propio archivo y esquema en `schemas/estado.v1.schema.json`. La CLI valida el contrato mínimo antes de persistir; el esquema permite campos adicionales para compatibilidad. Todavía no existe un validador JSON Schema completo ni están normalizadas todas las fases/evidencias de ejecución.
  - Aceptación pendiente: validar todas las propiedades del esquema con herramienta compatible, completar fases/comandos/evidencias y cubrir cada veredicto con pruebas.
- [ ] **P4 Validador de encargos (`--validar`).** Comprueba tipos, patrones relativos sin traversal, mutación, repo/base, agentes requeridos, rutas absolutas externas en el cuerpo, límite de 30.000 caracteres y el ejecutable inicial de cada comando cuando puede inferirse. La CLI aplica el preflight antes del despacho/revisión; no crea worktree ni ejecuta el oráculo/modelo. Los encargos de `higiene` requieren `exige_baseline_verde = true`. Los comandos complejos de shell se advierten, no se declaran verificados. GitHub Actions run #227 aprobó 122 tests para el código de esta tanda.
  - Aceptación pendiente: probar encargos históricos representativos y ejecutar `--validar` con la instalación real. Si se exige baseline verde, el oráculo se comprueba durante el despacho real, no en `--validar`.
- [x] **P7 Vista previa de integración.** Tras `pasa`, ejecuta `git merge-tree --write-tree` contra el SHA actual de la base y el HEAD de trabajo; registra `integracion_previa` como `limpia`, `conflictos` o `error`. `siguiente_accion` orienta la recuperación. La operación es de solo lectura. GitHub Actions run [#264](https://github.com/martinezmarcos93/orquestador-opencode/actions/runs/39076991455) aprobó 129 tests, incluidos casos sintéticos limpios y conflictivos que comprueban que HEAD/worktree de destino no cambian. La integración real con un worker sigue pendiente.

## Fase 3 — Calidad y eficiencia de la delegación

- [ ] **P5 Encargos dependientes y ciclo tests → implementación.** Incorporar `depende_de`, `espera_rojo` y `inmutables`; validar grafo acíclico, fallos de dependencias y base de cada etapa.
  - Aceptación: en sandbox, tester crea tests que fallan por la razón esperada y el implementador los satisface sin alterarlos.
- [ ] **P6 Presupuesto de tokens con corte en vivo.** Consumir eventos JSONL mientras se ejecuta OpenCode y detener al superar `presupuesto_tokens`; conservar evidencia parcial y terminar con `presupuesto_agotado`.
  - Aceptación: prueba con presupuesto mínimo corta el proceso, deja estado consistente y no pierde logs; timeout sigue funcionando.
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
