# Roadmap de endurecimiento y expansión de proveedores

Estado: publicado en rama de trabajo; implementación incremental en curso. Antigravity tiene adaptador inicial y pruebas con fixtures; CI #454 y #455 aprobadas; se añadió una guía reproducible para la validación en el equipo anfitrión, que sigue pendiente.
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
- La documentación oficial consultada confirma `agy --print`, `--output-format json`, `--print-timeout`, `--model`, `--effort` y `--sandbox`; la integración usa salida JSON final y no activa `--dangerously-skip-permissions`.
- La documentación oficial advierte que headless depende de credenciales previamente almacenadas y que `--sandbox` puede no contener procesos si no está disponible en el host.
- Confirmar versión, autenticación y efectividad real del sandbox en el equipo anfitrión antes de ejecutar tareas que escriban código.
- Seguir la lista de comprobación de `docs/VALIDACION_HOST_ANTIGRAVITY.md`; registrar la evidencia sanitizada sin credenciales ni prompts privados.
- No instalar herramientas ni ejecutar tareas con permisos amplios de forma implícita.
- Revisar los términos vigentes de Google antes de usar el proveedor desde una herramienta de orquestación externa; Orkestra documenta una zona gris contractual para ese patrón.

Criterio de aceptación: contrato de invocación cubierto por fixtures y verificación en el entorno anfitrión registrada por separado; si el CLI no está disponible, la suite unitaria sigue funcionando con dobles.

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
- [x] Fase 1.1: compuerta explícita de aceptación agregada; pruebas de contrato añadidas; CI de GitHub Actions #442 aprobada.
- [x] Fase 1.2: timeout exterior y terminación de grupos ya estaban implementados en la base (\u0060cola.py\u0060, \u0060procesos.py\u0060, \u0060tests/test_cola.py\u0060); se verificó estáticamente y no se duplicará la lógica. Falta ejecutar CI de esta rama.
- [x] Fase 1.3: la base ya registra SHA inicial/final, SHA inicial del worktree, valida ancestralidad y bloquea worktrees reutilizados sucios o divergentes; las pruebas de regresión existentes pasaron en CI #442. Se conserva esa lógica sin duplicar controles.
- [x] Fase 2.1: adaptador inicial, opciones de configuración y pruebas offline implementadas; CI #454 y #455 aprobadas.
- [x] Fase 2.2: guía de validación anfitriona añadida en `docs/VALIDACION_HOST_ANTIGRAVITY.md`.
- [ ] Fase 2.3: pendiente ejecución real autenticada, verificación del contrato de salida y evaluación del aislamiento/los términos en el equipo anfitrión. No se puede certificar desde GitHub.
- [ ] Fase 2.4: integrar la evidencia de aceptación y decidir explícitamente si Antigravity puede habilitarse para encargos reales.
- [ ] Fase 3: fallback acotado.
