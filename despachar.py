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
import shutil
import signal
import subprocess
import sys
import time
import tomllib
from datetime import date, datetime, timezone
from pathlib import Path

import mutacion
import visor as visor_herdr

logger = logging.getLogger("despachar")

RAIZ = Path(__file__).resolve().parent
RUNS = RAIZ / "runs"
SRC = Path.home() / "src"
MAX_RONDAS = 2
MAX_CUERPO_ENCARGO = 30_000
SIEMPRE_PERMITIDOS = ["REPORTE.md", "docs/opencode/**"]
ARCHIVOS_DEPENDENCIAS = {
    "requirements.txt", "requirements.in", "constraints.txt", "constraints.in", "pyproject.toml", "package.json", "package-lock.json",
    "poetry.lock", "Pipfile", "Pipfile.lock", "uv.lock", "pdm.lock",
    "yarn.lock", "pnpm-lock.yaml", "bun.lock", "bun.lockb",
    "Cargo.toml", "Cargo.lock", "go.mod", "go.sum",
    "Gemfile", "Gemfile.lock", "composer.json", "composer.lock",
    "mix.exs", "mix.lock", "gradle.lockfile", "build.gradle", "build.gradle.kts", "pom.xml",
    "Package.swift", "Podfile.lock", "pubspec.yaml", "pubspec.lock",
    "environment.yml", "environment.yaml", "conda-lock.yml", "setup.py", "setup.cfg",
}
PATRON_RUTA_ABSOLUTA = re.compile(
    r"(?<![A-Za-z0-9:/])/(?:home|tmp|mnt|etc|var|root|opt|usr|workspace|Users|private)/[^\s]+"
)
PATRON_SECRETO = re.compile(
    r"[\"']?(?:api[_-]?key|secret|token|password|passwd|access[_-]?key|private[_-]?key|client[_-]?secret)[\"']?"
    r"\s*[=:]\s*(?:['\"][^'\"\s]{8,}['\"]|[A-Za-z0-9_./+=-]{12,})"
    r"|-----BEGIN"
    r"|(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,})",
    re.I,
)
CAMPOS_OBLIGATORIOS = ("id", "proyecto", "repo", "agente", "tema", "permitidos", "oraculo")


def es_archivo_dependencias(ruta: str) -> bool:
    """Reconoce manifiestos y lockfiles comunes por nombre; no pretende cubrir todo ecosistema."""
    nombre = Path(ruta).name.lower()
    if nombre in {n.lower() for n in ARCHIVOS_DEPENDENCIAS}:
        return True
    return nombre.startswith(("requirements-", "requirements_", "constraints-", "constraints_")) and nombre.endswith((".txt", ".in"))


def posible_secreto(texto: str) -> bool:
    """Filtro heurístico para credenciales; un resultado negativo no garantiza ausencia de secretos."""
    return bool(PATRON_SECRETO.search(texto))


