"""Visor opcional en Herdr: una pestaña propia 'orquestador' con un panel por corrida.

Reglas (skill oficial de Herdr): solo opera si el proceso corre DENTRO de Herdr (HERDR_ENV=1),
siempre con --no-focus, no toca paneles ajenos y solo reutiliza/cierra los suyos. Si algo falla
devuelve None: el visor nunca bloquea un despacho.
"""
import fcntl
import json
import logging
import os
import shlex
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("visor")

ETIQUETA = "orquestador"
MAX_PANELES = 4


def disponible(env=os.environ) -> bool:
    return env.get("HERDR_ENV") == "1" and bool(env.get("HERDR_WORKSPACE_ID")) and shutil.which("herdr") is not None


def _herdr_real(*args: str) -> dict | None:
    r = subprocess.run(["herdr", *args], capture_output=True, text=True, encoding="utf-8", timeout=20)
    if r.returncode != 0:
        logger.warning("herdr %s falló: %s", " ".join(args[:2]), (r.stderr or r.stdout).strip()[:200])
        return None
    if not r.stdout.strip():          # p. ej. `pane run` responde rc 0 con stdout vacío
        return {}
    return json.loads(r.stdout).get("result", {})


class Visor:
    def __init__(self, estado_json: Path, workspace: str | None = None, herdr=_herdr_real):
        self.estado_json = Path(estado_json)
        self.workspace = workspace or os.environ.get("HERDR_WORKSPACE_ID", "")
        self.herdr = herdr

    def _cargar(self) -> dict:
        try:
            return json.loads(self.estado_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"tab_id": None, "paneles": {}}

    def _guardar(self, estado: dict) -> None:
        self.estado_json.write_text(json.dumps(estado, indent=2), encoding="utf-8")

    def _paneles_vivos(self, tab_id: str) -> list[str]:
        r = self.herdr("pane", "list", "--workspace", self.workspace) or {}
        return [p["pane_id"] for p in r.get("panes", []) if p.get("tab_id") == tab_id]

    def _asegurar_tab(self, estado: dict, cwd: str) -> str | None:
        r = self.herdr("tab", "list", "--workspace", self.workspace) or {}
        for t in r.get("tabs", []):
            if t.get("label") == ETIQUETA:
                if estado.get("tab_id") != t["tab_id"]:
                    estado.update(tab_id=t["tab_id"], paneles={})
                return t["tab_id"]
        r = self.herdr("tab", "create", "--workspace", self.workspace, "--label", ETIQUETA, "--cwd", cwd, "--no-focus")
        if not r:
            return None
        estado.update(tab_id=r["tab"]["tab_id"], paneles={r["root_pane"]["pane_id"]: {"estado": "libre", "nuevo": True}})
        return estado["tab_id"]

    def abrir(self, titulo: str, comando: list[str], cwd: str) -> str | None:
        """Abre (o reutiliza) un panel y le corre `comando`. Devuelve el pane_id o None."""
        try:
            self.estado_json.parent.mkdir(parents=True, exist_ok=True)
            with open(str(self.estado_json) + ".lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                estado = self._cargar()
                tab_id = self._asegurar_tab(estado, cwd)
                if not tab_id:
                    return None
                vivos = self._paneles_vivos(tab_id)
                paneles = {p: estado["paneles"].get(p, {"estado": "libre"}) for p in vivos}
                pane = next((p for p, v in paneles.items() if v["estado"] == "libre"), None)
                reutilizado = pane is not None and not paneles[pane].get("nuevo", False)
                if pane is None:
                    if len(vivos) >= MAX_PANELES:
                        logger.info("visor: %d paneles ocupados, esta corrida sigue sin panel", len(vivos))
                        estado["paneles"] = paneles
                        self._guardar(estado)
                        return None
                    r = self.herdr("pane", "split", vivos[-1], "--direction", "right" if len(vivos) == 1 else "down",
                                   "--cwd", cwd, "--no-focus")
                    if not r:
                        return None
                    pane = r["pane"]["pane_id"]
                # primero se reserva el panel y se persiste: si algo falla después, nadie más lo pisa
                paneles[pane] = {"estado": "activo", "titulo": titulo}
                estado["paneles"] = paneles
                self._guardar(estado)
                self.herdr("pane", "rename", pane, titulo)
                prefijo = "clear; " if reutilizado else ""
                if self.herdr("pane", "run", pane, prefijo + shlex.join(comando)) is None:
                    paneles[pane]["estado"] = "libre"
                    self._guardar(estado)
                    return None
                return pane
        except Exception as e:
            logger.warning("visor: no se pudo abrir el panel: %s", e, exc_info=True)
            return None

    def liberar(self, pane: str | None) -> None:
        """Marca el panel como reutilizable (queda visible el resultado hasta que otra corrida lo use)."""
        if not pane:
            return
        try:
            with open(str(self.estado_json) + ".lock", "w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                estado = self._cargar()
                if pane in estado.get("paneles", {}):
                    estado["paneles"][pane]["estado"] = "libre"
                    self._guardar(estado)
        except Exception as e:
            logger.warning("visor: no se pudo liberar %s: %s", pane, e, exc_info=True)
