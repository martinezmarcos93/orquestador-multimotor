# Roadmap de endurecimiento y expansión de proveedores

Estado: publicado en rama de trabajo; implementación incremental en curso.
Rama: `feat/roadmap-hardening-antigravity`
Base: `main`
Última actualización: 2026-10-23

## Objetivo

Mejorar la confiabilidad de los encargos y preparar la incorporación opcional de Antigravity sin reemplazar la arquitectura existente. Claude continúa como director y responsable de la decisión final; OpenCode permanece como motor predeterminado, Codex sigue siendo un motor opcional y la integración de cambios continúa siendo una decisión humana.

Los repositorios externos se usan como referencias de diseño, no como dependencias que deban importarse completas:
- Orkestra: adaptadores, ejecución de procesos, políticas de reintento y worktrees.
- Agent Orchestrator: estados explícitos, identidad de solicitud y separación entre ejecución y aceptación.
- Codex Orchestrator: supervisión y validación del ciclo de vida de procesos en Herdr.
- AWS CLI Agent Orchestrator: separación entre proveedor de agente y backend de terminal; sus limitaciones documentadas con Antigravity/Herdr se tratarán como específicas de esa implementación.

## Orden de implementación

### Fase 1 — Endurecimiento antes de ampliar proveedores

#### 1. Cerrar la compuerta de revisión
- Revisar el flujo de `revisor = true` y los estados `resultado` / `aprobacion`.
- No permitir aceptación implícita si el revisor falla, entrega formato inválido o no produce un veredicto válido.
- Mantener distinguibles el resultado del oráculo, el resultado de revisión y la decisión final del director.
- Añadir pruebas para revisión aprobada, rechazada, fallida y malformada.

Criterio de aceptación: un fallo de revisión nunca se transforma silenciosamente en aceptación plena; la compatibilidad de encargos sin revisor se conserva.

#### 2. Endurecer timeout, cancelación y terminación
- Verificar límites de tiempo del trabajador, despachador y cola.
- Añadir un límite exterior donde falte y garantizar terminación controlada del grupo de procesos.
- Conservar estados explícitos de timeout/interrupción y evitar reenvíos automáticos cuando el resultado de la ejecución sea incierto.
- Añadir pruebas de bloqueo, SIGTERM, proceso hijo/nieto y ausencia de procesos huérfanos.

Criterio de aceptación: una tarea bloqueada finaliza dentro de un límite conocido, deja un estado diagnóstico y no deja descendencia activa conocida.

#### 3. Reforzar trazabilidad de base y worktree
- Registrar `base_sha`, `head_sha`, rama y ruta de worktree por corrida.
- Validar que la referencia base y el worktree reutilizado coincidan con lo esperado.
- Bloquear reutilización cuando la identidad Git o el estado del worktree sean inconsistentes.
- Añadir pruebas de regresión para cambios de base y worktrees sucios o divergentes.

Criterio de aceptación: cada veredicto puede vincularse a referencias Git concretas y verificables; ninguna comprobación implica merge automático.

### Fase 2 — Antigravity como motor opcional

#### 4. Verificar el contrato real de `agy`
- Confirmar disponibilidad de CLI, autenticación, modo headless, flags soportados y formato de salida en el entorno anfitrión.
- No instalar herramientas ni ejecutar tareas con permisos amplios de forma implícita.
- Registrar la versión verificada y fixtures de salida/error para pruebas sin consumir cuota.

Criterio de aceptación: contrato de invocación documentado con evidencia del entorno; si el CLI no está disponible, la suite unitaria sigue funcionando con dobles.

#### 5. Implementar adaptador aislado
- Añadir Antigravity como motor optativo sin alterar el motor predeterminado.
- Normalizar salida final, errores, timeout, cancelación y metadatos al contrato de estado existente.
- Usar ejecución de argumentos sin shell, entorno explícito y límites de salida.
- Reutilizar el mismo oráculo y controles de alcance después de la ejecución.
- No dar al adaptador autoridad para aprobar su propio trabajo.

Criterio de aceptación: pruebas de contrato cubren éxito, salida malformada, fallo de proceso, timeout y ausencia de ejecutable; OpenCode y Codex mantienen su comportamiento.

### Fase 3 — Fallback acotado

#### 6. Añadir política de fallback explícita
- Clasificar fallos de autenticación/no disponibilidad, rate limit, timeout, crash, salida inválida y fallo del oráculo.
- Permitir fallback solo ante categorías declaradas y cuando el motor alternativo esté configurado.
- Registrar cada intento y su causa en el historial.
- Limitar cantidad de intentos y evitar ciclos.
- No cambiar de motor por un fallo del oráculo o por defectos del resultado como si fueran fallos de infraestructura.
- No reejecutar una tarea cuyo resultado sea incierto sin una política segura de idempotencia.

Criterio de aceptación: fallback determinista, acotado, auditable y cubierto por tests; si no hay alternativa válida, la tarea falla de manera explícita.

## Mejoras aplazadas deliberadamente

Estas ideas quedan registradas para evaluación futura, pero **no se incorporan en esta iteración**:

1. Migrar el orquestador a otro lenguaje o framework (Node.js, Rust o un kernel externo).
2. Sustituir historial JSONL/estado actual por SQLite, daemon persistente o manifiestos YAML.
3. Reemplazar Herdr/visor por otro multiplexor o agregar una segunda capa de paneles.
4. Importar agentes, skills o scripts completos de los repositorios de referencia sin revisión de licencia, seguridad y cadena de suministro.
5. Fallback ilimitado, reintentos infinitos, selección autónoma de proveedor o cambios de motor sin límites.
6. Merge automático de ramas o aprobación autónoma por parte de workers, revisores o Antigravity.
7. Ejecutar trabajos en GitHub Actions o máquinas de terceros como sustituto del entorno local.
8. Incorporar gateways de modelos externos que expongan prompts o código a intermediarios adicionales.
9. Ampliar el paralelismo por encima del límite actual antes de medir cuotas, conflictos de archivos y fiabilidad.
10. Reescribir el sandbox o presentarlo como aislamiento hermético: las limitaciones actuales de red, gitdir y acceso al entorno deben seguir documentadas.

## Disciplina de trabajo y publicación

- Trabajar exclusivamente en esta rama; no modificar ni fusionar `main` sin autorización explícita.
- Ejecutar la suite relevante después de cada incremento y la suite completa al cerrar cada fase.
- Añadir pruebas de regresión antes de dar por cerrada una corrección.
- Mantener documentación sincronizada con el comportamiento real, distinguiendo pruebas unitarias, pruebas con CLI real y aceptación en el equipo anfitrión.
- Publicar commits pequeños y verificables. No declarar validación local o integración real si solo se ha editado código a través de GitHub.
- Antes de pasar de una fase a la siguiente, revisar el diff y comprobar que las tareas aplazadas continúan fuera del alcance.

## Estado inicial

- [x] Rama de trabajo creada desde `main`.
- [x] Roadmap publicado.
- [ ] Fase 1.1: compuerta de revisión.
- [ ] Fase 1.2: timeout y terminación de procesos.
- [ ] Fase 1.3: trazabilidad de base y worktree.
- [ ] Fase 2: verificación e integración de Antigravity.
- [ ] Fase 3: fallback acotado.
