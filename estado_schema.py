"""Validación del estado.json contra schemas/estado.v1.schema.json (subconjunto de JSON Schema)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent


def _coincide_tipo_json(valor, tipo: str) -> bool:
    if tipo == "object":
        return isinstance(valor, dict)
    if tipo == "array":
        return isinstance(valor, list)
    if tipo == "string":
        return isinstance(valor, str)
    if tipo == "boolean":
        return isinstance(valor, bool)
    if tipo == "integer":
        return isinstance(valor, int) and not isinstance(valor, bool)
    if tipo == "number":
        return isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if tipo == "null":
        return valor is None
    return True


def _validar_con_schema(valor, esquema: dict, ruta: str = "$") -> list[str]:
    """Valida el subconjunto JSON Schema usado por estado.v1, sin dependencias externas."""
    errores: list[str] = []
    tipos = esquema.get("type")
    if tipos is not None:
        opciones = tipos if isinstance(tipos, list) else [tipos]
        if not any(_coincide_tipo_json(valor, tipo) for tipo in opciones):
            errores.append(f"{ruta}: tipo inválido; se esperaba {' o '.join(opciones)}")
            return errores
    if "const" in esquema and valor != esquema["const"]:
        errores.append(f"{ruta}: debe ser exactamente {esquema['const']!r}")
    if "enum" in esquema and valor not in esquema["enum"]:
        errores.append(f"{ruta}: valor fuera del enum permitido")
    if isinstance(valor, str):
        if len(valor) < esquema.get("minLength", 0):
            errores.append(f"{ruta}: longitud menor que minLength")
        patron = esquema.get("pattern")
        if patron and not re.search(patron, valor):
            errores.append(f"{ruta}: no coincide con pattern")
        if esquema.get("format") == "date-time":
            try:
                fecha = datetime.fromisoformat(valor.replace("Z", "+00:00"))
                if fecha.tzinfo is None or fecha.utcoffset() is None:
                    raise ValueError("falta zona horaria")
            except ValueError:
                errores.append(f"{ruta}: debe ser una fecha ISO-8601 con zona horaria")
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if "minimum" in esquema and valor < esquema["minimum"]:
            errores.append(f"{ruta}: valor menor que minimum")
        if "maximum" in esquema and valor > esquema["maximum"]:
            errores.append(f"{ruta}: valor mayor que maximum")
    if isinstance(valor, dict):
        faltan = [campo for campo in esquema.get("required", []) if campo not in valor]
        errores.extend(f"{ruta}: falta el campo obligatorio {campo!r}" for campo in faltan)
        propiedades = esquema.get("properties", {})
        for campo, subesquema in propiedades.items():
            if campo in valor and isinstance(subesquema, dict):
                errores.extend(_validar_con_schema(valor[campo], subesquema, f"{ruta}.{campo}"))
        if esquema.get("additionalProperties") is False:
            desconocidas = set(valor) - set(propiedades)
            errores.extend(f"{ruta}: propiedad no permitida {campo!r}" for campo in sorted(desconocidas))
    if isinstance(valor, list) and isinstance(esquema.get("items"), dict):
        for indice, elemento in enumerate(valor):
            errores.extend(_validar_con_schema(elemento, esquema["items"], f"{ruta}[{indice}]"))
    return errores


def validar_estado_v1(estado: dict) -> list[str]:
    """Valida estado.json contra el esquema versionado y sus restricciones declaradas."""
    ruta_schema = RAIZ / "schemas" / "estado.v1.schema.json"
    try:
        esquema = json.loads(ruta_schema.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"no se pudo cargar el esquema de estado v1: {exc}"]
    return _validar_con_schema(estado, esquema)
