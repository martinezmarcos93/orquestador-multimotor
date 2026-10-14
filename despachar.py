#!/usr/bin/env python3
"""Despachador: ejecuta UN encargo de Claude en OpenCode y deja un veredicto en estado.json.

Claude (director) escribe el encargo; este script crea el worktree, lanza OpenCode sin pantalla,
corre el oráculo y verifica el alcance. Claude no teclea en ninguna terminal: lee estado.json.

Uso: despachar.py ENCARGO.md [--dry-run]
"""
import argparse
import contextlib
import fcntl
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
import tomllib
from datetime import date
from pathlib import Path

import mutacion
import visor as visor_herdr

logger = logging.getLogger("despachar")

RAIZ = Path(__file__).resolve().parent
RUNS = RAIZ / "runs"
SRC = Path.home() / "src"
MAX_RONDAS = 2
SIEMPRE_PERMITIDOS = ["REPORTE.md", "docs/opencode/**"]
ARCHIVOS_DEPENDENCIAS = {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json",
                         "poetry.lock", "Pipfile", "Cargo.toml"}
PATRON_SECRETO = re.compile(r"(api[_-]?key|secret|token|password)\s*[=:]\s*['\"][^'\"\s]{8,}|-----BEGIN", re.I)
CAMPOS_OBLIGATORIOS = ("id", "proyecto", "repo", "agente", "tema", "permitidos", "oraculo")


def parsear_encargo(texto: str) -> dict:
    """Extrae el bloque TOML entre líneas '+++' al inicio del encargo."""
    m = re.match(r"\s*\+\+\+\n(.*?)\n\+\+\+", texto, re.S)
    if not m:
        raise ValueError("el encargo no tiene bloque +++ ... +++ con la configuración")
    cfg = tomllib.loads(m.group(1))
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in cfg]
    if faltan:
        raise ValueError(f"faltan campos en el encargo: {', '.join(faltan)}")
    for campo in ("proyecto", "tema", "id", "agente"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", str(cfg[campo])):
            raise ValueError(f"valor inválido en '{campo}': {cfg[campo]!r}")
    mut = cfg.get("mutacion")
    if mut is not None:
        if not isinstance(mut.get("archivos"), list) or not mut["archivos"]:
            raise ValueError("[mutacion] requiere 'archivos' (lista no vacía)")
        mut.setdefault("umbral", 0.8)
        mut.setdefault("max", 80)
    cfg.setdefault("base", "main")
    cfg.setdefault("timeout_min", 20)
    return cfg


def _glob_a_regex(patron: str) -> re.Pattern:
    salida, i = "", 0
    while i < len(patron):
        if patron.startswith("**", i):
            salida += ".*"
            i += 2
        elif patron[i] == "*":
            salida += "[^/]*"
            i += 1
        else:
            salida += re.escape(patron[i])
            i += 1
    return re.compile(salida + r"\Z")


def fuera_de_alcance(archivos: list[str], permitidos: list[str]) -> list[str]:
    """Devuelve los archivos que no calzan con ningún patrón permitido."""
    regexes = [_glob_a_regex(p) for p in list(permitidos) + SIEMPRE_PERMITIDOS]
    return [a for a in archivos if not any(r.match(a) for r in regexes)]


def decidir_resultado(*, timeout: bool, rc_opencode: int, commits: int, sucios: list[str],
                      fuera: list[str], oraculo_ok: bool, dependencias: list[str], secretos: bool,
                      puntaje_mutacion: float | None = None, umbral_mutacion: float = 0.0) -> str:
    """Veredicto único; el orden es el de gravedad."""
    if secretos:
        return "posible_secreto"
    if fuera:
        return "fuera_de_alcance"
    if dependencias:
        return "dependencia_nueva"
    if timeout:
        return "timeout"
    if commits == 0 and not sucios:
        return "sin_cambios" if rc_opencode == 0 else "error_opencode"
    if sucios:
        return "trabajo_sin_commitear"
    if not oraculo_ok:
        return "falla_oraculo"
    if puntaje_mutacion is not None and puntaje_mutacion < umbral_mutacion:
        return "tests_debiles"
    return "pasa"


def etapa(run: Path, texto: str) -> None:
    """Marcador de etapa legible para el visor (ver.py)."""
    with (run / "etapas.log").open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} ── {texto}\n")


