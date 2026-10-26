# Plan por etapas

## 1. Preparar e inspeccionar el piloto

Implementado: plantillas, validación de metadatos e inventario con formas de onda.
Se incorporaron ocho grabaciones de dos objetos por categoría, de Yiyi,
con condiciones declaradas y copias WAV verificadas.
La meta inicial sigue siendo 16 objetos y al menos tres golpes por objeto.

## 2. Acordar y verificar segmentación

Determinar cómo detectar inicio y final de los golpes con referencia al fondo,
manteniendo revisión manual. Documentar golpes dobles, colas truncadas y recorte.
Implementada una propuesta preliminar de segmentos con índices de muestra,
copias sin normalizar y página de escucha. La revisión de Yiyi aceptó 37
y excluyó cinco eventos, con motivos conservados.
Fijar las reglas después de inspeccionar el piloto y antes de ampliar la muestra.
Probar que los límites se conservan respecto del original.

## 3. Extraer los cuatro predictores

Implementar frecuencia prominente, centroide ponderado por potencia,
ancho de banda relativo B/C y duración energética D90.
Implementado y calculado: 37 espectros y 36 D90 estimables. Método común en
metodo_descriptores.md y configuración en config.json. Un golpe de madera
queda sin D90 por cola no aislada; ocho golpes llevan avisos de calidad o sensibilidad.
Fijar banda, ventana, selección de canal y tratamiento del ruido de forma común.
Documentar el efecto de cada decisión.

Verificaciones necesarias: tono de frecuencia conocida, momentos de un
espectro de referencia, duración energética de una señal conocida,
invariancia a ganancia constante sobre el mismo segmento sin recorte,
y manejo explícito de silencio, ruido y segmentos truncados.
Para una señal de potencia constante de duración T, el D90 ideal es 0.9 T;
la tolerancia de la prueba tendrá en cuenta el muestreo y la convención discreta.

Los ensayos sintéticos comprueban cálculos; no demuestran que una característica
sea un buen indicador del material en grabaciones reales.

## 4. Comparar objetos

Examinar espectros, formas de onda y repetibilidad. Resumir por objeto y comparar
los cuatro grupos. Mantener separadas las variaciones de golpe, objeto y bloque.
Tau y eta se estimarán solo si existen modos y decaimientos defendibles.

## 5. Clasificar

Primera prueba exploratoria implementada, sin búsqueda de hiperparámetros:
36 golpes completos de ocho objetos, con pesos que equilibran clases y objetos.
LeaveOneGroupOut excluye un objeto completo por ronda. Resultados por objeto:
A 2/8 (25 %), B 3/8 (37.5 %) y C 1/8 (12.5 %). No se confirma superioridad
del combinado. Se guardaron predicciones, particiones, sensibilidad descriptiva
por remuestreo y modelos finales en resultados/modelos_piloto_v1/.

Modelo A: frecuencia prominente, centroide y ancho relativo.
Modelo B: D90.
Modelo C: los cuatro predictores.

Mantener las mismas particiones para A, B y C y una referencia trivial.
El piloto deja fuera un integrante por ronda, con objetos completos.
Toda sesión y todo golpe de un objeto deben permanecer fuera del entrenamiento
cuando ese objeto se evalúa, incluso si aparece con varios teléfonos.

Verificar programáticamente ausencia de objetos compartidos y cobertura de clases.
Agregar probabilidades por objeto y comunicar incertidumbre sin tratar folds
correlacionados como experimentos independientes.

## Decisiones que aún requieren el piloto

- Evaluación de los avisos de sensibilidad con nuevas grabaciones.
- Selección de canal si existen varios; no promediarlos automáticamente.
- Revisión del golpe de madera sin cola aislada y de los golpes sensibles al fondo.
- Criterios comunes de aceptación y exclusión.
- Viabilidad del decaimiento modal.
- Disponibilidad de nuevos objetos y aclaración de golpes por colocación.

La banda, ventana y tratamiento de fondo se fijaron para el método piloto v1.
La validación por participante prevista sigue sin ser viable con un solo integrante.
