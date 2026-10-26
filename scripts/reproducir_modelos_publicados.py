"""Reentrena desde descriptores publicados sin sobrescribir resultados de referencia."""

import argparse
import json
import shutil
from pathlib import Path

from acustica_materiales.modeling import train_pilot


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--salida',type=Path,default=Path('resultados_reproducidos'))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    destination=args.salida.resolve()
    if destination.exists():
        raise ValueError('La carpeta de reproducción ya existe; elige otra salida.')
    destination.mkdir(parents=True)
    paths=['config.json','datos/caracteristicas/piloto_v1/por_golpe.csv',
           'datos/metadatos/objetos.csv','datos/metadatos/impactos.csv']
    for name in paths:
        source=root/name; target=destination/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    result=train_pilot(destination)
    expected={'A_espectral':2,'B_temporal':3,'C_combinado':1}
    actual={k:v['aciertos_objetos'] for k,v in result['metricas'].items()}
    assert actual==expected, f'Cambió la reproducción: {actual}. Revisa versiones y entorno.'
    print(json.dumps(actual,indent=2))
    print(destination/'resultados/modelos_piloto_v1/informe.md')


if __name__=='__main__':
    main()