def parsear_encargo(texto: str) -> dict:
    """Extrae el bloque TOML entre líneas '+++' al inicio del encargo."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    m = re.match(r"\s*\+\+\+\n(.*?)\n\+\+\+", texto, re.S)
    if not m:
        raise ValueError("el encargo no tiene bloque +++ ... +++ con la configuración")
    cfg = tomllib.loads(m.group(1))
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in cfg]
    if faltan:
        raise ValueError(f"faltan campos en el encargo: {', '.join(faltan)}")
    for campo in ("proyecto", "tema", "id", "agente"):
        if not isinstance(cfg[campo], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", cfg[campo]):
            raise ValueError(f"'{campo}' debe ser una cadena con formato válido: {cfg[campo]!r}")
    mut = cfg.get("mutacion")
    if mut is not None:
        if not isinstance(mut, dict):
            raise ValueError("'mutacion' debe ser una tabla TOML")
        if not isinstance(mut.get("archivos"), list) or not mut["archivos"]:
            raise ValueError("[mutacion] requiere 'archivos' (lista no vacía)")
        mut.setdefault("umbral", 0.8)
        mut.setdefault("max", 80)
    cfg.setdefault("base", "main")
    cfg.setdefault("timeout_min", 20)
    if not isinstance(cfg["repo"], str) or not cfg["repo"].strip():
        raise ValueError("'repo' debe ser una ruta no vacía")
    if not isinstance(cfg["base"], str) or not cfg["base"].strip():
        raise ValueError("'base' debe ser una referencia Git no vacía")
    if not isinstance(cfg["permitidos"], list) or not cfg["permitidos"]:
        raise ValueError("'permitidos' debe ser una lista no vacía de patrones relativos")
    for patron in cfg["permitidos"]:
        if (not isinstance(patron, str) or not patron.strip() or patron.startswith(("~", "/"))
                or "\\" in patron or re.match(r"^[A-Za-z]:", patron)
                or ".." in Path(patron).parts):
            raise ValueError(f"patrón inseguro o inválido en 'permitidos': {patron!r}")
    inmutables = cfg.get("inmutables", [])
    if not isinstance(inmutables, list):
        raise ValueError("'inmutables' debe ser una lista de patrones relativos")
    for patron in inmutables:
        if (not isinstance(patron, str) or not patron.strip() or patron.startswith(("~", "/"))
                or "\\" in patron or re.match(r"^[A-Za-z]:", patron)
                or ".." in Path(patron).parts):
            raise ValueError(f"patrón inseguro o inválido en 'inmutables': {patron!r}")
    cfg["inmutables"] = inmutables
    if (not isinstance(cfg["oraculo"], list) or not cfg["oraculo"]
            or any(not isinstance(cmd, str) or not cmd.strip() for cmd in cfg["oraculo"])):
        raise ValueError("'oraculo' debe ser una lista no vacía de comandos no vacíos")
    for campo in ("revisor", "exige_baseline_verde"):
        if campo in cfg and not isinstance(cfg[campo], bool):
            raise ValueError(f"'{campo}' debe ser booleano")
    if not isinstance(cfg["timeout_min"], int) or isinstance(cfg["timeout_min"], bool) or cfg["timeout_min"] < 1:
        raise ValueError("'timeout_min' debe ser un entero positivo")
    cfg.setdefault("timeout_cola_min", cfg["timeout_min"] + 30)
    if (not isinstance(cfg["timeout_cola_min"], int) or isinstance(cfg["timeout_cola_min"], bool)
            or cfg["timeout_cola_min"] <= cfg["timeout_min"]):
        raise ValueError("'timeout_cola_min' debe ser un entero mayor que 'timeout_min'")
    cfg.setdefault("permitir_entornos_compartidos", False)
    if not isinstance(cfg["permitir_entornos_compartidos"], bool):
        raise ValueError("'permitir_entornos_compartidos' debe ser booleano")
    if mut is not None:
        umbral = mut["umbral"]
        max_mutantes = mut["max"]
        if not isinstance(umbral, (int, float)) or isinstance(umbral, bool) or not 0 <= umbral <= 1:
            raise ValueError("'mutacion.umbral' debe ser un número entre 0 y 1")
        if not isinstance(max_mutantes, int) or isinstance(max_mutantes, bool) or max_mutantes < 1:
            raise ValueError("'mutacion.max' debe ser un entero positivo")
        for archivo in mut["archivos"]:
            if (not isinstance(archivo, str) or not archivo.strip() or Path(archivo).is_absolute()
                    or "\\" in archivo or ".." in Path(archivo).parts):
                raise ValueError(f"ruta inválida en 'mutacion.archivos': {archivo!r}")
    return cfg


def rutas_absolutas_externas(texto: str, repo: Path) -> list[str]:
    """Detecta rutas absolutas comunes en el cuerpo que apuntan fuera del repo."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    bloque = re.match(r"\s*\+\+\+\n.*?\n\+\+\+\s*\n(.*)\Z", texto, re.S)
    cuerpo = bloque.group(1) if bloque else texto
    raiz = repo.expanduser().resolve()
    externas: set[str] = set()
    for coincidencia in PATRON_RUTA_ABSOLUTA.finditer(cuerpo):
        valor = coincidencia.group(0).rstrip(".,:;!?]})")
        if not valor:
            continue
        try:
            Path(valor).resolve().relative_to(raiz)
        except ValueError:
            externas.add(valor)
    return sorted(externas)


SHELL_BUILTINS = {
    ":", ".", "alias", "bg", "break", "cd", "command", "continue", "echo", "eval", "exec",
    "exit", "export", "false", "fg", "getopts", "jobs", "kill", "local", "printf", "pwd",
    "read", "readonly", "return", "set", "shift", "source", "test", "times", "trap", "true",
    "type", "ulimit", "umask", "unalias", "unset", "wait",
}


def validar_comando_oraculo(comando: str, repo: Path) -> tuple[str | None, str | None]:
    """Comprueba el ejecutable inicial cuando puede inferirse sin ejecutar el comando."""
    try:
        tokens = shlex.split(comando)
    except ValueError as exc:
        return f"comando de oráculo con comillas/sintaxis inválida: {exc}", None
    if not tokens:
        return "comando de oráculo vacío", None
    indice = 0
    while indice < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[indice]):
        indice += 1
    if indice >= len(tokens):
        return None, f"no se pudo inferir el ejecutable del oráculo: {comando}"
    ejecutable = tokens[indice]
    if ejecutable in SHELL_BUILTINS or ejecutable in {"if", "then", "else", "elif", "fi", "for", "while", "until", "case", "do", "done", "!", "{", "}"}:
        return None, f"el comando usa sintaxis de shell; su ejecutabilidad no se verifica estáticamente: {comando}"
    if any(ch in ejecutable for ch in ("$", "*", "?", "[")) or chr(96) in ejecutable:
        return None, f"el ejecutable depende de expansión de shell; no se verifica estáticamente: {comando}"
    if "/" in ejecutable:
        candidato = Path(ejecutable).expanduser()
        if not candidato.is_absolute():
            candidato = repo / candidato
        if not candidato.is_file() or not os.access(candidato, os.X_OK):
            return f"el ejecutable del oráculo no existe o no tiene permiso de ejecución: {ejecutable}", None
        return None, None
    if shutil.which(ejecutable) is None:
        return f"no se encuentra el ejecutable inicial del oráculo: {ejecutable}", None
    return None, None


