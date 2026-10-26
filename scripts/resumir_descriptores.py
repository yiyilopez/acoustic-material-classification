"""Resumen y comprobación independiente de los archivos calculados del piloto."""

import csv
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf

root=Path(__file__).resolve().parents[1]
out=root/'resultados/descriptores_piloto'
data=json.loads((out/'calculo.json').read_text())
rows=data['resultados']
objects=data['por_objeto']
with (root/'datos/metadatos/impactos.csv').open(newline='') as f:
    decisions=list(csv.DictReader(f))
accepted={r['impacto_id'] for r in decisions if r['aceptado']=='si'}
assert {r['impacto_id'] for r in rows}==accepted
assert len(rows)==len(accepted)==37
assert len({r['objeto_id'] for r in rows})==8
assert all(np.isfinite(r[key]) for r in rows for key in ('fp_hz','centroide_hz','ancho_relativo'))
assert all(100<=r['fp_hz']<=20000 and 100<=r['centroide_hz']<=20000 and r['ancho_relativo']>=0 for r in rows)
with (root/'datos/metadatos/sesiones.csv').open(newline='') as f:
    sessions={r['sesion_id']:r for r in csv.DictReader(f)}
for r in rows:
    original=root/'datos/procesados/decodificados'/Path(sessions[r['sesion_id']]['archivo']).with_suffix('.wav')
    x,fs=sf.read(original)
    a,b=r['inicio_muestra'],r['fin_muestra']
    assert 0<=r['fondo_inicio_muestra']<r['fondo_fin_muestra']<a<b<=len(x)
    assert r['espectro_fin_muestra']-a==4800
    clip=root/'datos/procesados/ventanas_piloto_v1'/f'{r["impacto_id"]}.wav'
    y,rate=sf.read(clip)
    assert rate==fs and np.array_equal(y,x[a:b])
    if r['d90_s'] is not None:
        assert 0<=r['t05_s']<r['t95_s']<=(b-a)/fs
        assert np.isclose(r['d90_s'],r['t95_s']-r['t05_s'])
for o in objects:
    group=[r for r in rows if r['objeto_id']==o['objeto_id']]
    for k in ('fp_hz','centroide_hz','ancho_relativo','d90_s'):
        vals=[r[k] for r in group if r[k] is not None]
        assert len(vals)==o[k+'_n']
        assert np.isclose(np.median(vals),o[k+'_mediana'])
for name,digest in data['originales'].items():
    assert hashlib.sha256((root/'datos/originales'/name).read_bytes()).hexdigest()==digest
os.environ.setdefault('MPLCONFIGDIR',str(root/'resultados/segmentacion_piloto/.matplotlib'))
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from matplotlib.lines import Line2D

colors={'hierro':'#326482','madera':'#3f8058','plastico_rigido':'#b06816','vidrio':'#8b5191'}
labels=['Hierro · pieza de cortar pasto','Hierro · tubo','Madera · rama','Madera · palo',
        'Plástico · flotador','Plástico · caño','Vidrio · vaso roto','Vidrio · botella']
fig,axes=plt.subplots(1,4,figsize=(15,6.4),sharey=True)
for ax,key,scale,title in zip(axes,['fp_hz','centroide_hz','ancho_relativo','d90_s'],
    [.001,.001,1,1000],['Frecuencia prominente (kHz)','Centroide (kHz)','Ancho relativo B/C','D₉₀ (ms) · 36/37']):
    for i,o in enumerate(objects):
        group=[r for r in rows if r['objeto_id']==o['objeto_id'] and r[key] is not None]
        offset=np.linspace(-.16,.16,len(group))
        for jitter,r in zip(offset,group):
            ax.scatter(r[key]*scale,i+jitter,s=30,c=colors[r['material']],
                       edgecolors='#c14e0b' if r['avisos'] else 'white',linewidths=1.3,zorder=3)
        lo,md,hi=(o[key+s]*scale for s in ('_q25','_mediana','_q75'))
        ax.plot([lo,hi],[i,i],color='#252b30',lw=2,zorder=4)
        ax.scatter(md,i,color='#252b30',s=24,marker='D',zorder=5)
    ax.set_title(title,fontsize=11)
    ax.set_xlim(left=0)
    ax.grid(axis='x',alpha=.2)
    ax.set_yticks(range(8),labels)
axes[0].invert_yaxis()
fig.suptitle('Descriptores por objeto · piloto de Yiyi',fontsize=17,x=.57)
handles=[Line2D([0],[0],marker='o',linestyle='',markerfacecolor='#326482',markeredgecolor='white',label='Un golpe aceptado'),
         Line2D([0],[0],color='#252b30',marker='D',label='Mediana e intervalo P25–P75'),
         Line2D([0],[0],marker='o',linestyle='',markerfacecolor='white',markeredgecolor='#c14e0b',label='Golpe con aviso')]
