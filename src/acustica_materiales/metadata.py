"""Plantillas y validación de objetos, sesiones e impactos."""

import csv
import math
from collections import Counter
from pathlib import Path

import soundfile as sf

from .paths import contained_path

SCHEMAS = {
    "objetos.csv": [
        "objeto_id", "material", "descripcion", "largo_mm", "ancho_mm",
        "alto_mm", "espesor_mm", "observaciones",
    ],
    "sesiones.csv": [
        "sesion_id", "objeto_id", "participante_id", "archivo", "fecha_hora",
        "telefono", "app_grabacion", "colocacion_id", "recinto_id", "ciudad",
        "apoyo", "percutor", "distancia_cm", "orientacion_microfono", "observaciones",
    ],
    "impactos.csv": [
        "impacto_id", "sesion_id", "inicio_muestra", "fin_muestra",
        "aceptado", "motivo_exclusion", "observaciones",
    ],
}
MATERIALS = ("madera", "vidrio", "hierro", "plastico_rigido")


def initialize_templates(folder: Path) -> list[str]:
    """Crea únicamente las plantillas que faltan; nunca borra registros."""
    folder.mkdir(parents=True, exist_ok=True)
    created = []
    for filename, columns in SCHEMAS.items():
        path = folder / filename
        try:
            with path.open("x", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerow(columns)
            created.append(filename)
        except FileExistsError:
            continue
    return created


def _read_table(path: Path, columns: list[str], errors: list[str]) -> list[dict]:
    if not path.exists():
        errors.append(f"Falta {path.name}. Ejecuta iniciar-metadatos.")
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if reader.fieldnames != columns:
                errors.append(f"{path.name}: las columnas no coinciden con la plantilla.")
                return []
            rows = []
            for line, row in enumerate(reader, start=2):
                if None in row or any(value is None for value in row.values()):
                    errors.append(f"{path.name}:{line}: número incorrecto de columnas.")
                    continue
                cleaned = {key: value.strip() for key, value in row.items()}
                if any(cleaned.values()):
                    cleaned["_linea"] = line
                    rows.append(cleaned)
            return rows
    except (OSError, UnicodeError, csv.Error) as exc:
        errors.append(f"{path.name}: no se pudo leer: {exc}")
        return []


def _index(rows: list[dict], key: str, errors: list[str]) -> dict[str, dict]:
    result = {}
    for row in rows:
        identifier = row[key]
        if not identifier:
            errors.append(f"Falta {key} en la línea {row['_linea']}.")
        elif identifier in result:
            errors.append(f"{key} duplicado: {identifier}.")
        else:
            result[identifier] = row
    return result


def _positive_number(row: dict, key: str, errors: list[str]) -> None:
    if not row[key]:
        return
    try:
        value = float(row[key])
        if not math.isfinite(value) or value <= 0:
            raise ValueError
    except ValueError:
        errors.append(f"Línea {row['_linea']}: {key} debe ser un número positivo.")


def validate_metadata(folder: Path, raw: Path) -> dict:
    errors, warnings = [], []
    tables = {
        name: _read_table(folder / name, columns, errors)
        for name, columns in SCHEMAS.items()
    }
    objects = _index(tables["objetos.csv"], "objeto_id", errors)
    sessions = _index(tables["sesiones.csv"], "sesion_id", errors)
    _index(tables["impactos.csv"], "impacto_id", errors)
    for row in tables["objetos.csv"]:
        if row["material"] not in MATERIALS:
            errors.append(f"{row['objeto_id']}: material no válido: {row['material']!r}.")
        for key in ("largo_mm", "ancho_mm", "alto_mm", "espesor_mm"):
            _positive_number(row, key, errors)

    frames_by_session, seen_files, participants_by_object = {}, {}, {}
    for row in tables["sesiones.csv"]:
        sid = row["sesion_id"]
        if row["objeto_id"] not in objects:
            errors.append(f"{sid}: objeto inexistente: {row['objeto_id']}.")
        for key in ("participante_id", "archivo", "colocacion_id"):
            if not row[key]:
                errors.append(f"{sid}: falta {key}.")
        _positive_number(row, "distancia_cm", errors)
        participants_by_object.setdefault(row["objeto_id"], set()).add(row["participante_id"])
        if not row["archivo"]:
            continue
        try:
            path = contained_path(raw, row["archivo"])
            if path in seen_files:
                errors.append(f"{sid}: archivo ya asociado con {seen_files[path]}.")
            seen_files[path] = sid
            if not path.is_file():
                errors.append(f"{sid}: no existe el archivo {row['archivo']}.")
            else:
                frames_by_session[sid] = sf.info(str(path)).frames
        except (ValueError, RuntimeError, OSError) as exc:
            errors.append(f"{sid}: archivo no válido: {exc}")

    for row in tables["impactos.csv"]:
        iid, sid = row["impacto_id"], row["sesion_id"]
        if sid not in sessions:
            errors.append(f"{iid}: sesión inexistente: {sid}.")
        if row["aceptado"] not in ("pendiente", "si", "no"):
            errors.append(f"{iid}: aceptado debe ser pendiente, si o no.")
        if row["aceptado"] == "no" and not row["motivo_exclusion"]:
            errors.append(f"{iid}: falta el motivo de exclusión.")
        bounds = (row["inicio_muestra"], row["fin_muestra"])
        if row["aceptado"] == "si" or any(bounds):
            try:
                start, end = map(int, bounds)
                if start < 0 or end <= start:
                    raise ValueError
                if sid in frames_by_session and end > frames_by_session[sid]:
                    errors.append(f"{iid}: el final excede la longitud del archivo.")
            except ValueError:
                errors.append(f"{iid}: se requiere 0 <= inicio_muestra < fin_muestra.")

    for oid, participants in participants_by_object.items():
        if len(participants) > 1:
            warnings.append(
                f"{oid}: aparece con varios participantes; excluir al objeto completo "
                "al construir cualquier partición de evaluación."
            )
    if not objects:
        warnings.append("Las plantillas están vacías: todavía no hay objetos registrados.")
    elif len(objects) < 16:
        warnings.append("Todavía no se han registrado los 16 objetos previstos para el piloto.")
    return {
        "valido": not errors,
        "estado": "sin_datos" if not objects and not errors else ("valido" if not errors else "con_errores"),
        "objetos": len(objects),
        "sesiones": len(sessions),
        "impactos": len(tables["impactos.csv"]),
        "objetos_por_material": dict(Counter(row["material"] for row in objects.values())),
        "errores": errors,
        "avisos": warnings,
    }
