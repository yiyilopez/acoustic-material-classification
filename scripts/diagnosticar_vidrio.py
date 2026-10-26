"""Auditoría de señales y tres cambios de medición comunes, sin reemplazar v1."""

import csv
import json
import os
from pathlib import Path

import numpy as np
import soundfile as sf
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score, confusion_matrix

from acustica_materiales.features import periodogram, spectral_moments, DEFAULTS
from acustica_materiales.modeling import object_folds, object_weights, aggregate_probabilities
from acustica_materiales.inspection import sha256_file

root=Path(__file__).resolve().parents[1]
out=root/'resultados/diagnostico_vidrio_v1'
if out.exists():
    raise ValueError('Ya existe el diagnóstico; no se sobrescribe.')
calc=json.loads((root/'resultados/descriptores_piloto/calculo.json').read_text())
evaluation=json.loads((root/'resultados/modelos_piloto_v1/evaluacion.json').read_text())
settings=calc['configuracion']
records=calc['resultados']
audit={r['impacto_id']:r for r in calc['ventanas']}
with (root/'datos/metadatos/sesiones.csv').open(newline='') as f:
    sessions={r['sesion_id']:r for r in csv.DictReader(f)}
with (root/'datos/metadatos/objetos.csv').open(newline='') as f:
    names={r['objeto_id']:r['descripcion'] for r in csv.DictReader(f)}
audio={sid:sf.read(root/'datos/procesados/decodificados'/Path(s['archivo']).with_suffix('.wav')) for sid,s in sessions.items()}
checks=[]
alternate={'resta_fondo':{},'sin_ataque_10ms':{},'banda_hasta_10k':{}}
spectra={}
for r in records:
    iid=r['impacto_id']; x,fs=audio[r['sesion_id']]
    start=r['inicio_muestra']; n=round(.1*fs)
    f,p=periodogram(x[start:start+n],fs,settings)
    a,b=r['fondo_inicio_muestra'],r['fondo_fin_muestra']
    background=np.mean([periodogram(x[k:k+n],fs,settings)[1] for k in range(a,b-n+1,n)],axis=0)
    band=(f>=100)&(f<=20000); high=(f>=14500)&(f<=15800)
    ratio=float(p[high].sum()/p[band].sum())
    high_noise_ratio=float(10*np.log10(p[high].sum()/background[high].sum()))
    # Diagnósticos definidos para todos los objetos antes de comparar sus aciertos.
    alternate['resta_fondo'][iid]=spectral_moments(f[band],np.maximum(p[band]-background[band],0))
    band10=(f>=100)&(f<=10000)
    alternate['banda_hasta_10k'][iid]=spectral_moments(f[band10],p[band10])
    delayed_start=start+round(.01*fs)
    next_events=[v['inicio_muestra'] for v in calc['ventanas'] if v['impacto_id'].startswith(r['sesion_id']) and v['inicio_muestra']>start]
    assert delayed_start+n<=min(next_events+[len(x)])
    ff,pp=periodogram(x[delayed_start:delayed_start+n],fs,settings)
    bb=(ff>=100)&(ff<=20000)
    alternate['sin_ataque_10ms'][iid]=spectral_moments(ff[bb],pp[bb])
    checks.append(dict(impacto_id=iid,objeto_id=r['objeto_id'],
        material=r['material'],fp_hz=r['fp_hz'],centroide_hz=r['centroide_hz'],d90_s=r['d90_s'],
        relacion_energia_fondo_db=r['relacion_energia_fondo_db'],
        energia_14_5_15_8k_fraccion=ratio,relacion_banda_alta_fondo_db=high_noise_ratio,
        centroide_cambio_resta_fondo_relativo=abs(alternate['resta_fondo'][iid]['centroide_hz']-r['centroide_hz'])/r['centroide_hz'],
        **{name+'_fp_hz':value[iid]['fp_hz'] for name,value in alternate.items()}))
    spectra[iid]=(f,p,background)
rows=[r for r in records if r['d90_s'] is not None]
assert len(rows)==36
y=np.array([r['material'] for r in rows]); groups=np.array([r['objeto_id'] for r in rows])
classes=np.array(evaluation['clases']); folds=object_folds(y,groups)
objects=sorted(set(groups)); truth=np.array([y[groups==g][0] for g in objects])
with (root/'resultados/modelos_piloto_v1/predicciones_golpes.csv').open(newline='') as f:
    temporal={r['impacto_id']:r for r in csv.DictReader(f) if r['modelo']=='B_temporal'}
