# Orquestador multimotor

**Claude coordina. OpenCode, Codex y Antigravity ejecutan. El oráculo verifica. Una persona decide qué se integra.**

Orquestador de tareas de programación mediante encargos acotados, ramas/worktrees, pruebas automáticas y revisión de cambios. Ningún trabajador integra directamente a `main`.

## El flujo de trabajo

```text
                    ┌──────────────────────────┐
                    │     CLAUDE · DIRECTOR    │
                    │ define tarea y límites   │
                    │ revisa y decide          │
                    └────────────┬─────────────┘
                                 │ ENCARGO.md
                                 ▼
                    ┌──────────────────────────┐
                    │   DESPACHADOR · Python   │
                    │ valida · crea worktree   │
                    │ registra la ejecución    │
                    └────────────┬─────────────┘
                                 │ selecciona UN motor
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
     │ OPENCODE       │ │ CODEX CLI      │ │ ANTIGRAVITY CLI│
     │ agente worker  │ │ codex exec     │ │ agy --print    │
     └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
             └──────────────────┼──────────────────┘
                                ▼
                    ┌──────────────────────────┐
                    │ VERIFICACIÓN AUTOMÁTICA  │
                    │ oráculo · alcance        │
                    │ rutas protegidas · diff  │
                    └────────────┬─────────────┘
                                 │ estado.json + reporte
                                 ▼
                    ┌──────────────────────────┐
                    │ CLAUDE REVISA LA ENTREGA │
                    └────────────┬─────────────┘
                                 ▼
                    ┌──────────────────────────┐
                    │ DECISIÓN HUMANA          │
                    │ integrar / pedir cambios │
                    │ / descartar              │
                    └──────────────────────────┘
```

**Roles:** Claude no es un trabajador más: dirige, aporta contexto, evalúa el resultado y decide el siguiente paso. El despachador prepara y controla la ejecución. OpenCode, Codex CLI o Antigravity realizan la tarea asignada —un motor por encargo—. El oráculo comprueba el resultado; no se confía únicamente en lo que afirme el modelo.

## Instalación y comprobación

Requisitos: Python 3.11+, Git y el CLI que quieras usar, instalado y autenticado.

```bash
git clone https://github.com/martinezmarcos93/orquestador-multimotor.git
cd orquestador-multimotor
bash verificar.sh
python3 -m unittest discover -s tests
```

La suite de verificación no necesita lanzar modelos ni requiere red.

## Uso mínimo

1. Crear un encargo Markdown con bloque de configuración TOML: repositorio, rama base, agente, archivos permitidos, oráculo y timeout.
2. Validar y, primero, simular:
   ```bash
   python3 despachar.py ENCARGO.md --validar
   python3 despachar.py ENCARGO.md --dry-run
   ``
3. Ejecutar el encargo solo después de revisar la configuración y el riesgo.
4. Revisar `runs/<proyecto>-<id>/ronda-N/estado.json`, `REPORTE.md` y el diff.
5. Integrar manualmente solo después de revisar y aprobar.

En el encargo se selecciona el motor con `motor = "opencode"`, `motor = "codex"` o `motor = "antigravity"`. OpenCode es el predeterminado.

## Diferencias y límites de los motores

| Motor | Ejecución | Consideración principal |
|---|---|---|
| **OpenCode** | Agente configurado en el encargo | Puede usar el aislamiento `bwrap` opcional, si está disponible. |
| **Codex CLI** | `codex exec` no interactivo | El sandbox workspace-write limita escrituras y red; las pruebas disponibles observaron que aún puede leer `$HOME`. No usar con secretos. |
| **Antigravity CLI** | `agy --print` con salida JSON y `--sandbox` | Requiere aceptar explícitamente el riesgo. `--sandbox` es *best-effort*; no equivale a aislamiento verificado del host. **Hoy no puede editar archivos ni ejecutar comandos en modo desatendido** sin reglas `permissions.allow` en el host ([evidencia 23/10/2026](docs/evidencia/2026-10-23-antigravity-y-tanda-hanna.md)). |

Un **worktree no es un sandbox de seguridad**. Usar repositorios desechables y sin secretos al validar un motor nuevo. Una respuesta CLI correcta no prueba que el sandbox funcione. No ampliar permisos automáticamente si falla una ejecución.

## Resultados

El despachador registra el estado y la evidencia en `runs/`. Cada ejecución usa un directorio `ronda-N` nuevo. No cuentan para el tope de dos rondas de trabajo las ejecuciones en las que el motor no llegó a trabajar: errores del motor o entorno (`error_opencode`, `error_codex`, `error_antigravity`, `timeout`, `error_despachador`, `motor_sin_respuesta`), salidas tempranas (`dry_run`, `baseline_rojo`, `worktree_base_divergente`, `worktree_reutilizado_sucio`) y límites de presupuesto (`presupuesto_no_verificable`, `presupuesto_agotado`). Conservan su evidencia y `estado.json` indica esto con `cuenta_para_tope: false`. Los resultados también pueden indicar fallo del oráculo, cambio fuera de alcance o violación de rutas inmutables. `trabajo_sin_commitear` también cubre archivos ignorados dentro de patrones permitidos con comodines; se enumeran en `ignorados_sin_commitear`. Ante un fallo, revisar los logs y corregir el encargo; no integrar una entrega rechazada.

## Documentación

- [Roadmap de endurecimiento y Antigravity](docs/ROADMAP_ENDURECIMIENTO_ANTIGRAVITY.md)
- [Validación de Antigravity en el host](docs/VALIDACION_HOST_ANTIGRAVITY.md)
- [Roadmap general](ROADMAP.md)
- [Propuestas y antecedentes](docs/propuestas.md)

## Principios

- Encargos pequeños, explícitos y verificables.
- Separación entre director, trabajador y verificador.
- Límites de archivos y rutas inmutables.
- El oráculo y el diff pesan más que la declaración del agente.
- Sin push ni merge automático a `main`.
- La decisión de integración es humana.
