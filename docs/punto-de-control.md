# Punto de control

<!-- PUNTO-DE-CONTROL -->
- Tarea actual: compuerta de nivel A por código, en la rama `feat/compuerta-nivel-a` (4 commits, 226 tests verdes, subida, sin mergear).
- Próximo paso: Marcos decide el merge a `main`. Después, reinstalar con `./instalar.sh` para que la skill `director-opencode` salga de la plantilla actualizada (hoy ya coinciden).
- Bloqueado por: OK de Marcos para el merge.
- Archivos en curso: `despachar.py` (`motivo_nivel_a`, `PROYECTOS_NIVEL_A`, `ZONAS_NIVEL_A`), `tests/test_despachar.py` (clase TestParseo), `skills/director-opencode/SKILL.md`.
- Preguntas abiertas: los encargos de nivel A futuros necesitan `excepcion_nivel_a = "AAAA-MM-DD: motivo"`; los de Hanna del 23/10 no lo tienen (son históricos). `systemd/orquestador-nocturno.service` tiene la ruta personal del disco en un repo público.
<!-- /PUNTO-DE-CONTROL -->
