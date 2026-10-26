"""Inspección de archivos: no segmenta, filtra, normaliza ni clasifica."""

import csv
import hashlib
import html
import json
import math
import os
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import soundfile as sf

from .paths import check_output_folder

AUDIO_SUFFIXES = {
    ".wav", ".wave", ".flac", ".aif", ".aiff", ".ogg",
    ".opus", ".mp3", ".m4a", ".aac", ".wma",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_audio(raw: Path) -> list[Path]:
    if not raw.is_dir():
        raise ValueError(f"No existe la carpeta de originales: {raw}")
    return sorted(
        (path for path in raw.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES),
        key=lambda path: path.relative_to(raw).as_posix(),
    )


def inspect_file(path: Path, threshold: float = 0.999, max_bins: int = 2500) -> tuple[dict, dict]:
    """Mide todos los samples por bloques y conserva mínimos/máximos para dibujar."""
    if not 0 < threshold <= 1 or max_bins < 1:
        raise ValueError("Umbral o número de bloques de figura no válido.")
    digest = sha256_file(path)
    with sf.SoundFile(str(path)) as audio:
        rate, frames, channels = audio.samplerate, audio.frames, audio.channels
        if frames == 0:
            raise ValueError("El archivo no contiene muestras.")
        block_size = max(1, math.ceil(frames / max_bins))
        peaks, sums, squares = np.zeros(channels), np.zeros(channels), np.zeros(channels)
        near_full_scale = np.zeros(channels, dtype=np.int64)
        times, lows, highs = [], [], []
        consumed = 0
        while True:
            block = audio.read(block_size, dtype="float64", always_2d=True)
            if not len(block):
                break
            if not np.isfinite(block).all():
                raise ValueError("El archivo contiene muestras NaN o infinitas.")
            peaks = np.maximum(peaks, np.max(np.abs(block), axis=0))
            sums += block.sum(axis=0)
            squares += np.square(block).sum(axis=0)
            near_full_scale += (np.abs(block) >= threshold).sum(axis=0)
            times.append((consumed + (len(block) - 1) / 2) / rate)
            lows.append(block.min(axis=0))
            highs.append(block.max(axis=0))
            consumed += len(block)
        if consumed != frames:
            raise ValueError("La cantidad de muestras decodificada no coincide con la cabecera.")
        record = {
            "sha256": digest,
            "formato": audio.format,
            "subtipo": audio.subtype,
            "frecuencia_muestreo_hz": rate,
            "canales": channels,
            "muestras_por_canal": frames,
            "duracion_s": frames / rate,
            "pico_abs_por_canal": peaks.tolist(),
            "rms_por_canal": np.sqrt(squares / frames).tolist(),
            "media_por_canal": (sums / frames).tolist(),
            "muestras_cerca_limite_por_canal": near_full_scale.tolist(),
            "avisos": [],
        }
    if np.any(near_full_scale):
        record["avisos"].append(
            "Hay muestras cercanas al límite digital: revisar posible recorte; "
            "este indicador no demuestra saturación."
        )
    if np.all(peaks == 0):
        record["avisos"].append("Silencio digital: no hay señal acústica medible.")
    return record, {"tiempo_s": times, "min": lows, "max": highs}


def _draw_waveform(envelope: dict, channels: int, output: Path, title: str) -> None:
    # La caché de fuentes es local al informe, no depende de permisos en HOME.
    os.environ.setdefault("MPLCONFIGDIR", str(output.parent.parent / ".matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, axes = plt.subplots(channels, 1, figsize=(10, max(2.8, channels * 2)), squeeze=False, sharex=True)
    times = np.asarray(envelope["tiempo_s"])
    low, high = np.asarray(envelope["min"]), np.asarray(envelope["max"])
    for index, axis in enumerate(axes[:, 0]):
        axis.vlines(times, low[:, index], high[:, index], color="#126c82", linewidth=0.6)
        axis.set_ylabel(f"Canal {index + 1}\nAmplitud digital")
        axis.axhline(0, color="#637282", linewidth=0.4)
        axis.grid(alpha=0.15)
    axes[-1, 0].set_xlabel("Tiempo (s)")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(output, dpi=150)
    plt.close(fig)


def inspect_directory(raw: Path, output: Path, threshold: float = 0.999, max_bins: int = 2500) -> dict:
    check_output_folder(raw, output)
    paths = discover_audio(raw)
    output.mkdir(parents=True, exist_ok=True)
    (output / "figuras").mkdir(exist_ok=True)
    records, duplicates = [], {}
    for index, path in enumerate(paths, start=1):
        relative = path.relative_to(raw).as_posix()
        try:
            if not path.resolve().is_relative_to(raw.resolve()):
                raise ValueError("El enlace apunta fuera de la carpeta de originales.")
            record, envelope = inspect_file(path, threshold, max_bins)
            record.update(archivo=relative, estado="legible", error="")
            if record["sha256"] in duplicates:
                record["avisos"].append(f"Contenido idéntico a {duplicates[record['sha256']]}.")
            else:
                duplicates[record["sha256"]] = relative
            filename = f"{index:03d}_{record['sha256'][:12]}.png"
            _draw_waveform(envelope, record["canales"], output / "figuras" / filename, relative)
            record["figura"] = "figuras/" + filename
        except (ValueError, RuntimeError, OSError) as exc:
            record = {
                "archivo": relative, "estado": "error", "error": str(exc), "avisos": [],
            }
        records.append(record)

    summary = {
        "generado_utc": datetime.now(timezone.utc).isoformat(),
        "estado": "sin_audios" if not records else ("con_errores" if any(r["estado"] == "error" for r in records) else "inspeccion_completada"),
        "archivos_encontrados": len(records),
        "archivos_legibles": sum(r["estado"] == "legible" for r in records),
        "archivos_con_error": sum(r["estado"] == "error" for r in records),
        "configuracion_inspeccion": {"umbral_aviso_escala_completa": threshold, "max_bloques_figura": max_bins},
        "versiones": {name: version(name) for name in ("acustica-materiales", "numpy", "soundfile", "matplotlib")},
        "archivos": records,
    }
    (output / "resumen.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    columns = [
        "archivo", "estado", "formato", "subtipo", "frecuencia_muestreo_hz",
        "canales", "muestras_por_canal", "duracion_s", "pico_abs_por_canal",
        "rms_por_canal", "media_por_canal", "muestras_cerca_limite_por_canal",
        "sha256", "avisos", "error",
    ]
    with (output / "inventario.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                for key, value in record.items()
            })
    _write_html(summary, output / "informe.html")
    return summary


def _write_html(summary: dict, output: Path) -> None:
    escape, sections = html.escape, []
    for record in summary["archivos"]:
        heading = f"<h2>{escape(record['archivo'])}</h2>"
        if record["estado"] == "error":
            sections.append(heading + f"<p class='aviso'>No se pudo leer: {escape(record['error'])}</p>")
            continue
        details = (
            f"{record['duracion_s']:.3f} s · {record['frecuencia_muestreo_hz']} Hz · "
            f"{record['canales']} canal(es) · {record['formato']} / {record['subtipo']}"
        )
        alerts = "".join(f"<li>{escape(text)}</li>" for text in record["avisos"])
        sections.append(
            heading + f"<p>{escape(details)}</p>"
            + (f"<ul class='aviso'>{alerts}</ul>" if alerts else "")
            + f"<img src='{escape(record['figura'], quote=True)}' alt='Forma de onda por canal'>"
        )
    empty = "<p class='aviso'>Todavía no hay audios. Este informe no contiene resultados experimentales.</p>" if not sections else ""
    output.write_text(
        "<!doctype html><html lang='es'><meta charset='utf-8'><title>Inspección de audios piloto</title>"
        "<style>body{font:16px system-ui;max-width:1000px;margin:40px auto;padding:0 20px;color:#243744}"
        "h1,h2{color:#125c70}h2{margin-top:40px}img{max-width:100%}.aviso{background:#fff4dc;padding:14px}"
        "</style><h1>Inspección de audios piloto</h1>"
        f"<p>{summary['archivos_encontrados']} archivos encontrados; {summary['archivos_con_error']} con error de lectura.</p>"
        "<p>Se conservan todos los canales. No se aplica filtrado, normalización ni remuestreo. "
        "La figura muestra mínimos y máximos por bloque; las estadísticas usan todas las muestras. "
        "No se infiere el número de impactos ni se calculan descriptores o clasificación.</p>"
        + empty + "".join(sections) + "</html>",
        encoding="utf-8",
    )
