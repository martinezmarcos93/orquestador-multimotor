"""Confinamiento opcional del trabajador con bubblewrap (bwrap).

Aísla el sistema de archivos y el entorno, NO la red: OpenCode necesita llegar al proxy
LiteLLM en 127.0.0.1, así que la red se comparte. Qué se ve dentro:
  - /usr, /etc, /proc, /dev (solo lectura / mínimos) y un /tmp y un $HOME vacíos (tmpfs);
  - el worktree y el .git común del repo (lectura/escritura, para poder commitear);
  - el binario y la configuración de OpenCode (solo lectura), sin su base de datos ni auth.json;
  - rutas extra de solo lectura (p. ej. la guía de metodologías referida en `instructions`).
El entorno se limpia: solo PATH, HOME, LANG, TERM y las variables de `ENTORNO_PERMITIDO`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

MODOS = ("ninguno", "bwrap")
ENTORNO_PERMITIDO = ("LITELLM_MASTER_KEY",)


def modo_por_defecto() -> str:
    return os.environ.get("ORQUESTADOR_SANDBOX", "ninguno")


def instrucciones_opencode() -> list[Path]:
    """Rutas absolutas de `instructions` en opencode.jsonc (se montan de solo lectura)."""
    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    try:
        lineas = [l for l in cfg.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("//")]
        datos = json.loads("\n".join(lineas))
    except (OSError, ValueError):
        return []
    return [Path(r) for r in datos.get("instructions", []) if isinstance(r, str) and r.startswith("/")]


def disponible() -> bool:
    """True si bwrap existe y puede crear un espacio de nombres de usuario aquí."""
    exe = shutil.which("bwrap")
    if not exe:
        return False
    try:
        r = subprocess.run([exe, "--ro-bind", "/", "/", "true"], capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0


def _git_comun(wt: Path) -> Path:
    r = subprocess.run(["git", "-C", str(wt), "rev-parse", "--git-common-dir"],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    p = Path(r.stdout.strip())
    return (p if p.is_absolute() else wt / p).resolve()


def envolver(cmd: list[str], *, wt: Path, datos: Path, ro_extra: list[Path] | None = None,
             herramientas: list[Path] | None = None) -> list[str]:
    """Devuelve el comando `cmd` ejecutado dentro de bwrap. `datos` es un directorio escribible
    propio de la corrida que hace de ~/.local/share/opencode (se crea vacío). `herramientas` son
    prefijos (p. ej. ~/.nvm/versions/node/v24.20.0) que se montan de solo lectura y aportan su `bin/` al PATH."""
    home = Path.home()
    exe = shutil.which("bwrap") or "bwrap"  # la ausencia la detecta el preflight (disponible())
    datos.mkdir(parents=True, exist_ok=True)
    rutas_ro = [Path("/usr"), Path("/etc"), home / ".opencode", home / ".config" / "opencode"]
    rutas_ro += [Path(p) for p in (ro_extra if ro_extra is not None else instrucciones_opencode())]
    herramientas = [Path(h).expanduser().resolve() for h in (herramientas or [])]
    rutas_ro += herramientas
    argv = [exe, "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc",
            "--unshare-uts", "--clearenv"]
    for d in ("/bin", "/lib", "/lib64", "/sbin"):
        if os.path.islink(d):
            argv += ["--symlink", os.readlink(d), d]
    argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--tmpfs", str(home)]
    for p in rutas_ro:
        if p.exists():
            argv += ["--ro-bind", str(p), str(p)]
    argv += ["--bind", str(wt), str(wt), "--bind", str(_git_comun(wt)), str(_git_comun(wt)),
             "--bind", str(datos), str(home / ".local" / "share" / "opencode"),
             "--chdir", str(wt)]
    bins = ":".join(str(h / "bin") for h in herramientas)
    env = {"PATH": ":".join(x for x in (f"{home}/.opencode/bin", bins, "/usr/local/bin", "/usr/bin", "/bin") if x), "HOME": str(home),
           "LANG": os.environ.get("LANG", "C.UTF-8"), "TERM": "dumb"}
    env.update({k: os.environ[k] for k in ENTORNO_PERMITIDO if k in os.environ})
    for k, v in env.items():
        argv += ["--setenv", k, v]
    return argv + ["--"] + cmd
