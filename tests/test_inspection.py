import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from acustica_materiales.inspection import inspect_directory, inspect_file
from acustica_materiales.paths import check_output_folder


def test_pcm_stereo_preserves_channels_levels_and_original(tmp_path):
    rate = 48000
    t = np.arange(4800) / rate
    tone = 0.5 * np.sin(2 * np.pi * 1000 * t)
    path = tmp_path / "estereo.wav"
    sf.write(path, np.column_stack([tone, -tone]), rate, subtype="PCM_16")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    record, envelope = inspect_file(path)
    assert record["canales"] == 2
    assert record["frecuencia_muestreo_hz"] == rate
    assert record["duracion_s"] == pytest.approx(0.1)
    np.testing.assert_allclose(record["rms_por_canal"], [0.5 / np.sqrt(2)] * 2, atol=4e-5)
    np.testing.assert_allclose(record["pico_abs_por_canal"], [0.5] * 2, atol=4e-5)
    assert max(row[0] for row in envelope["max"]) > 0.49
    assert record["sha256"] == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_silence_is_flagged_and_peak_is_not_hidden(tmp_path):
    silence = tmp_path / "silencio.wav"
    sf.write(silence, np.zeros(1000), 48000, subtype="PCM_16")
    record, _ = inspect_file(silence)
    assert record["rms_por_canal"] == [0.0]
    assert any("Silencio" in text for text in record["avisos"])
    impulse = np.zeros(10000)
    impulse[513] = 1
    path = tmp_path / "pico.wav"
    sf.write(path, impulse, 48000, subtype="PCM_16")
    record, envelope = inspect_file(path, max_bins=10)
    assert record["muestras_cerca_limite_por_canal"] == [1]
    assert max(row[0] for row in envelope["max"]) > 0.99
    assert any("no demuestra saturación" in text for text in record["avisos"])


def test_nan_audio_is_not_reported_as_a_valid_measurement(tmp_path):
    path = tmp_path / "nan.wav"
    sf.write(path, [0.0, float("nan"), 0.0], 48000, subtype="FLOAT")
    with pytest.raises(ValueError, match="NaN"):
        inspect_file(path)


def test_output_cannot_overwrite_originals(tmp_path):
    raw = tmp_path / "originales"
    with pytest.raises(ValueError):
        check_output_folder(raw, raw)
    with pytest.raises(ValueError):
        check_output_folder(raw, raw / "informe")


def test_report_handles_bad_file_duplicates_and_html_names(tmp_path):
    raw, out = tmp_path / "originales", tmp_path / "salida"
    raw.mkdir()
    first = raw / "audio & prueba.wav"
    sf.write(first, np.sin(np.arange(800) / 20) * 0.2, 8000, subtype="PCM_16")
    (raw / "copia.wav").write_bytes(first.read_bytes())
    (raw / "roto.m4a").write_bytes(b"no es audio")
    summary = inspect_directory(raw, out, max_bins=40)
    assert summary["archivos_encontrados"] == 3
    assert summary["archivos_legibles"] == 2
    assert summary["archivos_con_error"] == 1
    assert any("Contenido idéntico" in warning for row in summary["archivos"] for warning in row["avisos"])
    assert "audio &amp; prueba.wav" in (out / "informe.html").read_text()
    saved = json.loads((out / "resumen.json").read_text())
    assert saved["archivos_con_error"] == 1
    assert len(list((out / "figuras").glob("*.png"))) == 2


def test_empty_directory_is_explicitly_not_an_experiment(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "out"
    raw.mkdir()
    report = inspect_directory(raw, out)
    assert report["estado"] == "sin_audios"
    assert report["archivos_encontrados"] == 0
    assert "no contiene resultados experimentales" in (out / "informe.html").read_text()
