"""Registro de procesos hijos lanzados en su propio grupo, para no dejar huérfanos al recibir SIGTERM.

Cada hijo se crea con start_new_session (así el timeout puede matar a toda su descendencia), pero
eso lo deja fuera del grupo del padre: si el padre muere por SIGTERM, el hijo sigue corriendo
(visto con `nocturna.py` → `cola.py` → `despachar.py` → `opencode`). Con este registro, el manejador
de SIGTERM termina todos los grupos vivos antes de salir.
"""
from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time

_activos: set[subprocess.Popen] = set()
_cerrojo = threading.Lock()


def lanzar(*args, **kwargs) -> subprocess.Popen:
    kwargs.setdefault("start_new_session", True)
    proc = subprocess.Popen(*args, **kwargs)
    with _cerrojo:
        _activos.add(proc)
    return proc


def terminar_activos(gracia_s: float = 3) -> int:
    """SIGTERM a cada grupo vivo, espera `gracia_s` y escala a SIGKILL. Devuelve cuántos había."""
    with _cerrojo:
        vivos = [p for p in _activos if p.poll() is None]
        _activos.clear()
    for p in vivos:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(p.pid, signal.SIGTERM)
    limite = time.time() + gracia_s
    while time.time() < limite and any(p.poll() is None for p in vivos):
        time.sleep(0.1)
    for p in vivos:
        if p.poll() is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(p.pid, signal.SIGKILL)
    return len(vivos)


def _al_recibir_sigterm(signum, frame):
    terminar_activos()
    raise SystemExit(128 + signum)


def instalar_manejador() -> None:
    signal.signal(signal.SIGTERM, _al_recibir_sigterm)