def validar_encargo(ruta_encargo: Path, directorio_agentes: Path | None = None, solo_revisor: bool = False) -> dict:
    """Valida estáticamente un encargo; no crea worktrees, no corre el oráculo ni lanza modelos."""
    errores: list[str] = []
    advertencias: list[str] = []
    try:
        texto = ruta_encargo.read_text(encoding="utf-8")
        if len(texto) > MAX_CUERPO_ENCARGO:
            errores.append(f"el encargo supera el límite de {MAX_CUERPO_ENCARGO} caracteres")
        cfg = parsear_encargo(texto)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return {"resultado": "encargo_invalido", "valido": False, "errores": [str(exc)], "advertencias": []}

    repo = Path(cfg["repo"]).expanduser().resolve()
    for indice, comando in enumerate(cfg["oraculo"], start=1):
        error_comando, aviso_comando = validar_comando_oraculo(comando, repo)
        if error_comando:
            errores.append(f"oraculo[{indice}]: {error_comando}")
        if aviso_comando:
            advertencias.append(f"oraculo[{indice}]: {aviso_comando}")
    for ruta_externa in rutas_absolutas_externas(texto, repo):
        errores.append(f"el cuerpo contiene una ruta absoluta externa al repo: {ruta_externa}")
    if not repo.is_dir() or not (repo / ".git").exists():
        errores.append(f"'{cfg['repo']}' no es un repositorio Git accesible")
    else:
        base = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"{cfg['base']}^{{commit}}"],
            capture_output=True, text=True, encoding="utf-8",
        )
        if base.returncode != 0:
            errores.append(f"la referencia base '{cfg['base']}' no existe en el repositorio")
    agentes = directorio_agentes or (Path.home() / ".config" / "opencode" / "agents")
    requeridos = ["revisor"] if solo_revisor else [cfg["agente"]]
    if not solo_revisor and cfg.get("revisor"):
        requeridos.append("revisor")
    for agente in requeridos:
        if not (agentes / f"{agente}.md").is_file():
            errores.append(f"el agente '{agente}' no está instalado en {agentes}")
    if cfg["agente"] == "higiene" and not cfg.get("exige_baseline_verde", False):
        errores.append("los encargos del agente 'higiene' requieren exige_baseline_verde = true")
    if cfg.get("exige_baseline_verde"):
        advertencias.append("el baseline se ejecutará durante el despacho; --validar no ejecuta el oráculo")
    return {
        "resultado": "encargo_valido" if not errores else "encargo_invalido",
        "valido": not errores,
        "id": cfg["id"],
        "proyecto": cfg["proyecto"],
        "agente": cfg["agente"],
        "repo": str(repo),
        "base": cfg["base"],
        "errores": errores,
        "advertencias": advertencias,
    }


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


def violaciones_inmutables(archivos: list[str], inmutables: list[str]) -> list[str]:
    """Devuelve archivos cambiados que coinciden con patrones protegidos."""
    regexes = [_glob_a_regex(p) for p in inmutables]
    return sorted({a for a in archivos if any(r.match(a) for r in regexes)})


def decidir_resultado(*, timeout: bool, rc_opencode: int, commits: int, sucios: list[str],
                      fuera: list[str], oraculo_ok: bool, dependencias: list[str], secretos: bool,
                      inmutables: list[str] | None = None,
                      puntaje_mutacion: float | None = None, umbral_mutacion: float = 0.0,
                      error_mutacion: bool = False, sin_candidatos_mutacion: bool = False) -> str:
    """Veredicto único; el orden es el de gravedad."""
    if secretos:
        return "posible_secreto"
    if inmutables:
        return "viola_inmutables"
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
    if error_mutacion:
        return "error_mutacion"
    if sin_candidatos_mutacion:
        return "mutacion_sin_candidatos"
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


