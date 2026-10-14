# Roadmap

Detalle, origen y diseño de cada ítem en [`docs/propuestas.md`](docs/propuestas.md).

**Método:** un incremento por vez, con tests y prueba en vivo antes del siguiente. Un ítem se marca hecho solo si pasa su criterio de aceptación.

## Hecho (2026-10-13)

- [x] Despachador: un encargo → un veredicto (`despachar.py`), con tope de 2 rondas
- [x] Trabajadores `tester`, `implementador`, `higiene`, `revisor` y skill `director-opencode`
- [x] Prueba de mutación automática y veredicto `tests_debiles`
- [x] Cola con paralelismo limitado (máx. 3) y candado por proyecto
- [x] Visor opcional en Herdr, `--reevaluar` y `--revisar-solo`
- [x] Repo público, historial con identidad `noreply`

## Fase 1 — Base de mantenimiento y trazabilidad

Baratos, independientes y de alto impacto. Se pueden hacer en cualquier orden.

- [ ] **P0 `verificar.sh`**: tests, `--dry-run` de ejemplo, agentes instalados iguales a los del repo y proxy vivo. *Aceptación:* un agente desactualizado o un mensaje roto a OpenCode lo hacen fallar sin gastar cuota.
- [ ] **P1 Historial y registro de uso**: `uso.py`, `runs/historial.jsonl` y `historial.py`. *Aceptación:* tras una cola de 3 encargos, `historial.py --por agente` coincide con la suma de los `estado.json`.
- [ ] **P3 Archivos `inmutables`**: veredicto `viola_inmutables`. *Aceptación:* un `implementador` que toca un test existente se rechaza sin leer el diff.

## Fase 2 — Estado y validación

- [ ] **P2 `estado.json` v1** con `siguiente_accion`, `head_sha`, comandos y evidencias. Depende de P1. *Aceptación:* todo estado valida contra `schemas/estado.v1.schema.json` y cada veredicto tiene `siguiente_accion`.
- [ ] **P4 Validador de encargos** (`--validar`). *Aceptación:* cada error de la primera práctica (ruta externa, `.venv` ausente) tiene un test que el validador atrapa.
- [ ] **P7 Vista previa de integración** (`git merge-tree`, solo lectura). *Aceptación:* un `pasa` que chocaría con `main` lo informa en `estado.json`.

## Fase 3 — Flujos de más valor

- [ ] **P5 `depende_de` y ciclo tests → implementar**, con `espera_rojo`. Depende de P3. *Aceptación:* en el sandbox, un `tester` escribe los tests y un `implementador` pasa el oráculo sin modificar ninguno.
- [ ] **P6 Presupuesto de tokens con corte en vivo** (`presupuesto_agotado`). Depende de P1. *Aceptación:* un trabajador con presupuesto bajo se corta y deja un estado consistente.
- [ ] **P9 Cooldown de modelos en LiteLLM.** Verificar primero qué ofrece la versión instalada. *Aceptación:* con un modelo caído a propósito, la cadena lo saltea y lo reintenta pasado el enfriamiento.

## Fase 4 — Desatendido

- [ ] **P8 Cola nocturna con systemd** (`pendientes/` → `en-curso/` → `listos/` o `fallidos/`). Depende de P1 y P6. *Aceptación:* una noche completa sin intervención, y a la mañana el historial resume lo ocurrido.

## Descartado a propósito

- Daemon con manifiestos YAML y SQLite (contra la simplicidad técnica intencionada).
- Ejecución en GitHub Actions (CI de repos privados bloqueado por facturación; el código saldría a máquinas de terceros).
- Agente que haga el merge (el merge es decisión humana).
- Gateways de modelos de terceros (los prompts pasarían por intermediarios).
- Importar colecciones de skills o agentes de terceros (cadena de suministro y licencias).

## Mantenimiento

No hace falta una flota de skills. Se mantiene con `verificar.sh` (P0) más los tres textos que ya existen: `director-opencode`, `delegacion-opencode` y los `agents/*.md`.
