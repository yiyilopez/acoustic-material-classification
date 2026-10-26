"""Resolución de rutas sin permitir escribir dentro de los originales."""

from pathlib import Path


def contained_path(root: Path, value: str) -> Path:
    """Una ruta de datos debe ser relativa y permanecer dentro de root."""
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"La ruta debe ser relativa: {value}")
    resolved = (root / relative).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"La ruta sale de la carpeta permitida: {value}")
    return resolved


def check_output_folder(raw: Path, output: Path) -> None:
    """Evita que la inspección sobrescriba datos originales."""
    raw, output = raw.resolve(), output.resolve()
    if raw == output or output.is_relative_to(raw) or raw.is_relative_to(output):
        raise ValueError("La salida y los originales deben ser carpetas separadas.")