temporal_p=np.array([[float(temporal[r['impacto_id']]['p_'+c]) for c in classes] for r in rows])
metrics={}; predictions=[]
for variant,values in alternate.items():
    metrics[variant]={}
    pp_a=None
    for model_name in ('A_espectral','C_combinado'):
        keys=['fp_hz','centroide_hz','ancho_relativo']
        x=np.array([[values[r['impacto_id']][k] for k in keys]+([r['d90_s']] if model_name=='C_combinado' else []) for r in rows])
        prob=np.full((len(rows),4),np.nan)
        for train,test in folds:
            assert not set(groups[train])&set(groups[test])
            model=RandomForestClassifier(**evaluation['configuracion'],n_jobs=1)
            model.fit(x[train],y[train],sample_weight=object_weights(y[train],groups[train]))
            assert np.array_equal(model.classes_,classes)
            prob[test]=model.predict_proba(x[test])
        if model_name=='A_espectral':
            pp_a=prob.copy()
        grouped=aggregate_probabilities(groups,prob)
        guessed=np.array([classes[np.argmax(grouped[g])] for g in objects])
        metrics[variant][model_name]=dict(aciertos=int(np.sum(guessed==truth)),
            exactitud_balanceada=float(balanced_accuracy_score(truth,guessed)),
            aciertos_vidrio=int(np.sum((guessed==truth)&(truth=='vidrio'))),
            matriz_confusion=confusion_matrix(truth,guessed,labels=classes).tolist())
        for i,g in enumerate(objects):
            predictions.append(dict(variante=variant,modelo=model_name,objeto_id=g,real=truth[i],prediccion=guessed[i],
                **{'p_'+c:float(v) for c,v in zip(classes,grouped[g])}))
    grouped=aggregate_probabilities(groups,.5*(pp_a+temporal_p))
    guessed=np.array([classes[np.argmax(grouped[g])] for g in objects])
    metrics[variant]['fusion_50_50']=dict(aciertos=int(np.sum(guessed==truth)),
        exactitud_balanceada=float(balanced_accuracy_score(truth,guessed)),
        aciertos_vidrio=int(np.sum((guessed==truth)&(truth=='vidrio'))))
    for i,g in enumerate(objects):
        predictions.append(dict(variante=variant,modelo='fusion_50_50',objeto_id=g,real=truth[i],prediccion=guessed[i],
            **{'p_'+c:float(v) for c,v in zip(classes,grouped[g])}))
out.mkdir(parents=True)
result=dict(alcance='Diagnóstico posterior al primer ensayo; no validación independiente ni selección de parámetros.',
    variantes=dict(resta_fondo='Resta espectral del promedio de tres fondos de 100 ms y rectificación a cero.',
        sin_ataque_10ms='Misma ventana de 100 ms y banda 100–20000 Hz, desplazada 10 ms después del inicio ajustado. D90 sin cambios.',
        banda_hasta_10k='Misma ventana original; banda reducida a 100–10000 Hz. D90 sin cambios.'),
    metricas=metrics,control_senales=checks,predicciones=predictions,
    originales=calc['originales'],sha256_caracteristicas=evaluation['sha256_caracteristicas'])
(out/'diagnostico.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
for filename,rs in [('control_senales.csv',checks),('predicciones.csv',predictions)]:
    with (out/filename).open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rs[0]));writer.writeheader();writer.writerows(rs)

os.environ.setdefault('MPLCONFIGDIR',str(root/'resultados/segmentacion_piloto/.matplotlib'))
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
fig,axes=plt.subplots(2,2,figsize=(13,8.5))
for row,oid in enumerate(('OBJ007','OBJ008')):
    ax=axes[row,0]
    for r in [v for v in records if v['objeto_id']==oid]:
        f,p,bg=spectra[r['impacto_id']]; mask=(f>=100)&(f<=20000)
        normalized=p[mask]/p[mask].max()
        ax.plot(f[mask]/1000,10*np.log10(np.maximum(normalized,1e-9)),lw=.7,label=r['impacto_id'].split('_')[1])
    ax.axvspan(14.5,15.8,color='#d5b24b',alpha=.2)
    ax.set(title=names[oid]+' · espectros por golpe',xlabel='Frecuencia (kHz)',ylabel='Potencia relativa al máximo (dB)',ylim=(-65,3))
    ax.legend(fontsize=8,ncol=3)
    ax=axes[row,1]
    for compare in [oid,'OBJ002' if oid=='OBJ007' else 'OBJ005']:
        sample=[v for v in records if v['objeto_id']==compare]
        powers=[]; backgrounds=[]
        for r in sample:
            f,p,bg=spectra[r['impacto_id']]; mask=(f>=100)&(f<=20000)
            norm=np.sum(p[mask]);powers.append(p[mask]/norm);backgrounds.append(bg[mask]/norm)
        normalized=np.mean(powers,axis=0);noise=np.mean(backgrounds,axis=0)
        line=ax.plot(f[mask]/1000,10*np.log10(np.maximum(normalized,1e-12)),lw=.9,label=names[compare])[0]
        ax.plot(f[mask]/1000,10*np.log10(np.maximum(noise,1e-12)),lw=.6,color=line.get_color(),linestyle=':',alpha=.65)
    ax.set(title='Comparación de forma espectral · fondo punteado',xlabel='Frecuencia (kHz)',ylabel='Fracción de potencia por bin (dB)',ylim=(-90,-5))
    ax.legend(fontsize=8)
fig.suptitle('Vidrio: señales distintas y solapamiento con otros objetos',fontsize=15)
fig.tight_layout()
fig.savefig(out/'espectros_vidrio.png',dpi=150)
plt.close(fig)
for name,digest in calc['originales'].items():
    assert sha256_file(root/'datos/originales'/name)==digest
print(json.dumps(metrics,ensure_ascii=False,indent=2))
print('Control vidrio:',json.dumps([r for r in checks if r['material']=='vidrio'],ensure_ascii=False))
