"""Comparación exploratoria de RF con exclusión completa de objetos."""

import csv
import json
import os
from collections import Counter
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import balanced_accuracy_score, confusion_matrix
from sklearn.model_selection import LeaveOneGroupOut

from .inspection import sha256_file

FEATURE_SETS = {'A_espectral':['fp_hz','centroide_hz','ancho_relativo'],
                'B_temporal':['d90_s'],
                'C_combinado':['fp_hz','centroide_hz','ancho_relativo','d90_s']}


def object_weights(y, groups):
    """Igual masa por clase y, dentro de cada clase, por objeto."""
    y,groups=np.asarray(y),np.asarray(groups)
    labels={}
    for group in np.unique(groups):
        target=np.unique(y[groups==group])
        if len(target)!=1:
            raise ValueError('Un objeto tiene varias etiquetas.')
        labels[group]=target[0]
    per_class=Counter(labels.values())
    per_object=Counter(groups)
    w=np.array([1/(per_object[g]*per_class[c]) for c,g in zip(y,groups)])
    return w*len(w)/w.sum()


def object_folds(y, groups):
    y,groups=np.asarray(y),np.asarray(groups)
    labels={g:np.unique(y[groups==g]) for g in np.unique(groups)}
    if any(len(c)!=1 for c in labels.values()):
        raise ValueError('Un objeto tiene varias etiquetas.')
    if min(Counter(c[0] for c in labels.values()).values())<2:
        raise ValueError('Se requieren al menos dos objetos por clase para excluir uno.')
    folds=list(LeaveOneGroupOut().split(np.zeros((len(y),1)),y,groups))
    for train,test in folds:
        if set(groups[train])&set(groups[test]):
            raise ValueError('Fuga entre objetos de entrenamiento y evaluación.')
        if set(y[train])!=set(y):
            raise ValueError('Falta una categoría en entrenamiento.')
    return folds


def aggregate_probabilities(groups, probabilities):
    groups=np.asarray(groups)
    return {g:np.mean(probabilities[groups==g],axis=0) for g in sorted(set(groups))}