@contextlib.contextmanager
def candado(nombre: str):
    """Exclusión entre procesos (despachos en paralelo) para operaciones que lockean el .git del repo."""
    carpeta = RUNS / ".locks"
    carpeta.mkdir(parents=True, exist_ok=True)
    with (carpeta / f"{nombre}.lock").open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def git(cwd: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falló: {r.stderr.strip()}")
    return r.stdout.strip()


def listar_sucios(wt: Path) -> list[str]:
    """Archivos sin commitear, uno por uno (-uall: sin esto git colapsa carpetas nuevas a 'docs/').
    Sin strip(): la primera línea puede empezar con un espacio (' M archivo') y se perdería una letra."""
    r = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=wt, capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git status falló: {r.stderr.strip()}")
    return [l[3:] for l in r.stdout.splitlines() if l]


def correr_oraculo(comandos: list[str], cwd: Path, repo: Path, log: Path) -> bool:
    ok = True
    with log.open("a", encoding="utf-8") as f:
        for cmd in comandos:
            cmd = cmd.replace("{repo}", str(repo))
            f.write(f"\n$ {cmd}\n")
            r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                               encoding="utf-8", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            f.write(r.stdout + r.stderr + f"[rc={r.returncode}]\n")
            ok = ok and r.returncode == 0
    return ok


def preparar_worktree(cfg: dict, repo: Path) -> tuple[Path, str, bool]:
    rama = f"opencode/{date.today().isoformat()}-{cfg['tema']}"
    wt = SRC / f"{cfg['proyecto']}-{cfg['tema']}"
    if wt.exists():
        return wt, git(wt, "branch", "--show-current"), True
    git(repo, "worktree", "add", str(wt), "-b", rama, cfg["base"])
    return wt, rama, False


ENTORNOS = (".venv", "node_modules")


def enlazar_entornos(repo: Path, wt: Path) -> list[str]:
    """Un worktree no trae .venv/node_modules (ignorados por git): se enlazan y se excluyen del status."""
    enlazados = []
    excluir = Path(git(wt, "rev-parse", "--git-path", "info/exclude"))
    excluir = excluir if excluir.is_absolute() else wt / excluir
    excluir.parent.mkdir(parents=True, exist_ok=True)
    previo = excluir.read_text(encoding="utf-8") if excluir.exists() else ""
    for nombre in ENTORNOS:
        if (repo / nombre).exists() and not (wt / nombre).exists():
            (wt / nombre).symlink_to(repo / nombre)
            enlazados.append(nombre)
            if f"/{nombre}" not in previo.splitlines():
                previo += f"/{nombre}\n"
    if enlazados:
        excluir.write_text(previo, encoding="utf-8")
    return enlazados


def cuerpo_encargo(texto: str) -> str:
    """El encargo sin su bloque de configuración +++ ... +++."""
    return re.sub(r"\A\s*\+\+\+\n.*?\n\+\+\+\n", "", texto, flags=re.S).strip()


def mensaje_para_opencode(texto_encargo: str, wt: Path, repo: Path | None = None) -> str:
    """El encargo va incrustado: OpenCode desatendido rechaza leer rutas fuera del worktree."""
    cuerpo = cuerpo_encargo(texto_encargo)
    if repo:
        cuerpo = cuerpo.replace(str(repo), str(wt))
    return ("Cargá la skill `delegacion-opencode` y seguila al pie de la letra. Tu encargo está abajo. "
            f"Trabajá solo en el worktree {wt} (ya está creado y es tu directorio actual). "
            "No leas ni escribas fuera de él. Al terminar dejá REPORTE.md en la raíz del worktree.\n\n"
            f"--- ENCARGO ---\n{cuerpo}")


def texto_final_de_eventos(lineas) -> str:
    """Texto de la respuesta final del agente a partir del stream --format json de OpenCode."""
    textos = []
    for linea in lineas:
        try:
            parte = json.loads(linea).get("part", {})
        except json.JSONDecodeError:
            continue
        if parte.get("type") == "text" and parte.get("text", "").strip():
            textos.append(parte["text"].strip())
    for t in reversed(textos):
        if "## Hallazgos" in t:
            return t
    return "\n\n".join(textos)


def resumir_revision(texto: str) -> dict:
    niveles = {n.lower() + "s": len(re.findall(rf"^\s*-\s*\[{n}\]", texto, re.M)) for n in ("ALTA", "MEDIA", "BAJA")}
    m = re.search(r"## Veredicto\s*\n+\s*(\w+)", texto)
    return {"veredicto": m.group(1) if m else None, **niveles}


def revisar(cfg: dict, texto_encargo: str, wt: Path, run: Path, base_ref: str) -> dict:
    """Etapa del revisor (solo lectura). Si deja el worktree distinto, se reporta como error."""
    antes = (git(wt, "rev-parse", "HEAD"), listar_sucios(wt))
    mensaje = (f"Revisá la rama {git(wt, 'branch', '--show-current')} contra {base_ref}. Empezá con "
               f"`git diff --stat {base_ref}..HEAD` y después `git diff {base_ref}..HEAD`.\n\n"
               f"El encargo que cumplía el trabajador era:\n{cuerpo_encargo(texto_encargo)}\n\n"
               "Respondé solo con el formato indicado en tus instrucciones.")
    cmd = ["opencode", "run", "--agent", "revisor", "--dir", str(wt), "--format", "json",
           "--title", f"rev-{cfg['id']}", mensaje]
    with (run / "revision.jsonl").open("w", encoding="utf-8") as out, \
         (run / "revision.err").open("w", encoding="utf-8") as err:
        try:
            subprocess.run(cmd, stdout=out, stderr=err, timeout=min(cfg["timeout_min"], 10) * 60,
                           stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return {"error": "el revisor excedió el tiempo"}
    if (git(wt, "rev-parse", "HEAD"), listar_sucios(wt)) != antes:
        return {"error": "el revisor modificó el worktree (es de solo lectura)"}
    texto = texto_final_de_eventos((run / "revision.jsonl").read_text(encoding="utf-8").splitlines())
    if not texto:
        return {"error": "el revisor no devolvió texto", "log": str(run / "revision.err")}
    (run / "revision.md").write_text(texto, encoding="utf-8")
    return {"archivo": str(run / "revision.md"), **resumir_revision(texto)}


def revisar_solo(ruta_encargo: Path) -> dict:
    """Corre solo el revisor sobre el worktree ya existente de un encargo."""
    texto = ruta_encargo.read_text(encoding="utf-8")
    cfg = parsear_encargo(texto)
    repo = Path(cfg["repo"]).expanduser()
    wt = SRC / f"{cfg['proyecto']}-{cfg['tema']}"
    if not wt.exists():
        raise ValueError(f"no existe el worktree {wt}")
    run = RUNS / f"{cfg['proyecto']}-{cfg['id']}" / "revision-manual"
    run.mkdir(parents=True, exist_ok=True)
    return {"id": cfg["id"], "proyecto": cfg["proyecto"], "resultado": "revision_manual",
            "revision": revisar(cfg, texto, wt, run, git(repo, "rev-parse", cfg["base"]))}


def despachar(ruta_encargo: Path, dry_run: bool = False, visor=None, reevaluar: bool = False) -> dict:
    texto = ruta_encargo.read_text(encoding="utf-8")
    cfg = parsear_encargo(texto)
    repo = Path(cfg["repo"]).expanduser()
    if not (repo / ".git").exists():
        raise ValueError(f"{repo} no es un repo git")

    run_base = RUNS / f"{cfg['proyecto']}-{cfg['id']}"
    ronda = 1 + sum(1 for r in run_base.glob("ronda-*") if (r / "opencode.jsonl").exists())
    if reevaluar:
        if ronda == 1:
            raise ValueError("no hay ninguna ronda ejecutada que reevaluar")
        ronda -= 1      # la última ronda ya ejecutada; no consume una nueva
    estado = {"id": cfg["id"], "proyecto": cfg["proyecto"], "agente": cfg["agente"], "ronda": ronda}
    if ronda > MAX_RONDAS and not reevaluar:
        estado["resultado"] = "tope_rondas"
        estado["nota"] = f"ya se hicieron {MAX_RONDAS} rondas: lo toma Claude (regla de calibre)"
        return estado
    run = run_base / ("reevaluacion" if reevaluar else f"ronda-{ronda}")
    run.mkdir(parents=True, exist_ok=True)
    (run / "FIN").unlink(missing_ok=True)
    estado["run"] = str(run)
    etapa(run, f"encargo {cfg['id']} · ronda {ronda} · agente {cfg['agente']}")
    pane = None
    if visor and not dry_run:
        pane = visor.abrir(f"{cfg['proyecto']}-{cfg['id']} r{ronda}",
                           [sys.executable, "-B", str(RAIZ / "ver.py"), str(run)], str(RAIZ))
    try:
        with candado(cfg["proyecto"]):
            sha_base_main = git(repo, "rev-parse", cfg["base"])
            wt, rama, reutilizado = preparar_worktree(cfg, repo)
            enlazados = enlazar_entornos(repo, wt)
        etapa(run, f"worktree listo · rama {rama}")
        estado.update(rama=rama, worktree=str(wt), reutilizado=reutilizado, entornos_enlazados=enlazados)
        if dry_run:
            estado["resultado"] = "dry_run"
            estado["mensaje"] = mensaje_para_opencode(texto, wt, repo)
            return estado

        log_oraculo = run / "oraculo.log"
        t0, timeout, rc = time.time(), False, 0
        if reevaluar:
            etapa(run, "reevaluación: no se vuelve a lanzar OpenCode (ni se gasta cuota ni una ronda)")
        else:
            etapa(run, "oráculo (antes)")
            estado["oraculo_antes"] = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo)
            if cfg.get("exige_baseline_verde") and not estado["oraculo_antes"]:
                estado["resultado"] = "baseline_rojo"
                estado["nota"] = "este encargo exige baseline verde para poder probar que no cambió el comportamiento"
                return estado

            etapa(run, f"OpenCode trabajando (máx {cfg['timeout_min']} min)")
            cmd = ["opencode", "run", "--agent", cfg["agente"], "--dir", str(wt), "--format", "json",
                   "--title", f"enc-{cfg['id']}-r{ronda}", mensaje_para_opencode(texto, wt, repo)]
            logger.info("lanzando: %s", shlex.join(cmd[:8]))
            with (run / "opencode.jsonl").open("w", encoding="utf-8") as out, \
                 (run / "opencode.err").open("w", encoding="utf-8") as err:
                try:
                    rc = subprocess.run(cmd, stdout=out, stderr=err, timeout=cfg["timeout_min"] * 60,
                                        stdin=subprocess.DEVNULL).returncode
                except subprocess.TimeoutExpired:
                    timeout, rc = True, -1
                    logger.error("OpenCode excedió %s min", cfg["timeout_min"])
            estado["duracion_s"] = round(time.time() - t0)

        base_ref = sha_base_main
        commits = int(git(wt, "rev-list", "--count", f"{base_ref}..HEAD") or 0)
        cambiados = set(git(wt, "diff", "--name-only", f"{base_ref}..HEAD").splitlines())
        sucios = listar_sucios(wt)
        cambiados |= set(sucios)
        diff = git(wt, "diff", f"{base_ref}..HEAD", check=False)
        añadidas = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        fuera = fuera_de_alcance(sorted(cambiados), cfg["permitidos"])
        dependencias = sorted(a for a in cambiados if Path(a).name in ARCHIVOS_DEPENDENCIAS)
        etapa(run, "oráculo (después) y verificación de alcance")
        oraculo_ok = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo)

        mut_cfg = cfg.get("mutacion")
        resumen_mut = None
        if mut_cfg and commits and oraculo_ok and not fuera and not sucios:
            etapa(run, "prueba de mutación")
            logger.info("prueba de mutación sobre %s", mut_cfg["archivos"])
            resumen_mut = mutacion.evaluar(wt, mut_cfg["archivos"], cfg["oraculo"], mut_cfg.get("funciones"),
                                           mut_cfg["max"])
            (run / "mutacion.json").write_text(json.dumps(resumen_mut, indent=2, ensure_ascii=False), encoding="utf-8")
        estado.update(
            commits=commits, archivos=sorted(cambiados), fuera_de_alcance=fuera, sin_commitear=sucios,
            dependencias_tocadas=dependencias, oraculo_despues=oraculo_ok,
            reporte=(wt / "REPORTE.md").exists(), rc_opencode=rc,
            main_intacto=git(repo, "rev-parse", cfg["base"]) == sha_base_main,
            resultado=decidir_resultado(timeout=timeout, rc_opencode=rc, commits=commits, sucios=sucios,
                                        fuera=fuera, oraculo_ok=oraculo_ok, dependencias=dependencias,
                                        secretos=bool(PATRON_SECRETO.search(añadidas)),
                                        puntaje_mutacion=(resumen_mut or {}).get("puntaje"),
                                        umbral_mutacion=(mut_cfg or {}).get("umbral", 0.0)),
        )
        if cfg.get("revisor") and estado["resultado"] in ("pasa", "tests_debiles"):
            etapa(run, "revisor (solo lectura)")
            logger.info("etapa de revisión (solo lectura)")
            estado["revision"] = revisar(cfg, texto, wt, run, base_ref)
        if resumen_mut:
            estado["mutacion"] = {k: resumen_mut[k] for k in ("total", "muertos", "puntaje") if k in resumen_mut}
            estado["mutacion"]["sobrevivientes"] = resumen_mut.get("sobrevivientes", [])[:15]
            if "error" in resumen_mut:
                estado["mutacion"]["error"] = resumen_mut["error"]
        return estado

    finally:
        etapa(run, f"veredicto: {estado.get('resultado')}")
        (run / "FIN").touch()
        if visor:
            visor.liberar(pane)

