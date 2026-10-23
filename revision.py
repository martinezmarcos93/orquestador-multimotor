"""Lectura y validación del texto que devuelve el revisor; sin llamadas a procesos."""
from __future__ import annotations

import json
import re

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


def normalizar_veredicto(linea: str) -> str:
    """Tolera adornos triviales (`**APTO**`, `APTO.`, backticks); no acepta otras palabras."""
    return linea.strip().strip("*`_ ").rstrip(".!:;").strip("*`_ ")


def resumir_revision(texto: str) -> dict:
    niveles = {n.lower() + "s": len(re.findall(rf"^\s*-\s*\[{n}\]", texto, re.M)) for n in ("ALTA", "MEDIA", "BAJA")}
    m = re.search(r"(?m)^## Veredicto\s*\n([^\n]+)", texto)
    return {"veredicto": normalizar_veredicto(m.group(1)) if m else None, **niveles}


def validar_formato_revision(texto: str) -> dict:
    """Valida el contrato mínimo del revisor; no interpreta el contenido como verdad objetiva."""
    resumen = resumir_revision(texto)
    m = re.search(r"(?m)^## Veredicto\s*\n([^\n]+)", texto)
    h = re.search(r"(?ms)^## Hallazgos\s*\n(.*)\Z", texto)
    if not m or not h:
        return {"formato_valido": False, "error_formato": "faltan las secciones Veredicto o Hallazgos", **resumen}
    veredicto = normalizar_veredicto(m.group(1))
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


def estado_aceptacion(resultado: str, aprobacion: str, requiere_revision: bool) -> str:
    """Deriva aceptación operativa sin confundir tests verdes con aprobación final.

    La aprobación del revisor es una compuerta intermedia: la decisión final de integrar
    sigue siendo del director y nunca se infiere de un resultado técnico por sí solo.
    """
    if resultado not in ("pasa", "tests_debiles"):
        return "bloqueado_por_resultado_tecnico"
    if not requiere_revision:
        return "pendiente_decision_director"
    if aprobacion == "aprobado":
        return "revision_aprobada_pendiente_decision_director"
    if aprobacion == "con_observaciones":
        return "bloqueado_por_observaciones"
    if aprobacion in ("revision_error", "revision_formato_invalido", "revision_inconsistente"):
        return "bloqueado_por_error_revision"
    if aprobacion == "bloqueado_por_resultado_tecnico":
        return "bloqueado_por_resultado_tecnico"
    return "bloqueado_por_revision"
