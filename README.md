# Orquestador OpenCode — Claude dirige, los trabajadores obedecen

Sistema de orquestación en el que Claude Code actúa como **director** y modelos gratuitos de OpenCode como **trabajadores**. Claude escribe un encargo acotado, el despachador lo ejecuta en un worktree aislado, verifica el resultado con un oráculo y Claude revisa y decide: integrar, dar una orden nueva con feedback o tomarlo él.

> **Principio fundamental:** Claude no controla terminales, coordina trabajo. La comunicación es por archivos y el veredicto sale de un oráculo ejecutable, no del "listo" de quien trabajó.

---

## Instalación rápida

**Requisitos:** Python 3.11+, `git`, [`opencode`](https://opencode.ai) con un proveedor configurado (en este caso un proxy LiteLLM local con fallback entre modelos gratuitos) y Claude Code.

```bash
git clone https://github.com/martinezmarcos93/orquestador-opencode.git
cd orquestador-opencode
./instalar.sh          # copia los agentes a ~/.config/opencode/agents y la skill a ~/.claude/skills
python3 -m unittest discover -s tests
```

No tiene dependencias externas: solo la librería estándar.

---

## Cómo usar

### Flujo básico

1. **Elegí** un proyecto de bajo calibre (git, en disco ext4) y una tarea chica con oráculo verificable.
2. **Redactá** el encargo en `_encargos/<proyecto>/NNN-tema.md`, empezando por el bloque de configuración:

   ```toml
   +++
   id = "001"
   proyecto = "mercado-sandbox"
   repo = "/home/usuario/src/mercado-sandbox"
   agente = "tester"
   tema = "tests-nucleo"
   base = "main"
   permitidos = ["tests/**"]
   oraculo = [".venv/bin/python -m pytest -q"]
   timeout_min = 20
   +++
   ```

3. **Despachá** (desde Claude, con `run_in_background`; se reactiva solo al terminar):

   ```bash
   python3 despachar.py ENCARGO.md
   python3 despachar.py ENCARGO.md --dry-run     # prepara el worktree sin gastar cuota
   ```

4. **Leé el veredicto** en `runs/<proyecto>-<id>/ronda-N/estado.json`, revisá el diff y decidí.

### Veredictos

| `resultado` | Qué significa | Qué hace el director |
|---|---|---|
| `pasa` | Oráculo verde, dentro de alcance | Revisa el diff y propone integrar (el merge es humano) |
| `falla_oraculo` | Los tests no pasan | Nueva ronda con feedback concreto |
| `sin_cambios` / `trabajo_sin_commitear` | No hizo nada, o dejó cambios sueltos | Nueva ronda o los commitea |
| `fuera_de_alcance` | Tocó archivos no permitidos | Descarta o devuelve sin leer el diff |
| `dependencia_nueva` / `posible_secreto` | Cambió dependencias o metió algo sensible | Descarta |
| `timeout` / `error_opencode` | Cuota, proxy o modelo colgado | Revisa `opencode.err` |
| `tope_rondas` | Ya hubo 2 rondas del mismo encargo | Lo toma Claude |

---

## Arquitectura

```
Claude (director)                       despachar.py                      OpenCode (trabajador)
 │ escribe _encargos/<proy>/NNN.md ───▶ │ git worktree + rama opencode/…
 │                                      │ enlaza .venv / node_modules
 │                                      │ opencode run --agent <trabajador> ─▶ trabaja y commitea
 │                                      │ ◀──────── REPORTE.md + commits ─────┘
 │                                      │ oráculo antes/después · alcance · deps · secretos
 │ ◀──────────── estado.json ───────────┘
 ├─ pasa ────────▶ revisa diff, prueba de mutación, propone integrar
 ├─ ajustes ─────▶ nuevo encargo con feedback (máx. 2 rondas)
 └─ tope ────────▶ lo termina Claude
```

### Trabajadores

Cada trabajador es un agente de OpenCode (`agents/*.md`) con su propio prompt y permisos de edición:

| Agente | Función | Puede editar |
|---|---|---|
| `tester` | Escribe solo tests | `tests/**`, `REPORTE.md`, `docs/opencode/**` |
| `implementador` | Una tarea acotada de código | Archivos permitidos del encargo |

---

## Estructura del repositorio

```
orquestador-opencode/
├── README.md
├── despachar.py                 # despachador: un encargo → un veredicto
├── instalar.sh                  # instala agentes y skill
├── agents/                      # trabajadores de OpenCode
├── skills/director-opencode/    # skill de Claude: el ciclo del director
├── tests/                       # unittest del despachador
└── runs/                        # logs y estado.json por corrida (ignorado por git)
```

---

## Lecciones de la primera práctica

Probado el 2026-10-13 con un sandbox de análisis de mercado y el agente `tester`:

1. **OpenCode desatendido rechaza leer fuera del worktree** y se detiene en silencio (`external_directory ... auto-rejecting`). Por eso el encargo va incrustado en el mensaje y la ruta del repo original se reescribe.
2. **Un worktree no trae `.venv` ni `node_modules`** (están en `.gitignore`): el despachador los enlaza y los excluye de git.
3. **`git status` colapsa carpetas nuevas** a `docs/`: se usa `-uall` para no dar falsos positivos de alcance.
4. **No fiarse del "listo" ni de los "bugs encontrados".** El modelo gratuito afirmó asserts que contradecían su propia aritmética y los llamó bugs del código.
5. **Prueba de mutación como compuerta de calidad:** tests verdes no bastan. Dos bordes de RSI sobrevivieron a la mutación hasta que el director los corrigió.

---

## Calibre y límites

Solo se delega trabajo de bajo calibre: sin secretos, sin dinero ni datos de terceros. Los modelos gratuitos pueden usar los prompts para entrenar. El trabajador nunca hace push a `main` ni merge, y el despachador verifica que `main` quedó intacto.