def crear_visor(pedido: bool):
    """Visor de Herdr solo si se pidió (--visor o ORQUESTADOR_VISOR=1) y estamos dentro de Herdr."""
    if not (pedido or os.environ.get("ORQUESTADOR_VISOR") == "1"):
        return None
    if not visor_herdr.disponible():
        logger.info("visor pedido, pero no corre dentro de Herdr: se omite")
        return None
    RUNS.mkdir(exist_ok=True)
    return visor_herdr.Visor(RUNS / ".visor.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encargo", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="prepara el worktree y muestra el mensaje, sin lanzar OpenCode")
    ap.add_argument("--visor", action="store_true", help="abre un panel en Herdr (solo si corre dentro de Herdr)")
    ap.add_argument("--reevaluar", action="store_true",
                    help="repite oráculo, alcance, mutación y revisor sobre el trabajo ya hecho, sin lanzar OpenCode")
    ap.add_argument("--revisar-solo", action="store_true", help="corre solo el revisor sobre el worktree existente")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        estado = (revisar_solo(args.encargo.resolve()) if args.revisar_solo
                  else despachar(args.encargo.resolve(), args.dry_run, crear_visor(args.visor), args.reevaluar))
    except Exception as e:
        logger.error("no se pudo despachar: %s", e, exc_info=True)
        estado = {"resultado": "error_despachador", "error": str(e)}
    if estado.get("run"):
        destino = Path(estado["run"]) / "estado.json"
        destino.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")
        estado["estado_json"] = str(destino)
    print(json.dumps(estado, indent=2, ensure_ascii=False))
    return 0 if estado.get("resultado") in ("pasa", "dry_run", "revision_manual") else 1


if __name__ == "__main__":
    sys.exit(main())
