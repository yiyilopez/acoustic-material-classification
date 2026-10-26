# Diagnóstico posterior a la primera prueba

**Exploratorio: estos ocho objetos ya fueron utilizados para evaluar los modelos originales.** Los nuevos porcentajes sirven para orientar el desarrollo; no constituyen una validación independiente de mejoras.

Se fijaron tres variantes antes de ejecutar este diagnóstico, sin búsqueda de semillas, combinaciones de variables ni hiperparámetros. Usan los mismos 36 golpes y excluyen objetos completos en las mismas rondas.

| Variante | Objetos acertados | Exactitud balanceada |
|---|---:|---:|
| fusion_50_50 | 4/8 | 50.0% |
| RF_todas_variables | 1/8 | 12.5% |
| logistica_regularizada | 2/8 | 25.0% |

## Qué cambia

- Fusión 50/50: promedia las probabilidades del espectral y el temporal ya calculadas sin ver cada objeto. No supone que la suma de características sea equivalente a combinar decisiones.
- RF con todas las variables: permite considerar los cuatro descriptores en cada división. El combinado original usa sqrt y considera dos; el espectral usa sqrt y considera una. No se modifica profundidad, hojas, número de árboles ni semilla.
- Regresión logística: compara un modelo lineal regularizado con los cuatro descriptores. El escalado y el ajuste utilizan exclusivamente los objetos de entrenamiento de cada ronda.

El combinado original coincidió con el espectral en siete de los ocho objetos. La pieza de cortar pasto cambió de hierro a vidrio; los otros siete resultados fueron iguales. Esto describe las decisiones, pero no identifica por sí solo la causa de los errores. Los objetos son pocos y geométricamente diversos, algunos predictores son sensibles al ruido y cada ronda solo conserva otro objeto de la misma categoría que el objeto evaluado.

La escala distinta de Hz y segundos no es por sí sola la explicación del fallo del bosque. La incertidumbre dominante sigue siendo la escasa diversidad de objetos y la reutilización de la muestra para desarrollo.

Los originales y los modelos de la primera prueba se conservaron. No se modificaron los descriptores para favorecer una variante.

Referencia de configuración: [RandomForestClassifier](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html). La elección de ajustes tras observar puntuaciones puede sesgar la evaluación: [validación anidada y no anidada](https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html).
