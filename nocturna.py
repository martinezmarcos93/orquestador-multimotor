#!/usr/bin/env python3
"""Cola nocturna desatendida: pendientes/ -> en-curso/ -> listos/ o fallidos/, más un resumen para la mañana.

Pensado para correr como servicio oneshot de systemd (ver systemd/). Una instancia a la vez (flock).
Un encargo que quedó en en-curso/ por una interrupción NO se relanza solo (evita duplicar trabajo y
cuota): pasa a fallidos/ con una nota y lo decide Marcos o el director. Solo corre encargos que el
preflight acepta, y cola.py corta sola ante fallos seguidos de infraestructura.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import despachar

RAIZ = Path(__file__).resolve().parent
SUBCARPETAS = ("pendientes", "en-curso", "listos", "fallidos", "resumenes")
APROBADOS = ("pasa", "tests_preparados")
APROBACION_OK = (None, "no_requerida", "aprobado")
logger = logging.getLogger("nocturna")


def preparar(carpeta: Path) -> None:
    for sub in SUBCARPETAS:
        (carpeta / sub).mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def instancia_unica(carpeta: Path):
    with (carpeta / ".lock").open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("otra instancia de nocturna.py ya está corriendo en esta carpeta")
        yield


def mover(archivo: Path, destino: Path, nota: str | None = None) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    nuevo = destino / archivo.name
    if nuevo.exists():  # nunca pisar: conservar ambas versiones
        nuevo = destino / f"{archivo.stem}.{time.strftime('%H%M%S')}{archivo.suffix}"
    shutil.move(str(archivo), str(nuevo))
    if nota:
        nuevo.with_name(nuevo.name + ".nota.txt").write_text(nota.rstrip() + "\n", encoding="utf-8")
    return nuevo


def recuperar_interrumpidos(carpeta: Path) -> list[str]:
    movidos = []
    for f in sorted((carpeta / "en-curso").glob("*.md")):
        mover(f, carpeta / "fallidos",
              "interrumpido: la corrida anterior no terminó. No se relanza sola para no duplicar trabajo; "
              "revisá runs/<proyecto>-<id>/ y, si corresponde, devolvelo a pendientes/.")
        movidos.append(f.name)
    return movidos


def ejecutar_cola(archivos: list[Path], maximo: int, timeout_s: int) -> dict | None:
    """Lanza cola.py en su propio grupo de procesos; devuelve su resumen JSON o None si no se pudo leer."""
    proc = subprocess.Popen([sys.executable, "-u", str(RAIZ / "cola.py"), "--max", str(maximo), *map(str, archivos)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            start_new_session=True)
    try:
        salida, err = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        despachar_terminar(proc)
        logger.error("cola.py excedió %s s; se terminó el grupo de procesos", timeout_s)
        return None
    except BaseException:  # SIGTERM/Ctrl-C a nocturna: no dejar la cola huérfana en su propio grupo
        despachar_terminar(proc)
        raise
    try:
        return json.loads(salida)
    except json.JSONDecodeError:
        logger.error("cola.py no devolvió JSON (rc=%s): %s", proc.returncode, (err or salida)[-500:])
        return None


def despachar_terminar(proc: subprocess.Popen) -> None:
    for senal, espera in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, senal)
        try:
            proc.communicate(timeout=espera)
            return
        except subprocess.TimeoutExpired:
            continue


def clasificar(resultado: dict) -> bool:
    return resultado.get("resultado") in APROBADOS and resultado.get("aprobacion") in APROBACION_OK


def procesar(carpeta: Path, maximo: int = 2, timeout_h: float = 8, ejecutor=ejecutar_cola) -> dict:
    """Un ciclo completo. `ejecutor` se inyecta en los tests."""
    preparar(carpeta)
    inicio = datetime.now()
    interrumpidos = recuperar_interrumpidos(carpeta)
    invalidos: dict[str, str] = {}
    validos: list[tuple[Path, dict]] = []
    for f in sorted((carpeta / "pendientes").glob("*.md")):
        try:
            cfg = despachar.parsear_encargo(f.read_text(encoding="utf-8"))
            pre = despachar.validar_encargo(f)
            if not pre["valido"]:
                raise ValueError("; ".join(pre["errores"]))
        except Exception as exc:  # el encargo defectuoso no debe frenar al resto
            logger.error("encargo inválido %s: %s", f.name, exc, exc_info=True)
            invalidos[f.name] = str(exc)
            mover(f, carpeta / "fallidos", f"inválido en el preflight: {exc}")
            continue
        validos.append((mover(f, carpeta / "en-curso"), cfg))
    resumen_cola = None
    if validos:
        resumen_cola = ejecutor([f for f, _ in validos], maximo, int(timeout_h * 3600))
    por_clave = {(r.get("proyecto"), r.get("id")): r for r in (resumen_cola or {}).get("resultados", [])}
    listos, fallidos = [], []
    for f, cfg in validos:
        r = por_clave.get((cfg["proyecto"], cfg["id"]))
        if r is None:
            # sin veredicto (cola caída/timeout): queda en en-curso/ y la próxima corrida lo marcará interrumpido
            fallidos.append((f.name, "sin_veredicto", "la cola no devolvió resultado; sigue en en-curso/"))
            continue
        if clasificar(r):
            mover(f, carpeta / "listos")
            listos.append((f.name, r.get("resultado"), r.get("rama")))
        else:
            motivo = r.get("motivo") or r.get("resultado")
            mover(f, carpeta / "fallidos", f"resultado: {r.get('resultado')} · aprobación: {r.get('aprobacion')} · {motivo}")
            fallidos.append((f.name, r.get("resultado"), motivo))
    resumen = {"inicio": inicio.isoformat(timespec="seconds"), "interrumpidos": interrumpidos, "invalidos": invalidos,
               "listos": listos, "fallidos": fallidos, "duracion_cola_s": (resumen_cola or {}).get("duracion_s")}
    escribir_resumen(carpeta, resumen)
    return resumen


def escribir_resumen(carpeta: Path, r: dict) -> Path:
    lineas = [f"# Resumen nocturno — {r['inicio']}", "",
              f"- Listos para revisar: **{len(r['listos'])}**",
              f"- Fallidos o sin veredicto: **{len(r['fallidos']) + len(r['invalidos'])}**",
              f"- Interrumpidos de una corrida anterior: **{len(r['interrumpidos'])}**", ""]
    if r["listos"]:
        lineas += ["## Listos (revisar el diff; el merge es tuyo)", ""]
        lineas += [f"- `{n}` → {res} · rama `{rama}`" for n, res, rama in r["listos"]]
        lineas.append("")
    if r["fallidos"] or r["invalidos"] or r["interrumpidos"]:
        lineas += ["## Requieren atención", ""]
        lineas += [f"- `{n}` → {res}: {mot}" for n, res, mot in r["fallidos"]]
        lineas += [f"- `{n}` → inválido: {e}" for n, e in r["invalidos"].items()]
        lineas += [f"- `{n}` → interrumpido en la corrida anterior" for n in r["interrumpidos"]]
        lineas.append("")
    ruta = carpeta / "resumenes" / f"{datetime.now():%Y-%m-%d-%H%M}.md"
    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


def _sigterm(signum, frame):
    raise SystemExit(f"interrumpido por señal {signum}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--carpeta", type=Path, required=True)
    ap.add_argument("--max", type=int, default=2)
    ap.add_argument("--timeout-h", type=float, default=8)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    preparar(args.carpeta)
    signal.signal(signal.SIGTERM, _sigterm)
    with instancia_unica(args.carpeta):
        r = procesar(args.carpeta, args.max, args.timeout_h)
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