def ejecutar_proceso_con_timeout(cmd: list[str], *, cwd: Path, timeout_s: float,
                                 stdout, stderr, gracia_s: float = 5) -> tuple[int, bool]:
    """Ejecuta un proceso en su propio grupo y termina también a sus descendientes al vencer el plazo."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL, start_new_session=True
    )
    try:
        proc.wait(timeout=timeout_s)
        return proc.returncode, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        limite = time.monotonic() + gracia_s
        try:
            proc.wait(timeout=gracia_s)
        except subprocess.TimeoutExpired:
            pass
        # El proceso principal puede terminar mientras un hijo sigue vivo con el mismo grupo.
        while time.monotonic() < limite:
            try:
                os.killpg(proc.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(min(0.05, max(0, limite - time.monotonic())))
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return proc.returncode, True


def correr_oraculo(comandos: list[str], cwd: Path, repo: Path, log: Path,
                   timeout_s: float = 1200, gracia_s: float = 5) -> bool:
    """Ejecuta cada comando con límite propio; al vencer, termina todo su grupo de procesos."""
    ok = True
    with log.open("a", encoding="utf-8") as f:
        for cmd in comandos:
            cmd = cmd.replace("{repo}", str(repo))
            f.write(f"\n$ {cmd}\n")
            f.flush()
            proc = subprocess.Popen(
                cmd, shell=True, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, start_new_session=True,
            )
            try:
                salida, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, __import__("signal").SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    salida, _ = proc.communicate(timeout=gracia_s)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(proc.pid, __import__("signal").SIGKILL)
                    except ProcessLookupError:
                        pass
                    salida, _ = proc.communicate()
                f.write(salida or "")
                f.write(f"\n[timeout tras {timeout_s:g} segundos; grupo de procesos terminado]\n")
                f.flush()
                return False
            f.write(salida or "")
            f.write(f"[rc={proc.returncode}]\n")
            f.flush()
            ok = ok and proc.returncode == 0
    return ok


def preparar_worktree(cfg: dict, repo: Path, base_sha: str) -> tuple[Path, str, bool]:
    """Crea el worktree o valida la identidad del ya existente; nunca lo reutiliza a ciegas."""
    rama = f"opencode/{date.today().isoformat()}-{cfg['tema']}"
    wt = SRC / f"{cfg['proyecto']}-{cfg['tema']}"
    if wt.exists():
        raiz_wt = Path(git(wt, "rev-parse", "--show-toplevel")).resolve()
        if raiz_wt != wt.resolve():
            raise RuntimeError(f"el worktree existente resuelve a otra ruta: {raiz_wt}")
        rama_actual = git(wt, "branch", "--show-current")
        if not rama_actual.startswith("opencode/") or not rama_actual.endswith(f"-{cfg['tema']}"):
            raise RuntimeError(
                f"worktree reutilizado en rama inesperada {rama_actual!r}; "
                f"se esperaba una rama opencode/*-{cfg['tema']}"
            )
        # Evita aceptar una carpeta Git independiente que casualmente tenga el mismo nombre.
        comun_repo = Path(git(repo, "rev-parse", "--git-common-dir"))
        comun_wt = Path(git(wt, "rev-parse", "--git-common-dir"))
        if not comun_repo.is_absolute():
            comun_repo = repo / comun_repo
        if not comun_wt.is_absolute():
            comun_wt = wt / comun_wt
        if comun_repo.resolve() != comun_wt.resolve():
            raise RuntimeError("el worktree existente no pertenece al repositorio del encargo")
        return wt, rama_actual, True
    git(repo, "worktree", "add", str(wt), "-b", rama, base_sha)
    return wt, rama, False


def base_es_ancestro(base_sha: str, wt: Path) -> bool:
    """Comprueba que el worktree parte de la base fijada para esta corrida."""
    r = subprocess.run(["git", "merge-base", "--is-ancestor", base_sha, "HEAD"], cwd=wt,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode not in (0, 1):
        raise RuntimeError(f"no se pudo validar la base del worktree: {r.stderr.strip()}")
    return r.returncode == 0


ENTORNOS = (".venv", "node_modules")


def enlazar_entornos(repo: Path, wt: Path, permitir_compartidos: bool = False) -> list[str]:
    """Enlaza entornos del repo solo con opt-in explícito; los symlinks comparten acceso al host."""
    if not permitir_compartidos:
        return []
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
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
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
    m = re.search(r"(?m)^## Veredicto\s*\n([^\n]+)", texto)
    return {"veredicto": m.group(1).strip() if m else None, **niveles}


def validar_formato_revision(texto: str) -> dict:
    """Valida el contrato mínimo del revisor; no interpreta el contenido como verdad objetiva."""
    resumen = resumir_revision(texto)
    m = re.search(r"(?m)^## Veredicto\s*\n([^\n]+)", texto)
    h = re.search(r"(?ms)^## Hallazgos\s*\n(.*)\Z", texto)
    if not m or not h:
        return {"formato_valido": False, "error_formato": "faltan las secciones Veredicto o Hallazgos", **resumen}
    veredicto = m.group(1).strip()
    if veredicto not in ("APTO", "CON_OBSERVACIONES"):
        return {"formato_valido": False, "error_formato": "veredicto desconocido", **resumen}
    lineas = [line.strip() for line in h.group(1).splitlines() if line.strip()]
    if not lineas:
        return {"formato_valido": False, "error_formato": "la sección Hallazgos está vacía", **resumen}
    if lineas != ["- ninguno"]:
        patron = re.compile(r"^- \[(ALTA|MEDIA|BAJA)\] [^:\n]+:\d+ — .+ Evidencia: .+$")
        if not all(patron.match(linea) for linea in lineas):
            return {"formato_valido": False, "error_formato": "hallazgo fuera del formato requerido o sin evidencia", **resumen}
    if veredicto == "CON_OBSERVACIONES" and lineas == ["- ninguno"]:
        return {"formato_valido": False, "error_formato": "CON_OBSERVACIONES requiere al menos un hallazgo", **resumen}
    if veredicto == "APTO" and (resumen["altas"] or resumen["medias"]):
        return {"formato_valido": False, "error_formato": "APTO contradice hallazgos ALTA/MEDIA", **resumen}
    return {"formato_valido": True, **resumen}


def aprobar_revision(revision: dict | None) -> str:
    """Estado de aprobación separado del resultado técnico de tests/oráculo."""
    if not revision or revision.get("error"):
        return "revision_error"
    if not revision.get("formato_valido"):
        return "revision_formato_invalido"
    if revision.get("veredicto") == "CON_OBSERVACIONES":
        return "con_observaciones"
    if revision.get("veredicto") == "APTO":
        if revision.get("altas", 0) or revision.get("medias", 0):
            return "revision_inconsistente"
        return "aprobado"
    return "revision_formato_invalido"


def revisar(cfg: dict, texto_encargo: str, wt: Path, run: Path, base_ref: str) -> dict:
    """Etapa del revisor (solo lectura). Rechaza estado sucio y detecta mutaciones."""
    antes = (git(wt, "rev-parse", "HEAD"), listar_sucios(wt))
    if antes[1]:
        return {"error": "revisión bloqueada: el worktree contiene cambios sin commitear",
                "archivos_sucios": antes[1]}
    mensaje = (f"Revisá la rama {git(wt, 'branch', '--show-current')} contra {base_ref}. Empezá con "
               f"`git diff --stat {base_ref}..HEAD` y después `git diff {base_ref}..HEAD`.\n\n"
               f"El encargo que cumplía el trabajador era:\n{cuerpo_encargo(texto_encargo)}\n\n"
               "Respondé solo con el formato indicado en tus instrucciones.")
    cmd = ["opencode", "run", "--agent", "revisor", "--dir", str(wt), "--format", "json",
           "--title", f"rev-{cfg['id']}", mensaje]
    error_proceso = None
    proc = None
    codigo_revision = None
    with (run / "revision.jsonl").open("w", encoding="utf-8") as out, \
         (run / "revision.err").open("w", encoding="utf-8") as err:
        codigo_revision, agotado = ejecutar_proceso_con_timeout(
            cmd, cwd=wt, timeout_s=min(cfg["timeout_min"], 10) * 60, stdout=out, stderr=err
        )
        if agotado:
            error_proceso = "el revisor excedió el tiempo; se terminó el grupo de procesos"
    # Comprobar el worktree incluso tras timeout o salida no cero: el fallo no debe ocultar mutaciones.
    if (git(wt, "rev-parse", "HEAD"), listar_sucios(wt)) != antes:
        return {"error": "el revisor modificó el worktree (es de solo lectura)"}
    if error_proceso:
        return {"error": error_proceso}
    if codigo_revision != 0:
        return {"error": f"el revisor terminó con código {codigo_revision}"}
    texto = texto_final_de_eventos((run / "revision.jsonl").read_text(encoding="utf-8").splitlines())
    if not texto:
        return {"error": "el revisor no devolvió texto", "log": str(run / "revision.err")}
    (run / "revision.md").write_text(texto, encoding="utf-8")
    return {"archivo": str(run / "revision.md"), **validar_formato_revision(texto)}


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
    revision = revisar(cfg, texto, wt, run, git(repo, "rev-parse", cfg["base"]))
    return {"id": cfg["id"], "proyecto": cfg["proyecto"], "resultado": "revision_manual",
            "revision": revision, "aprobacion": aprobar_revision(revision)}


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
            wt, rama, reutilizado = preparar_worktree(cfg, repo, sha_base_main)
            enlazados = enlazar_entornos(repo, wt, cfg["permitir_entornos_compartidos"])
        etapa(run, f"worktree listo · rama {rama}")
        head_inicio = git(wt, "rev-parse", "HEAD")
        estado.update(rama=rama, worktree=str(wt), reutilizado=reutilizado, entornos_enlazados=enlazados,
                      permitir_entornos_compartidos=cfg.get("permitir_entornos_compartidos", False),
                      base_ref=cfg["base"], base_sha=sha_base_main, head_sha_inicio=head_inicio)
        if not base_es_ancestro(sha_base_main, wt):
            estado["resultado"] = "worktree_base_divergente"
            estado["nota"] = ("la base fijada al inicio no es ancestro del HEAD del worktree; "
                              "no se ejecutó el agente para evitar comparar contra una historia incompatible")
            estado["base_sha_actual_fin"] = git(repo, "rev-parse", cfg["base"])
            estado["base_movida"] = estado["base_sha_actual_fin"] != sha_base_main
            return estado
        sucios_inicio = listar_sucios(wt)
        if reutilizado and sucios_inicio:
            estado["resultado"] = "worktree_reutilizado_sucio"
            estado["archivos_sucios_inicio"] = sucios_inicio
            estado["nota"] = ("el worktree reutilizado contiene cambios sin commitear; se bloquea el encargo "
                              "para no mezclar trabajo anterior ni ejecutar el oráculo sobre un estado ambiguo")
            return estado
        if dry_run:
            estado["resultado"] = "dry_run"
            estado["mensaje"] = mensaje_para_opencode(texto, wt, repo)
            estado["head_sha_fin"] = git(wt, "rev-parse", "HEAD")
            estado["base_sha_actual_fin"] = git(repo, "rev-parse", cfg["base"])
            estado["base_movida"] = estado["base_sha_actual_fin"] != sha_base_main
            return estado

        log_oraculo = run / "oraculo.log"
        t0, timeout, rc = time.time(), False, 0
        if reevaluar:
            etapa(run, "reevaluación: no se vuelve a lanzar OpenCode (ni se gasta cuota ni una ronda)")
        else:
            etapa(run, "oráculo (antes)")
            estado["oraculo_antes"] = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo, timeout_s=cfg["timeout_min"] * 60)
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
                rc, timeout = ejecutar_proceso_con_timeout(
                    cmd, cwd=wt, timeout_s=cfg["timeout_min"] * 60, stdout=out, stderr=err
                )
                if timeout:
                    rc = -1
                    logger.error("OpenCode excedió %s min; se terminó el grupo de procesos", cfg["timeout_min"])
            estado["duracion_s"] = round(time.time() - t0)

        base_ref = sha_base_main
        commits = int(git(wt, "rev-list", "--count", f"{base_ref}..HEAD") or 0)
        # Sin detección de renombres: al mover un archivo protegido, deben verse
        # tanto la ruta de origen como la de destino para no eludir inmutables.
        cambiados = set(git(wt, "diff", "--name-only", "--no-renames", f"{base_ref}..HEAD").splitlines())
        sucios = listar_sucios(wt)
        cambiados |= set(sucios)
        diff = git(wt, "diff", f"{base_ref}..HEAD", check=False)
        añadidas = "\n".join(l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        fuera = fuera_de_alcance(sorted(cambiados), cfg["permitidos"])
        protegidos = violaciones_inmutables(sorted(cambiados), cfg.get("inmutables", []))
        dependencias = sorted(a for a in cambiados if es_archivo_dependencias(a))
        etapa(run, "oráculo (después) y verificación de alcance")
        oraculo_ok = correr_oraculo(cfg["oraculo"], wt, repo, log_oraculo, timeout_s=cfg["timeout_min"] * 60)

        mut_cfg = cfg.get("mutacion")
        resumen_mut = None
        if mut_cfg and commits and oraculo_ok and not fuera and not sucios:
            etapa(run, "prueba de mutación")
            logger.info("prueba de mutación sobre %s", mut_cfg["archivos"])
            try:
                resumen_mut = mutacion.evaluar(wt, mut_cfg["archivos"], cfg["oraculo"], mut_cfg.get("funciones"),
                                               mut_cfg["max"])
            except Exception as exc:
                logger.exception("falló la evaluación de mutación")
                resumen_mut = {"error": f"excepción durante la evaluación de mutación: {exc}",
                               "total": 0, "universo": 0, "puntaje": None, "sobrevivientes": []}
            (run / "mutacion.json").write_text(json.dumps(resumen_mut, indent=2, ensure_ascii=False), encoding="utf-8")
        head_fin = git(wt, "rev-parse", "HEAD")
        base_sha_fin = git(repo, "rev-parse", cfg["base"])
        estado.update(
            commits=commits, archivos=sorted(cambiados), fuera_de_alcance=fuera,
            archivos_inmutables=protegidos, sin_commitear=sucios,
            dependencias_tocadas=dependencias, oraculo_despues=oraculo_ok,
            reporte=(wt / "REPORTE.md").exists(), rc_opencode=rc,
            head_sha_fin=head_fin,
            base_sha_actual_fin=base_sha_fin,
            base_movida=base_sha_fin != sha_base_main,
            main_intacto=base_sha_fin == sha_base_main,
            resultado=decidir_resultado(timeout=timeout, rc_opencode=rc, commits=commits, sucios=sucios,
                                        fuera=fuera, oraculo_ok=oraculo_ok, dependencias=dependencias,
                                        secretos=posible_secreto(añadidas), inmutables=protegidos,
                                        puntaje_mutacion=(resumen_mut or {}).get("puntaje"),
                                        umbral_mutacion=(mut_cfg or {}).get("umbral", 0.0),
                                        error_mutacion=bool((resumen_mut or {}).get("error")),
                                        sin_candidatos_mutacion=bool(
                                            mut_cfg and resumen_mut and not resumen_mut.get("error")
                                            and resumen_mut.get("total", 0) == 0
                                        )),
        )
        estado["aprobacion"] = "no_requerida"
        if cfg.get("revisor"):
            if estado["resultado"] in ("pasa", "tests_debiles"):
                etapa(run, "revisor (solo lectura)")
                logger.info("etapa de revisión (solo lectura)")
                estado["revision"] = revisar(cfg, texto, wt, run, base_ref)
                estado["aprobacion"] = aprobar_revision(estado["revision"])
            else:
                estado["aprobacion"] = "bloqueado_por_resultado_tecnico"
        if resumen_mut:
            estado["mutacion"] = {k: resumen_mut[k] for k in ("total", "muertos", "puntaje") if k in resumen_mut}
            estado["mutacion"]["sobrevivientes"] = resumen_mut.get("sobrevivientes", [])[:15]
            if "error" in resumen_mut:
                estado["mutacion"]["error"] = resumen_mut["error"]
        return estado

    finally:
        # También deja trazabilidad en salidas tempranas (p. ej. baseline_rojo o base divergente).
        if "wt" in locals() and wt.exists():
            try:
                estado.setdefault("head_sha_fin", git(wt, "rev-parse", "HEAD"))
            except Exception as e:
                estado.setdefault("error_snapshot_head", str(e))
        if "sha_base_main" in locals():
            estado.setdefault("base_ref", cfg["base"])
            estado.setdefault("base_sha", sha_base_main)
            try:
                base_sha_fin = git(repo, "rev-parse", cfg["base"])
                estado.setdefault("base_sha_actual_fin", base_sha_fin)
                estado.setdefault("base_movida", base_sha_fin != sha_base_main)
                estado.setdefault("main_intacto", base_sha_fin == sha_base_main)
            except Exception as e:
                estado.setdefault("error_snapshot_base", str(e))
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


ACCIONES_SIGUIENTES = {
    "pasa": "Revisar diff, reporte y evidencia antes de integrar manualmente.",
    "sin_cambios": "Confirmar si el encargo ya estaba satisfecho o si faltó trabajo.",
    "error_opencode": "Inspeccionar opencode.err y el estado del worktree antes de reintentar.",
    "timeout": "Inspeccionar logs; dividir el encargo o ajustar timeout_min.",
    "timeout_despachador": "Inspeccionar el diagnóstico de la cola y comprobar que no queden procesos.",
    "error_despachador": "Leer stderr y corregir el error de infraestructura antes de reintentar.",
    "error_cola": "Inspeccionar el error del runner y la configuración del encargo.",
    "encargo_invalido": "Corregir los errores de validación antes de volver a despachar.",
    "baseline_rojo": "Restaurar o explicar el baseline rojo; no ejecutar el trabajador hasta resolverlo.",
    "worktree_base_divergente": "Preservar cambios y recrear el worktree desde una base compatible.",
    "worktree_reutilizado_sucio": "Inspeccionar los cambios preexistentes; preservarlos o limpiarlos explícitamente antes de reintentar.",
    "fuera_de_alcance": "Revisar y revertir los archivos fuera del alcance autorizado.",
    "viola_inmutables": "Restaurar los archivos protegidos; el encargo no autoriza modificarlos, borrarlos ni renombrarlos.",
    "posible_secreto": "Retirar la credencial, revisar su exposición y rotarla si corresponde.",
    "dependencia_nueva": "Revisar y autorizar explícitamente los cambios de dependencias.",
    "trabajo_sin_commitear": "Pedir al trabajador que commitee o descarte sus cambios y reevaluar.",
    "falla_oraculo": "Inspeccionar oraculo.log y corregir los fallos de verificación.",
    "tests_debiles": "Revisar mutantes sobrevivientes y fortalecer las pruebas.",
    "error_mutacion": "Inspeccionar mutacion.json; la evaluación de mutación falló y no debe considerarse aprobada.",
    "mutacion_sin_candidatos": "Revisar archivos/funciones configurados: no se encontró ningún candidato de mutación.",
    "tope_rondas": "Entregar el caso a Claude para revisión humana y definir el siguiente encargo.",
    "revision_manual": "Leer revision.md y resolver observaciones antes de integrar.",
    "revision_invalida": "Revisar el formato y la evidencia del informe del revisor.",
    "error_estado_invalido": "Corregir la construcción del estado antes de confiar en el veredicto.",
}


def normalizar_estado(estado: dict, inicio_utc: str) -> dict:
    """Añade metadatos versionados y una acción siguiente explícita a toda corrida."""
    estado.setdefault("schema_version", 1)
    estado.setdefault("inicio_utc", inicio_utc)
    estado["fin_utc"] = datetime.now(timezone.utc).isoformat()
    resultado = estado.get("resultado", "error_despachador")
    aprobacion = estado.get("aprobacion", "no_requerida")
    if resultado == "revision_manual" and aprobacion == "revision_error" and estado.get("revision", {}).get("archivos_sucios"):
        estado["siguiente_accion"] = "Commitear o descartar explícitamente los cambios antes de pedir revisión."
    elif aprobacion not in ("no_requerida", "aprobado") and resultado in ("pasa", "revision_manual"):
        estado["siguiente_accion"] = "Resolver el bloqueo del revisor antes de integrar; consultar el detalle de revision."
    else:
        estado["siguiente_accion"] = ACCIONES_SIGUIENTES.get(
            resultado, "Inspeccionar estado.json y los logs asociados antes de continuar."
        )
    return estado


def validar_estado_v1(estado: dict) -> list[str]:
    """Valida el contrato mínimo de estado.v1 con la biblioteca estándar."""
    errores = []
    requeridos = ("schema_version", "inicio_utc", "fin_utc", "resultado", "siguiente_accion")
    for campo in requeridos:
        if campo not in estado:
            errores.append(f"falta el campo obligatorio '{campo}'")
    if estado.get("schema_version") != 1 or isinstance(estado.get("schema_version"), bool):
        errores.append("'schema_version' debe ser el entero 1")
    for campo in ("resultado", "siguiente_accion"):
        if not isinstance(estado.get(campo), str) or not estado[campo].strip():
            errores.append(f"'{campo}' debe ser una cadena no vacía")
    for campo in ("inicio_utc", "fin_utc"):
        valor = estado.get(campo)
        if not isinstance(valor, str):
            errores.append(f"'{campo}' debe ser una fecha ISO-8601 con zona horaria")
            continue
        try:
            fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            if fecha.tzinfo is None or fecha.utcoffset() is None:
                raise ValueError("falta zona horaria")
        except ValueError:
            errores.append(f"'{campo}' debe ser una fecha ISO-8601 con zona horaria")
    return errores


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encargo", type=Path)
    ap.add_argument("--validar", action="store_true",
                    help="valida configuración, repo, base y agente sin crear worktree ni ejecutar comandos del oráculo")
    ap.add_argument("--dry-run", action="store_true", help="prepara el worktree y muestra el mensaje, sin lanzar OpenCode")
    ap.add_argument("--visor", action="store_true", help="abre un panel en Herdr (solo si corre dentro de Herdr)")
    ap.add_argument("--reevaluar", action="store_true",
                    help="repite oráculo, alcance, mutación y revisor sobre el trabajo ya hecho, sin lanzar OpenCode")
    ap.add_argument("--revisar-solo", action="store_true", help="corre solo el revisor sobre el worktree existente")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if args.validar:
        try:
            estado = validar_encargo(args.encargo.resolve(), solo_revisor=args.revisar_solo)
        except Exception as exc:
            estado = {"resultado": "encargo_invalido", "valido": False,
                      "errores": [f"falló el preflight: {exc}"], "advertencias": []}
        print(json.dumps(estado, indent=2, ensure_ascii=False))
        return 0 if estado["valido"] else 1
    inicio_utc = datetime.now(timezone.utc).isoformat()
    try:
        ruta = args.encargo.resolve()
        preflight = validar_encargo(ruta, solo_revisor=args.revisar_solo)
        if not preflight["valido"]:
            estado = {"resultado": "encargo_invalido", "errores": preflight["errores"],
                      "advertencias": preflight["advertencias"]}
        else:
            estado = (revisar_solo(ruta) if args.revisar_solo
                      else despachar(ruta, args.dry_run, crear_visor(args.visor), args.reevaluar))
    except Exception as e:
        logger.error("no se pudo despachar: %s", e, exc_info=True)
        estado = {"resultado": "error_despachador", "error": str(e)}
    estado = normalizar_estado(estado, inicio_utc)
    errores_esquema = validar_estado_v1(estado)
    if errores_esquema:
        estado["resultado"] = "error_estado_invalido"
        estado["errores_estado_schema"] = errores_esquema
        estado["siguiente_accion"] = "Corregir la construcción del estado antes de confiar en el veredicto."
    if estado.get("run"):
        destino = Path(estado["run"]) / "estado.json"
        estado["estado_json"] = str(destino)
        destino.write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(estado, indent=2, ensure_ascii=False))
    return 0 if (estado.get("resultado") in ("pasa", "dry_run", "revision_manual")
                and estado.get("aprobacion", "no_requerida") in ("no_requerida", "aprobado")) else 1


if __name__ == "__main__":
    sys.exit(main())