def _write_csv(path, rows):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def train_pilot(root: Path):
    output=root/'resultados/modelos_piloto_v1'
    if output.exists():
        raise ValueError('Ya existen resultados de modelos; no se sobrescriben.')
    config=json.loads((root/'config.json').read_text())
    settings=config['plan_analisis']['random_forest']
    source=root/'datos/caracteristicas/piloto_v1/por_golpe.csv'
    with source.open(newline='') as f:
        all_rows=list(csv.DictReader(f))
    keys=FEATURE_SETS['C_combinado']
    rows,excluded=[],[]
    for row in all_rows:
        if all(row[k] and np.isfinite(float(row[k])) for k in keys):
            rows.append(row)
        else:
            excluded.append(dict(impacto_id=row['impacto_id'],motivo='Falta al menos un descriptor: misma exclusión para A, B y C.'))
    if len({r['impacto_id'] for r in rows})!=len(rows):
        raise ValueError('Hay impactos duplicados.')
    y=np.array([r['material'] for r in rows])
    groups=np.array([r['objeto_id'] for r in rows])
    classes=np.array(sorted(set(y)))
    folds=object_folds(y,groups)
    object_ids=sorted(set(groups))
    object_truth=np.array([y[groups==g][0] for g in object_ids])
    output.mkdir(parents=True)
    (output/'modelos').mkdir()
    partitions=[]
    for train,test in folds:
        partitions.append(dict(objeto_excluido=str(groups[test][0]),
            objetos_entrenamiento=sorted(set(groups[train])),
            impactos_entrenamiento=[rows[i]['impacto_id'] for i in train],
            impactos_evaluacion=[rows[i]['impacto_id'] for i in test],
            clases_entrenamiento=sorted(set(y[train]))))
    predictions,object_predictions,metrics=[],[],{}
    correct_by_model={}
    for name,features in FEATURE_SETS.items():
        x=np.array([[float(r[k]) for k in features] for r in rows])
        probabilities=np.full((len(rows),len(classes)),np.nan)
        for train,test in folds:
            model=RandomForestClassifier(**settings,n_jobs=1)
            model.fit(x[train],y[train],sample_weight=object_weights(y[train],groups[train]))
            assert np.array_equal(model.classes_,classes)
            probabilities[test]=model.predict_proba(x[test])
        assert np.isfinite(probabilities).all()
        assert np.allclose(probabilities.sum(axis=1),1)
        hit_pred=classes[np.argmax(probabilities,axis=1)]
        aggregated=aggregate_probabilities(groups,probabilities)
        object_pred=np.array([classes[np.argmax(aggregated[g])] for g in object_ids])
        correct=object_pred==object_truth
        correct_by_model[name]=correct
        for i,row in enumerate(rows):
            predictions.append(dict(modelo=name,impacto_id=row['impacto_id'],objeto_id=row['objeto_id'],
                real=row['material'],prediccion=hit_pred[i],correcto=bool(hit_pred[i]==y[i]),
                **{f'p_{c}':float(p) for c,p in zip(classes,probabilities[i])}))
        for i,g in enumerate(object_ids):
            p=aggregated[g]
            object_predictions.append(dict(modelo=name,objeto_id=g,real=object_truth[i],
                prediccion=object_pred[i],correcto=bool(correct[i]),golpes=int(np.sum(groups==g)),
                empate=bool(np.sum(np.isclose(p,p.max(),atol=1e-12,rtol=0))>1),
                **{f'p_{c}':float(v) for c,v in zip(classes,p)}))
        metrics[name]=dict(predictores=features,aciertos_objetos=int(correct.sum()),objetos=len(object_ids),
            exactitud_balanceada_objetos=float(balanced_accuracy_score(object_truth,object_pred)),
            exactitud_balanceada_golpes_secundaria=float(balanced_accuracy_score(y,hit_pred)),
            matriz_confusion_objetos=confusion_matrix(object_truth,object_pred,labels=classes).tolist())
        final=RandomForestClassifier(**settings,n_jobs=1)
        final.fit(x,y,sample_weight=object_weights(y,groups))
        joblib.dump(dict(modelo=final,predictores=features,clases=classes.tolist(),
            unidad_prediccion='promedio de probabilidades de los golpes del objeto',
            sha256_caracteristicas=sha256_file(source),configuracion=settings,
            metodo_caracteristicas='piloto_v1',uso='prototipo exploratorio; probabilidades sin calibrar'),
            output/'modelos'/f'{name}.joblib')
    # Remuestreo pareado y estratificado de predicciones OOF ya calculadas.
    # Describe sensibilidad a ocho objetos; no reentrena ni elimina dependencia entre folds.
    rng=np.random.default_rng(2026)
    indices=np.concatenate([rng.choice(np.flatnonzero(object_truth==c),
        size=(10000,int(np.sum(object_truth==c))),replace=True) for c in classes],axis=1)
    boot={name:np.mean(correct[indices],axis=1) for name,correct in correct_by_model.items()}
    for name in metrics:
        metrics[name]['rango_descriptivo_remuestreo_95']=np.quantile(boot[name],[.025,.975]).tolist()
    differences={}
    for other in ('A_espectral','B_temporal'):
        delta=boot['C_combinado']-boot[other]
        differences[f'C_menos_{other}']=dict(diferencia=metrics['C_combinado']['exactitud_balanceada_objetos']-metrics[other]['exactitud_balanceada_objetos'],
            rango_descriptivo_remuestreo_95=np.quantile(delta,[.025,.975]).tolist())
    result=dict(tipo='exploratorio_sin_ajuste_hiperparametros',
        validacion='LeaveOneGroupOut por objeto; ocho rondas con siete objetos de entrenamiento.',
        motivo_cambio_validacion='Solo hay un participante; no se puede excluir un participante completo conservando entrenamiento.',
        configuracion=settings,ponderacion='Cada clase tiene el mismo peso; dentro de la clase cada objeto tiene el mismo peso total.',
        agregacion='Promedio aritmético de probabilidades por golpe del objeto excluido. Empates: primera etiqueta en orden alfabético.',
        incertidumbre='Percentiles 2.5–97.5 de 10000 remuestreos estratificados por clase y pareados entre modelos de las ocho predicciones por objeto. Solo sensibilidad descriptiva condicionada a los objetos observados; los entrenamientos de los folds se solapan. No es un intervalo de generalización ni una prueba de superioridad.',
        golpes=len(rows),objetos=len(object_ids),clases=classes.tolist(),
        objetos_por_clase=dict(Counter(object_truth)),excluidos_comunes=excluded,
        impactos_con_avisos_incluidos=[r['impacto_id'] for r in rows if r['avisos']],
        referencia_uniforme_exactitud_balanceada_esperada=1/len(classes),
        referencia_constante_exactitud_balanceada_observada=float(balanced_accuracy_score(object_truth,np.repeat(classes[0],len(object_truth)))),
        referencia_constante_clase=str(classes[0]),
        sha256_caracteristicas=sha256_file(source),
        sha256_impactos=sha256_file(root/'datos/metadatos/impactos.csv'),
        versiones={name:version(name) for name in ('numpy','scipy','scikit-learn','joblib')},
        particiones=partitions,metricas=metrics,diferencias=differences,
        predicciones_objetos=object_predictions)
    (output/'evaluacion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    _write_csv(output/'predicciones_objetos.csv',object_predictions)
    _write_csv(output/'predicciones_golpes.csv',predictions)
    _write_csv(output/'metricas.csv',[dict(modelo=name,
        exactitud_balanceada_objetos=m['exactitud_balanceada_objetos'],
        aciertos_objetos=m['aciertos_objetos'],objetos=m['objetos'],
        rango_descriptivo_inferior=m['rango_descriptivo_remuestreo_95'][0],
        rango_descriptivo_superior=m['rango_descriptivo_remuestreo_95'][1]) for name,m in metrics.items()])
    write_report(root,result)
    return result


def write_report(root,result):
    output=root/'resultados/modelos_piloto_v1'
    os.environ.setdefault('MPLCONFIGDIR',str(root/'resultados/segmentacion_piloto/.matplotlib'))
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    labels=['Hierro','Madera','Plástico','Vidrio']
    fig,axes=plt.subplots(1,3,figsize=(12,4.5))
    for ax,(name,metric) in zip(axes,result['metricas'].items()):
        cm=np.array(metric['matriz_confusion_objetos'])
        ax.imshow(cm,cmap='Blues',vmin=0,vmax=2)
        for i in range(4):
            for j in range(4):
                ax.text(j,i,str(cm[i,j]),ha='center',va='center',color='white' if cm[i,j]==2 else '#163345')
        ax.set_xticks(range(4),labels,rotation=35,ha='right')
        ax.set_yticks(range(4),labels)
        ax.set(xlabel='Predicción',ylabel='Material declarado',
            title=f'{name.replace("_"," ")}\n{metric["aciertos_objetos"]}/8 · {metric["exactitud_balanceada_objetos"]:.1%}')
    fig.suptitle('Objetos no vistos en entrenamiento · piloto exploratorio',fontsize=14)
    fig.tight_layout()
    fig.savefig(output/'confusiones.png',dpi=160)
    plt.close(fig)
    text=['# Primera prueba de clasificación','',
        '**Evaluación exploratoria de ocho objetos, dos por material, de un participante.** '
        'Los resultados se refieren a objetos excluidos del entrenamiento en cada ronda.','',
        '| Modelo | Predictores | Aciertos por objeto | Exactitud balanceada | Rango descriptivo de remuestreo |',
        '|---|---|---:|---:|---:|']
    for name,m in result['metricas'].items():
        lo,hi=m['rango_descriptivo_remuestreo_95']
        text.append(f'| {name} | {", ".join(m["predictores"])} | {m["aciertos_objetos"]}/8 | {m["exactitud_balanceada_objetos"]:.1%} | {lo:.1%}–{hi:.1%} |')
    text+=['','La referencia de predicción uniforme tiene una exactitud balanceada esperada del 25 %. '
        'Predecir siempre hierro en los ocho objetos también obtiene 25 %. '
        'No se usa la exactitud sobre los datos de entrenamiento como resultado.','',
        '![Matrices de confusión por objeto](confusiones.png)','',
        '## Qué ocurrió con cada objeto','',
        '| Objeto | Material declarado | Espectral | Temporal | Combinado |',
        '|---|---|---|---|---|']
    predictions=result['predicciones_objetos']
    with (root/'datos/metadatos/objetos.csv').open(newline='') as f:
        names={r['objeto_id']:r['descripcion'] for r in csv.DictReader(f)}
    for oid in sorted({r['objeto_id'] for r in predictions}):
        sample=[r for r in predictions if r['objeto_id']==oid]
        guesses=[]
        for name in FEATURE_SETS:
            r=next(r for r in sample if r['modelo']==name)
            guesses.append(r['prediccion'].replace('_',' ') + (' ✓' if r['correcto'] else ' ✗'))
        text.append(f'| {names[oid]} ({oid}) | {sample[0]["real"].replace("_"," ")} | '+ ' | '.join(guesses)+' |')
    text+=['','## Método y límites','',
        '- Se compararon los modelos con los mismos 36 golpes de ocho objetos y las mismas ocho particiones. '
        'SES004_G04 se excluyó de los tres porque no tiene D90 estimable. Los siete golpes completos con avisos se conservaron, sin nuevas exclusiones.',
        '- En cada ronda se entrenó con siete objetos y se evaluaron todos los golpes disponibles del octavo. '
        'Se comprobó que ningún objeto ni golpe apareciera simultáneamente en entrenamiento y evaluación.',
        '- Los bosques usan 300 árboles, profundidad máxima 3, mínimo 3 muestras por hoja y semilla 42. '
        'Se aplicaron pesos para igualar clases y objetos dentro de cada clase. No se buscaron hiperparámetros ni se seleccionaron características según el resultado.',
        '- La predicción por objeto es la clase con mayor promedio de probabilidades de sus golpes. '
        'Estas probabilidades no están calibradas. La métrica principal es el promedio de los aciertos por clase '
        '(exactitud balanceada); como hay dos objetos por clase, aquí coincide con la fracción de objetos acertados.',
        '- Solo hay ocho predicciones por modelo; un objeto cambia el resultado en 12.5 puntos porcentuales. '
        'Los rangos de remuestreo son descriptivos: no reentrenan modelos y no resuelven la dependencia entre rondas ni la escasa diversidad de objetos.',
        '- La validación por participante del diseño inicial no puede ejecutarse con una sola persona. '
        'Esta prueba por objeto es una evaluación provisional, que no mide generalización a otros teléfonos o integrantes.','',
        '## Comparación del combinado','',
        '| Diferencia | Puntos porcentuales | Rango descriptivo pareado |',
        '|---|---:|---:|']
    for name,d in result['diferencias'].items():
        lo,hi=d['rango_descriptivo_remuestreo_95']
        text.append(f'| {name} | {d["diferencia"]*100:+.1f} | {lo*100:+.1f} a {hi*100:+.1f} |')
    text+=['','Esta comparación no confirma superioridad ni valida H3. Hace falta ampliar los objetos '
        'y comprobar si el desempeño se mantiene con el protocolo fijado.','',
        '## Archivos guardados','',
        '- `predicciones_objetos.csv`: predicciones obtenidas sin ver cada objeto en entrenamiento.',
        '- `predicciones_golpes.csv`: resultados secundarios por repetición.',
        '- `evaluacion.json`: particiones, versiones, pesos, métricas y trazabilidad de entradas.',
        '- `modelos/`: tres prototipos entrenados con los 36 golpes completos para futuras pruebas; '
        'no se les atribuye la evaluación de un conjunto independiente adicional.','',
        '## Referencias del procedimiento','',
        '- [RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html).',
        '- [LeaveOneGroupOut](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.LeaveOneGroupOut.html).',
        '- [Exactitud balanceada](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.balanced_accuracy_score.html).','']
    (output/'informe.md').write_text('\n'.join(text),encoding='utf-8')
