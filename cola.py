#!/usr/bin/env python3
"""Cola de encargos con paralelismo limitado (2-3) para no agotar la cuota gratuita compartida.

Dos encargos del mismo repo que podrían tocar los mismos archivos (o que comparten tema/worktree)
nunca corren a la vez: "una sola cabeza por archivo". Si hay fallos de infraestructura seguidos
(cuota, proxy caído) la cola deja de lanzar y lo informa.

Uso: cola.py ENCARGO.md [ENCARGO.md ...] [--max 2]
"""
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import despachar

logger = logging.getLogger("cola")

MAX_PERMITIDO = 3
FALLOS_DE_INFRAESTRUCTURA = {"timeout", "timeout_despachador", "error_opencode", "error_despachador", "error_cola"}


def _prefijo(patron: str) -> str:
    """Parte fija del patrón antes del primer comodín."""
    return patron.split("*", 1)[0]


def se_pisan(a: dict, b: dict) -> bool:
    """True si dos encargos no deben correr a la vez (misma cabeza sobre los mismos archivos)."""
    try:
        repo_a = str(Path(a["repo"]).expanduser().resolve())
        repo_b = str(Path(b["repo"]).expanduser().resolve())
    except (OSError, RuntimeError):
        # Ante rutas no resolubles, serializar es más seguro que asumir independencia.
        repo_a, repo_b = a["repo"], b["repo"]
    if repo_a != repo_b:
        return False
    if a["tema"] == b["tema"]:
        return True
    return any(_prefijo(x).startswith(_prefijo(y)) or _prefijo(y).startswith(_prefijo(x))
               for x in a["permitidos"] for y in b["permitidos"])


def planificar(encargos: list[dict], runner, max_paralelo: int = 2, corte_fallos: int = 2) -> list[dict]:
    """Ejecuta los encargos {'ruta','cfg'} con `runner(enc) -> estado`, respetando paralelismo y conflictos."""
    max_paralelo = max(1, min(max_paralelo, MAX_PERMITIDO))
    pendientes, corriendo, resultados = list(encargos), {}, []
    seguidos, detenida = 0, False
    with ThreadPoolExecutor(max_workers=max_paralelo) as ex:
        while pendientes or corriendo:
            if not detenida:
                for enc in list(pendientes):
                    if len(corriendo) >= max_paralelo:
                        break
                    if any(se_pisan(enc["cfg"], c["cfg"]) for c in corriendo.values()):
                        continue
                    pendientes.remove(enc)
                    corriendo[ex.submit(runner, enc)] = enc
            elif pendientes:
                resultados += [{"id": e["cfg"]["id"], "proyecto": e["cfg"]["proyecto"], "resultado": "no_lanzado",
                                "motivo": f"cola detenida tras {seguidos} fallos de infraestructura seguidos"}
                               for e in pendientes]
                pendientes.clear()
            if not corriendo:
                break
            hechos, _ = wait(corriendo, return_when=FIRST_COMPLETED)
            for f in hechos:
                enc = corriendo.pop(f)
                try:
                    estado = f.result()
                except Exception as e:
                    logger.error("falló el runner de %s: %s", enc["ruta"], e, exc_info=True)
                    estado = {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                              "resultado": "error_cola", "error": str(e)}
                resultados.append(estado)
                seguidos = seguidos + 1 if estado.get("resultado") in FALLOS_DE_INFRAESTRUCTURA else 0
                detenida = detenida or seguidos >= corte_fallos
    return resultados


def todos_aprobados(resultados: list[dict]) -> bool:
    """La cola solo devuelve éxito si los tests pasan y la compuerta de revisión no bloquea."""
    return all(
        r.get("resultado") == "pasa"
        and r.get("aprobacion", "no_requerida") in ("no_requerida", "aprobado")
        for r in resultados
    )


def comunicar_con_timeout(proc, timeout_s: int, gracia_s: float = 5) -> tuple[str, str, bool]:
    """Espera un proceso y, al vencer, termina su grupo completo; devuelve stdout, stderr y timeout."""
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return stdout, stderr, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=gracia_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
        return stdout, stderr, True


def runner_subproceso(enc: dict) -> dict:
    """Corre despachar.py con timeout exterior y termina el grupo si se atasca."""
    cmd = [sys.executable, "-B", str(Path(despachar.__file__)), str(enc["ruta"])]
    timeout_s = enc["cfg"].get("timeout_cola_min", enc["cfg"].get("timeout_min", 20) + 30) * 60
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            start_new_session=True)
    stdout, stderr, agotado = comunicar_con_timeout(proc, timeout_s)
    if agotado:
        return {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"],
                "resultado": "timeout_despachador", "timeout_s": timeout_s,
                "error": "el despachador excedió el timeout exterior",
                "diagnostico": (stderr or stdout or "")[-400:]}
    try:
        estado = json.loads(stdout)
    except json.JSONDecodeError:
        return {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"], "resultado": "error_despachador",
                "codigo_salida": proc.returncode, "error": (stderr or stdout or "salida vacía")[-400:]}
    if proc.returncode != 0:
        estado.setdefault("codigo_salida_despachador", proc.returncode)
    return estado


def cargar(rutas: list[Path]) -> list[dict]:
    encargos, vistos = [], set()
    for ruta in rutas:
        cfg = despachar.parsear_encargo(ruta.read_text(encoding="utf-8"))
        clave = (cfg["proyecto"], cfg["id"])
        if clave in vistos:
            raise ValueError(f"encargo duplicado: {clave}")
        vistos.add(clave)
        encargos.append({"ruta": ruta.resolve(), "cfg": cfg})
    return encargos


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("encargos", nargs="+", type=Path)
    ap.add_argument("--visor", action="store_true", help="un panel por corrida en Herdr (si corre dentro de Herdr)")
    ap.add_argument("--max", type=int, default=2, help=f"trabajadores en paralelo (1-{MAX_PERMITIDO})")
    args = ap.parse_args()
    if not 1 <= args.max <= MAX_PERMITIDO:
        ap.error(f"--max debe estar entre 1 y {MAX_PERMITIDO}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    if args.visor:
        os.environ["ORQUESTADOR_VISOR"] = "1"
    t0 = time.time()
    try:
        resultados = planificar(cargar(args.encargos), runner_subproceso, args.max)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"resultado": "cola_invalida", "error": str(exc)}, ensure_ascii=False))
        return 1
    resumen = {
        "duracion_s": round(time.time() - t0),
        "max_paralelo": args.max,
        "resultados": [
            {"proyecto": r.get("proyecto"), "id": r.get("id"), "resultado": r.get("resultado"),
             "aprobacion": r.get("aprobacion"), "rama": r.get("rama"), "commits": r.get("commits")}
            | ({k: r[k] for k in ("revision", "mutacion", "errores", "error", "motivo", "diagnostico",
                                   "timeout_s", "codigo_salida", "codigo_salida_despachador")
                if k in r})
            for r in resultados
        ],
    }
    despachar.RUNS.mkdir(exist_ok=True)
    (despachar.RUNS / f"cola-{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    return 0 if todos_aprobados(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
