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
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import despachar

logger = logging.getLogger("cola")

MAX_PERMITIDO = 3
FALLOS_DE_INFRAESTRUCTURA = {"timeout", "error_opencode", "error_despachador"}


def _prefijo(patron: str) -> str:
    """Parte fija del patrón antes del primer comodín."""
    return patron.split("*", 1)[0]


def se_pisan(a: dict, b: dict) -> bool:
    """True si dos encargos no deben correr a la vez (misma cabeza sobre los mismos archivos)."""
    if a["repo"] != b["repo"]:
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


def runner_subproceso(enc: dict) -> dict:
    """Corre despachar.py como proceso aparte y devuelve el JSON que imprime."""
    r = subprocess.run([sys.executable, "-B", str(Path(despachar.__file__)), str(enc["ruta"])],
                       capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"id": enc["cfg"]["id"], "proyecto": enc["cfg"]["proyecto"], "resultado": "error_despachador",
                "error": (r.stderr or r.stdout)[-400:]}


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
    ap.add_argument("--max", type=int, default=2, help=f"trabajadores en paralelo (1-{MAX_PERMITIDO})")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    t0 = time.time()
    resultados = planificar(cargar(args.encargos), runner_subproceso, args.max)
    resumen = {"duracion_s": round(time.time() - t0), "max_paralelo": args.max,
               "resultados": [{k: r.get(k) for k in ("proyecto", "id", "resultado", "rama", "commits") if k in r}
                              | ({"revision": r["revision"]} if "revision" in r else {})
                              | ({"mutacion": r["mutacion"].get("puntaje")} if "mutacion" in r else {})
                              for r in resultados]}
    despachar.RUNS.mkdir(exist_ok=True)
    (despachar.RUNS / f"cola-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    return 0 if all(r.get("resultado") == "pasa" for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
