#!/usr/bin/env python3
"""Despachador: ejecuta UN encargo de Claude en OpenCode y deja un veredicto en estado.json.

Claude (director) escribe el encargo; este script crea el worktree, lanza OpenCode sin pantalla,
corre el oráculo y verifica el alcance. Claude no teclea en ninguna terminal: lee estado.json.

Uso: despachar.py ENCARGO.md [--dry-run]
"""
import argparse
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
                      fuera: list[str], oraculo_ok: bool, dependencias: list[str], secretos: bool) -> str:
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
    return "pasa"


def git(cwd: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falló: {r.stderr.strip()}")
    return r.stdout.strip()


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


def mensaje_para_opencode(texto_encargo: str, wt: Path) -> str:
    """El encargo va incrustado: OpenCode desatendido rechaza leer rutas fuera del worktree."""
    cuerpo = re.sub(r"\A\s*\+\+\+\n.*?\n\+\+\+\n", "", texto_encargo, flags=re.S).strip()
    return ("Cargá la skill `delegacion-opencode` y seguila al pie de la letra. Tu encargo está abajo. "
            f"Trabajá solo en el worktree {wt} (ya está creado y es tu directorio actual). "
            "No leas ni escribas fuera de él. Al terminar dejá REPORTE.md en la raíz del worktree.\n\n"
            f"--- ENCARGO ---\n{cuerpo}")


def despachar(ruta_encargo: Path, dry_run: bool = False) -> dict:
    texto = ruta_encargo.read_text(encoding="utf-8")
    cfg = parsear_encargo(texto)
    repo = Path(cfg["repo"]).expanduser()
    if not (repo / ".git").exists():
        raise ValueError(f"{repo} no es un repo git")

    run_base = RUNS / f"{cfg['proyecto']}-{cfg['id']}"
    ronda = 1 + sum(1 for r in run_base.glob("ronda-*") if (r / "opencode.jsonl").exists())
    estado = {"id": cfg["id"], "proyecto": cfg["proyecto"], "agente": cfg["agente"], "ronda": ronda}
    if ronda > MAX_RONDAS:
        estado["resultado"] = "tope_rondas"
        estado["nota"] = f"ya se hicieron {MAX_RONDAS} rondas: lo toma Claude (regla de calibre)"
        return estado
    run = run_base / f"ronda-{ronda}"
    run.mkdir(parents=True, exist_ok=True)

    sha_base_main = git(repo, "rev-parse", cfg["base"])
    wt, rama, reutilizado = preparar_worktree(cfg, repo)
    estado.update(rama=rama, worktree=str(wt), reutilizado=reutilizado)
    if dry_run:
        estado["resultado"] = "dry_run"
        estado["mensaje"] = mensaje_para_opencode(texto, wt)
        return estado

    log_oraculo = run / "oraculo.log"
    estado["oraculo_antes"] = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo)

    cmd = ["opencode", "run", "--agent", cfg["agente"], "--dir", str(wt), "--format", "json",
           "--title", f"enc-{cfg['id']}-r{ronda}", mensaje_para_opencode(texto, wt)]
    logger.info("lanzando: %s", shlex.join(cmd[:8]))
    t0, timeout, rc = time.time(), False, 0
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
    sucios = [l[3:] for l in git(wt, "status", "--porcelain").splitlines()]
    cambiados |= set(sucios)
    diff = git(wt, "diff", f"{base_ref}..HEAD", check=False)
    añadidas = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    fuera = fuera_de_alcance(sorted(cambiados), cfg["permitidos"])
    dependencias = sorted(a for a in cambiados if Path(a).name in ARCHIVOS_DEPENDENCIAS)
    oraculo_ok = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo)

    estado.update(
        commits=commits, archivos=sorted(cambiados), fuera_de_alcance=fuera, sin_commitear=sucios,
        dependencias_tocadas=dependencias, oraculo_despues=oraculo_ok,
        reporte=(wt / "REPORTE.md").exists(), rc_opencode=rc,
        main_intacto=git(repo, "rev-parse", cfg["base"]) == sha_base_main,
        resultado=decidir_resultado(timeout=timeout, rc_opencode=rc, commits=commits, sucios=sucios,
                                    fuera=fuera, oraculo_ok=oraculo_ok, dependencias=dependencias,
                                    secretos=bool(PATRON_SECRETO.search(añadidas))),
    )
    return estado


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encargo", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="prepara el worktree y muestra el mensaje, sin lanzar OpenCode")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    try:
        estado = despachar(args.encargo.resolve(), args.dry_run)
    except Exception as e:
        logger.error("no se pudo despachar: %s", e, exc_info=True)
        estado = {"resultado": "error_despachador", "error": str(e)}
    if "proyecto" in estado and estado.get("resultado") != "tope_rondas":
        destino = RUNS / f"{estado['proyecto']}-{estado['id']}" / f"ronda-{estado['ronda']}" / "estado.json"
        destino.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")
        estado["estado_json"] = str(destino)
    print(json.dumps(estado, indent=2, ensure_ascii=False))
    return 0 if estado.get("resultado") in ("pasa", "dry_run") else 1


if __name__ == "__main__":
    sys.exit(main())
