"""Reglas de alcance y heurísticas de seguridad sobre los archivos que toca un trabajador."""
from __future__ import annotations

import re
from pathlib import Path

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


PATRON_ASIGNACION_SECRETO = re.compile(
    r"[\"']?(?:api[_-]?key|secret|token|password|passwd|access[_-]?key|private[_-]?key|client[_-]?secret)[\"']?"
    r"\s*[=:]\s*(?:(?P<q>['\"])(?P<vq>[^'\"\s]{8,})(?P=q)|(?P<vu>[A-Za-z0-9_./+=-]{12,}))",
    re.I,
)


PATRON_TOKEN_PROVEEDOR = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{10,})"
    r"|-----BEGIN|\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)


MARCAS_NO_SECRETO = ("test", "mock", "fake", "dummy", "example", "sample", "placeholder", "changeme",
                     "prueba", "csrf", "xxxx", "your_", "your-", "<", "${", "{{", "process.env", "environ")


def es_archivo_dependencias(ruta: str) -> bool:
    """Reconoce manifiestos y lockfiles comunes por nombre; no pretende cubrir todo ecosistema."""
    nombre = Path(ruta).name.lower()
    if nombre in {n.lower() for n in ARCHIVOS_DEPENDENCIAS}:
        return True
    return nombre.startswith(("requirements-", "requirements_", "constraints-", "constraints_")) and nombre.endswith((".txt", ".in"))


def posible_secreto(texto: str) -> bool:
    """Filtro heurístico para credenciales; un resultado negativo no garantiza ausencia de secretos."""
    if PATRON_TOKEN_PROVEEDOR.search(texto):
        return True
    for m in PATRON_ASIGNACION_SECRETO.finditer(texto):
        valor = m.group("vq") or m.group("vu")
        if any(marca in valor.lower() for marca in MARCAS_NO_SECRETO):
            continue
        # Sin comillas, una expresión (os.environ.get, actor.csrfToken) no es un literal: exigir un dígito.
        if m.group("vu") and not re.search(r"\d", valor):
            continue
        return True
    return False


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