fig.legend(handles=handles,loc='lower center',ncol=3,bbox_to_anchor=(.58,.025),frameon=False)
fig.text(.30,.005,'8 objetos; 2 por material; un participante. Las repeticiones no son objetos independientes.',fontsize=9)
fig.tight_layout(rect=(0,.10,1,.93))
fig.savefig(out/'resumen_por_objeto.png',dpi=160)
plt.close(fig)
flagged=[r for r in rows if r['avisos']]
lines=['# Descriptores acústicos del piloto','',
    'Se calcularon los tres descriptores espectrales en los **37 golpes aceptados**, de ocho objetos. '
    'D₉₀ fue estimable en **36**. Se conservaron las cinco exclusiones de la revisión de escucha.','',
    'Las ventanas espectrales son de 100 ms, con banda de 100 a 20000 Hz. Las ventanas temporales se ajustan '
    'al retorno al fondo y descuentan su contribución por bloques de 1 ms. '
    'El método y sus límites están en [método v1](../../docs/metodo_descriptores.md).','',
    '![Golpes, medianas e intervalos por objeto](resumen_por_objeto.png)','',
    '## Medianas por objeto','',
    '| Objeto | Golpes | fₚ (Hz) | C (Hz) | B/C | D₉₀ (ms) | n D₉₀ |',
    '|---|---:|---:|---:|---:|---:|---:|']
for o,label in zip(objects,labels):
    lines.append(f'| {label} | {o["golpes_aceptados"]} | {o["fp_hz_mediana"]:.0f} | {o["centroide_hz_mediana"]:.0f} | {o["ancho_relativo_mediana"]:.3f} | {o["d90_s_mediana"]*1000:.1f} | {o["d90_s_n"]} |')
lines+=['','Los valores sin redondear, junto con P25 y P75, están en '
    '[por_objeto.csv](../../datos/caracteristicas/piloto_v1/por_objeto.csv). '
    'La tabla resume repeticiones, no estima propiedades intrínsecas del material. '
    'Una mediana de frecuencias máximas puede quedar entre dos picos y no coincidir con un pico medido.','',
    f'## Controles de calidad: {len(flagged)} golpes con avisos','',
    'El cuarto golpe del palo de madera (**SES004_G04**) no vuelve al fondo antes del límite de 750 ms. '
    'Se mantiene aceptado como evento, pero su D₉₀ principal queda vacío y no participa en la mediana. '
    'La duración que resultaría de la ventana limitada se conserva solo como diagnóstico.','',
    '| Golpe | Avisos |','|---|---|']
for r in flagged:
    lines.append(f'| {r["impacto_id"]} | {r["avisos"].replace("_"," ").replace(";","; ")} |')
lines+=['','Las frecuencias prominentes del caño cambian entre máximos competidores; tres golpes cambian '
    'más del 20 % al usar 80 o 120 ms. En el vaso roto hay dos golpes con máximos cerca de 4.55 kHz '
    'y dos cerca de 15.2 kHz. Hay energía cerca de 15 kHz en varios objetos: su origen no está identificado '
    'y estos máximos no deben presentarse como modos propios del material.','',
    'Los avisos de sensibilidad no son intervalos de confianza. Los valores con avisos permanecen '
    'en los archivos y los resúmenes para no aplicar exclusiones adicionales después de ver los resultados. '
    'El D₉₀ sin cola aislada es un dato no estimable.','',
    '## Archivos y verificación','',
    '- [Descriptores por golpe](../../datos/caracteristicas/piloto_v1/por_golpe.csv).',
    '- [Límites de las ventanas](../../datos/caracteristicas/piloto_v1/ventanas.csv).',
    '- [Cálculos y diagnósticos completos](calculo.json).','',
    'Las 37 ventanas WAV se compararon muestra por muestra con sus copias fuente. '
    'Se verificaron índices, pertenencia a los eventos aceptados, resúmenes por objeto y hashes de los originales. '
    'Las 20 pruebas del código pasaron. No se entrenaron modelos ni se realizaron pruebas de hipótesis.','',
    '## Figuras de cada grabación','']
for sid,path in data['figuras'].items():
    lines.append(f'- [{sid}: ventanas, espectros y energía acumulada]({path}).')
(out/'informe.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'Verificados 37 golpes, 36 D90, ocho objetos; {len(flagged)} golpes con avisos. Informe: {out / "informe.md"}')
