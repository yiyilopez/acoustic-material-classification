"""Tres diagnósticos prefijados; no sustituyen la primera evaluación."""

import csv
import json
import os
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from acustica_materiales.modeling import object_weights, object_folds, aggregate_probabilities

root=Path(__file__).resolve().parents[1]
out=root/'resultados/diagnostico_modelos_v1'
if out.exists():
    raise ValueError('Ya existe el diagnóstico; no se sobrescribe.')
previous=root/'resultados/modelos_piloto_v1'
evaluation=json.loads((previous/'evaluacion.json').read_text())
with (root/'datos/caracteristicas/piloto_v1/por_golpe.csv').open(newline='') as f:
    raw=list(csv.DictReader(f))
features=['fp_hz','centroide_hz','ancho_relativo','d90_s']
rows=[r for r in raw if all(r[k] for k in features)]
x=np.array([[float(r[k]) for k in features] for r in rows])
y=np.array([r['material'] for r in rows])
groups=np.array([r['objeto_id'] for r in rows])
classes=np.array(evaluation['clases'])
folds=object_folds(y,groups)
with (previous/'predicciones_golpes.csv').open(newline='') as f:
    old=list(csv.DictReader(f))
lookup={(r['modelo'],r['impacto_id']):r for r in old}
probabilities={}
probabilities['fusion_50_50']=np.mean([np.array([[float(lookup[(m,r['impacto_id'])]['p_'+c]) for c in classes] for r in rows])
    for m in ('A_espectral','B_temporal')],axis=0)
probabilities['RF_todas_variables']=np.full((len(rows),4),np.nan)
probabilities['logistica_regularizada']=np.full((len(rows),4),np.nan)
for train,test in folds:
    assert not set(groups[train])&set(groups[test])
    weights=object_weights(y[train],groups[train])
    rf=RandomForestClassifier(**evaluation['configuracion'],max_features=1.0,n_jobs=1)
    rf.fit(x[train],y[train],sample_weight=weights)
    assert np.array_equal(rf.classes_,classes)
    probabilities['RF_todas_variables'][test]=rf.predict_proba(x[test])
    # El escalado se ajusta exclusivamente al entrenamiento de cada ronda.
    linear=make_pipeline(StandardScaler(),LogisticRegression(C=1,max_iter=3000,solver='lbfgs'))
    linear.fit(x[train],y[train],standardscaler__sample_weight=weights,
               logisticregression__sample_weight=weights)
    assert np.array_equal(linear.classes_,classes)
    probabilities['logistica_regularizada'][test]=linear.predict_proba(x[test])
objects=sorted(set(groups))
truth=np.array([y[groups==g][0] for g in objects])
metrics={}
predictions=[]
for name,p in probabilities.items():
    assert np.isfinite(p).all() and np.allclose(p.sum(axis=1),1)
    grouped=aggregate_probabilities(groups,p)
    guessed=np.array([classes[np.argmax(grouped[g])] for g in objects])
    metrics[name]=dict(aciertos=int(np.sum(guessed==truth)),objetos=len(objects),
        exactitud_balanceada=float(balanced_accuracy_score(truth,guessed)),
        matriz_confusion=confusion_matrix(truth,guessed,labels=classes).tolist())
    for i,g in enumerate(objects):
        predictions.append(dict(variante=name,objeto_id=g,real=truth[i],prediccion=guessed[i],
            correcto=bool(guessed[i]==truth[i]),**{'p_'+c:float(v) for c,v in zip(classes,grouped[g])}))
out.mkdir(parents=True)
result=dict(estado='diagnostico_exploratorio_posterior_a_ver_resultados_iniciales',
    advertencia='Se reutilizan los mismos ocho objetos. Comparar variantes no proporciona una nueva evaluación independiente. No se selecciona un ganador definitivo.',
    configuraciones=dict(fusion_50_50='Media de probabilidades OOF de A y B; pesos 50/50 fijados sin búsqueda.',
        RF_todas_variables='Mismos parámetros del combinado original; max_features=1.0 en lugar de sqrt.',
        logistica_regularizada='Cuatro predictores; StandardScaler ponderado dentro de cada fold; regresión logística C=1, sin selección de C.'),
    golpes=len(rows),objetos=objects,particiones=evaluation['particiones'],
    metricas=metrics,predicciones=predictions)
(out/'diagnostico.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
with (out/'predicciones.csv').open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(predictions[0]));writer.writeheader();writer.writerows(predictions)
report=['# Diagnóstico posterior a la primera prueba','',
    '**Exploratorio: estos ocho objetos ya fueron utilizados para evaluar los modelos originales.** '
    'Los nuevos porcentajes sirven para orientar el desarrollo; no constituyen una validación independiente de mejoras.','',
    'Se fijaron tres variantes antes de ejecutar este diagnóstico, sin búsqueda de semillas, combinaciones de variables ni hiperparámetros. '
    'Usan los mismos 36 golpes y excluyen objetos completos en las mismas rondas.','',
    '| Variante | Objetos acertados | Exactitud balanceada |','|---|---:|---:|']
for name,m in metrics.items():
    report.append(f'| {name} | {m["aciertos"]}/8 | {m["exactitud_balanceada"]:.1%} |')
report+=['','## Qué cambia','',
    '- Fusión 50/50: promedia las probabilidades del espectral y el temporal ya calculadas sin ver cada objeto. No supone que la suma de características sea equivalente a combinar decisiones.',
    '- RF con todas las variables: permite considerar los cuatro descriptores en cada división. El combinado original usa sqrt y considera dos; el espectral usa sqrt y considera una. No se modifica profundidad, hojas, número de árboles ni semilla.',
    '- Regresión logística: compara un modelo lineal regularizado con los cuatro descriptores. El escalado y el ajuste utilizan exclusivamente los objetos de entrenamiento de cada ronda.','',
    'El combinado original coincidió con el espectral en siete de los ocho objetos. La pieza de cortar pasto cambió '
    'de hierro a vidrio; los otros siete resultados fueron iguales. Esto describe las decisiones, pero no identifica '
    'por sí solo la causa de los errores. Los objetos son pocos y geométricamente diversos, algunos predictores son '
    'sensibles al ruido y cada ronda solo conserva otro objeto de la misma categoría que el objeto evaluado.','',
    'La escala distinta de Hz y segundos no es por sí sola la explicación del fallo del bosque. '
    'La incertidumbre dominante sigue siendo la escasa diversidad de objetos y la reutilización de la muestra para desarrollo.','',
    'Los originales y los modelos de la primera prueba se conservaron. No se modificaron los descriptores para favorecer una variante.','',
    'Referencia de configuración: [RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html). '
    'La elección de ajustes tras observar puntuaciones puede sesgar la evaluación: '
    '[validación anidada y no anidada](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).','']
(out/'informe.md').write_text('\n'.join(report))
print(json.dumps(metrics,ensure_ascii=False,indent=2))
