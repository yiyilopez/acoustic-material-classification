"""Comandos de la primera etapa del laboratorio."""

import argparse
import json
import sys
from pathlib import Path

from .inspection import inspect_directory
from .metadata import initialize_templates, validate_metadata
from .paths import contained_path
from .segmentation import segment_pilot
from .features import extract_pilot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Laboratorio de sonidos de impacto: etapa piloto.")
    parser.add_argument("--raiz", type=Path, default=Path.cwd(), help="Carpeta raíz del proyecto.")
    parser.add_argument("--config", default="config.json", help="Configuración relativa a la raíz.")
    parser.add_argument("comando", choices=("iniciar-metadatos", "validar-metadatos", "inspeccionar", "segmentar-piloto", "descriptores-piloto", "entrenar-piloto"))
    args = parser.parse_args(argv)
    try:
        root = args.raiz.resolve()
        config = json.loads(contained_path(root, args.config).read_text(encoding="utf-8"))
        raw = contained_path(root, config["rutas"]["originales"])
        metadata = contained_path(root, config["rutas"]["metadatos"])
        if args.comando == "entrenar-piloto":
            from .modeling import train_pilot
            report = train_pilot(root)
            for name, metric in report['metricas'].items():
                print(f"{name}: {metric['aciertos_objetos']}/{metric['objetos']} objetos; exactitud balanceada {metric['exactitud_balanceada_objetos']:.1%}")
            print('Informe: resultados/modelos_piloto_v1/informe.md')
            return 0
        if args.comando == "descriptores-piloto":
            report = extract_pilot(root)
            print(f"{report['golpes_aceptados']} golpes calculados; {report['excluidos']} excluidos. Resultados: datos/caracteristicas/piloto_v1")
            return 0
        if args.comando == "segmentar-piloto":
            report = segment_pilot(root)
            print(f"{len(report['eventos'])} candidatos; pendientes de escucha. Informe: resultados/segmentacion_piloto/revision.html")
            return 0
        if args.comando == "iniciar-metadatos":
            created = initialize_templates(metadata)
            print("Plantillas creadas: " + (", ".join(created) if created else "ninguna; ya existen."))
            return 0
        if args.comando == "validar-metadatos":
            report = validate_metadata(metadata, raw)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["valido"] else 2
        settings = config["inspeccion"]
        report = inspect_directory(
            raw, contained_path(root, config["rutas"]["inspeccion"]),
            float(settings["umbral_aviso_escala_completa"]),
            int(settings["max_bloques_figura"]),
        )
        print(f"Estado: {report['estado']}. Archivos: {report['archivos_encontrados']}; errores: {report['archivos_con_error']}.")
        print(f"Informe: {config['rutas']['inspeccion']}/informe.html")
        return 0 if report["archivos_con_error"] == 0 else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"No se pudo completar el comando: {exc}", file=sys.stderr)
        return 2
