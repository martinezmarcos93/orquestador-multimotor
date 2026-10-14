#!/usr/bin/env python3
"""Visor en vivo de una corrida: sigue etapas.log + opencode.jsonl + revision.jsonl y los muestra legibles.

Uso: ver.py RUN_DIR      (termina solo cuando el despachador deja el archivo FIN)
"""
import json
import sys
import time
from pathlib import Path

ARCHIVOS = (("etapas.log", None), ("opencode.jsonl", "trabajador"), ("revision.jsonl", "revisor"))


def formatear_evento(linea: str, rol: str) -> str | None:
    """Una línea legible por evento de OpenCode (--format json); None si no aporta."""
    try:
        e = json.loads(linea)
    except json.JSONDecodeError:
        return None
    p = e.get("part", {})
    if p.get("type") == "tool":
        st = p.get("state", {})
        if st.get("status") not in ("completed", "error"):
            return None
        entrada = st.get("input", {})
        detalle = entrada.get("command") or entrada.get("filePath") or entrada.get("pattern") or entrada.get("name") or ""
        marca = "✗" if st.get("status") == "error" else "▸"
        return f"{rol[:3]} {marca} {p.get('tool', '?'):<6} {str(detalle).splitlines()[0][:110] if detalle else ''}"
    if p.get("type") == "text" and p.get("text", "").strip():
        return f"{rol[:3]} │ {' '.join(p['text'].split())[:160]}"
    if e.get("type") == "error":
        return f"{rol[:3]} ✗ error: {json.dumps(e.get('error', e), ensure_ascii=False)[:140]}"
    return None


def seguir(run: Path, salida=sys.stdout, espera: float = 0.4, max_inactivo: float = 3600) -> None:
    posiciones = {nombre: 0 for nombre, _ in ARCHIVOS}
    restos = {nombre: "" for nombre, _ in ARCHIVOS}
    ultimo = time.time()
    fin_visto = None
    while True:
        hubo = False
        for nombre, rol in ARCHIVOS:
            ruta = run / nombre
            if not ruta.exists():
                continue
            with ruta.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(posiciones[nombre])
                datos = f.read()
                posiciones[nombre] = f.tell()
            if not datos:
                continue
            hubo = True
            lineas = (restos[nombre] + datos).split("\n")
            restos[nombre] = lineas.pop()
            for linea in lineas:
                texto = linea if rol is None else formatear_evento(linea, rol)
                if texto:
                    print(texto, file=salida, flush=True)
        ultimo = time.time() if hubo else ultimo
        if (run / "FIN").exists():
            fin_visto = fin_visto or time.time()
            if not hubo and time.time() - fin_visto > espera * 2:
                break
        elif time.time() - ultimo > max_inactivo:
            print("── sin actividad: el visor se cierra ──", file=salida, flush=True)
            return
        time.sleep(espera)
    for _ in range(25):
        if (run / "estado.json").exists():
            r = json.loads((run / "estado.json").read_text(encoding="utf-8"))
            print(f"── fin: {r.get('resultado')} · commits {r.get('commits', '-')} ──", file=salida, flush=True)
            return
        time.sleep(0.4)
    print("── fin ──", file=salida, flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    seguir(Path(sys.argv[1]))
