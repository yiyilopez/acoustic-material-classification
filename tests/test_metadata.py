import csv

import numpy as np
import soundfile as sf

from acustica_materiales.metadata import SCHEMAS, initialize_templates, validate_metadata


def write_row(folder, name, values):
    with (folder / name).open("a", encoding="utf-8", newline="") as stream:
        csv.DictWriter(stream, SCHEMAS[name]).writerow(values)


def prepare(tmp_path):
    meta, raw = tmp_path / "metadatos", tmp_path / "originales"
    raw.mkdir()
    initialize_templates(meta)
    sf.write(raw / "sesion.wav", np.zeros(100), 48000, subtype="PCM_16")
    write_row(meta, "objetos.csv", {"objeto_id": "OBJ001", "material": "hierro"})
    write_row(meta, "sesiones.csv", {
        "sesion_id": "SES001", "objeto_id": "OBJ001", "participante_id": "P01",
        "archivo": "sesion.wav", "colocacion_id": "C01",
    })
    return meta, raw


def test_initialization_never_overwrites_existing_records(tmp_path):
    assert len(initialize_templates(tmp_path)) == 3
    write_row(tmp_path, "objetos.csv", {"objeto_id": "OBJ001", "material": "hierro"})
    before = (tmp_path / "objetos.csv").read_bytes()
    assert initialize_templates(tmp_path) == []
    assert (tmp_path / "objetos.csv").read_bytes() == before


def test_empty_templates_are_valid_but_not_data(tmp_path):
    meta, raw = tmp_path / "meta", tmp_path / "raw"
    raw.mkdir()
    initialize_templates(meta)
    report = validate_metadata(meta, raw)
    assert report["valido"]
    assert report["estado"] == "sin_datos"
    assert report["objetos"] == 0


def test_multiple_impacts_are_one_object_and_bounds_are_checked(tmp_path):
    meta, raw = prepare(tmp_path)
    for i in range(3):
        write_row(meta, "impactos.csv", {
            "impacto_id": f"I{i}", "sesion_id": "SES001",
            "inicio_muestra": str(i * 10), "fin_muestra": str(i * 10 + 10),
            "aceptado": "si",
        })
    report = validate_metadata(meta, raw)
    assert report["valido"]
    assert report["objetos"] == 1 and report["impactos"] == 3
    write_row(meta, "impactos.csv", {
        "impacto_id": "fuera", "sesion_id": "SES001",
        "inicio_muestra": "50", "fin_muestra": "101", "aceptado": "si",
    })
    report = validate_metadata(meta, raw)
    assert not report["valido"]
    assert any("excede" in item for item in report["errores"])


def test_material_ids_and_relations_are_not_silently_changed(tmp_path):
    meta, raw = prepare(tmp_path)
    write_row(meta, "objetos.csv", {"objeto_id": "OBJ001", "material": "acero"})
    write_row(meta, "impactos.csv", {"impacto_id": "I1", "sesion_id": "falta", "aceptado": "no"})
    report = validate_metadata(meta, raw)
    assert not report["valido"]
    assert any("duplicado" in error for error in report["errores"])
    assert any("material no válido" in error for error in report["errores"])
    assert any("sesión inexistente" in error for error in report["errores"])
    assert any("motivo de exclusión" in error for error in report["errores"])


def test_recording_cannot_escape_raw_folder(tmp_path):
    meta, raw = prepare(tmp_path)
    outside = tmp_path / "fuera.wav"
    sf.write(outside, [0.0], 48000, subtype="PCM_16")
    write_row(meta, "sesiones.csv", {
        "sesion_id": "SES002", "objeto_id": "OBJ001", "participante_id": "P01",
        "archivo": "../fuera.wav", "colocacion_id": "C01",
    })
    report = validate_metadata(meta, raw)
    assert not report["valido"]
    assert any("carpeta permitida" in error for error in report["errores"])
