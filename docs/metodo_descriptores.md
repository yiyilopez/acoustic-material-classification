# Descriptores del piloto: método v1

Este método se fijó al inspeccionar el piloto de Yiyi, antes de entrenar modelos.
Es una elección operativa para estas grabaciones; no se seleccionó buscando
maximizar diferencias entre materiales. Debe mantenerse al ampliar la muestra
o revisarse explícitamente para todos los objetos. Parámetros en
`config.json`, sección `extraccion_piloto_v1`.

## Datos y coordenadas

Se usan exclusivamente los 37 eventos aceptados por escucha en
`datos/metadatos/impactos.csv`. Los cinco excluidos no participan en los cálculos.
Se trabaja con copias mono a 48000 Hz, PCM de 24 bits, verificadas frente al
registro de decodificación. No se filtra, normaliza ni remuestrea el audio.
Los WAV de ventanas conservan exactamente las muestras de sus copias fuente.
Los originales y el registro de decisiones por escucha no se modifican.

En `ventanas.csv`, inicio es inclusivo y fin es exclusivo, con índices desde
cero relativos a la grabación completa decodificada. Tiempo absoluto = índice/fs.
Los límites preliminares de la etapa anterior quedan como antecedente;
el cálculo utiliza los nuevos límites de `datos/caracteristicas/piloto_v1/ventanas.csv`.

## Fondo, frente y final

Para cada evento se toma como fondo el intervalo de 350 a 50 ms antes del
máximo RMS localizado durante la segmentación. Se estima su media y su potencia
media después de quitar esa media. Es una referencia local, no una medición
independiente del ruido del teléfono. Una variación del entorno puede invalidar
el supuesto de fondo constante.

Se examina la potencia por bloques de 1 ms. El frente se coloca inmediatamente
después de la última racha de cinco bloques cuya potencia no supera nueve veces
la del fondo, buscando hasta 120 ms hacia atrás desde el máximo. Se conservan
2 ms adicionales antes del frente. La resolución del frente es aproximadamente
1 ms; no se interpreta como un instante físico exacto de contacto.

Desde 15 ms después del máximo, se busca una racha de 30 ms cuya potencia,
suavizada con un promedio de 5 ms, no supere dos veces la del fondo. La ventana
incluye esa racha. El límite de seguridad es 750 ms desde el inicio o el inicio
del siguiente candidato, incluso si fue excluido. No se atraviesa otro evento.
Si no se consigue el retorno al fondo, D90 queda ausente; el valor producido
por la ventana limitada se guarda únicamente como diagnóstico provisional.

## Espectro y sus tres descriptores

Todos usan los primeros 100 ms desde el inicio ajustado (4800 muestras).
Se resta la media de esa ventana y se aplica una rampa sin² de 1 ms al inicio
y una rampa cos² de 10 ms al final; el resto tiene peso uno. Esta elección
conserva buena parte del ataque y reduce discontinuidades en los bordes.
Los espectros describen los primeros 100 ms del evento, no todo su decaimiento.
Se registra por separado la ventana espectral, aunque exceda el final temporal.

Se calcula el periodograma unilateral:

`P[k] = |FFT((x-media(x))*w)[k]|² / (fs * suma(w²))`.

Se duplican las potencias de las frecuencias positivas salvo Nyquist; no se
rellena con ceros. La separación entre frecuencias de la FFT es 10 Hz, que no
equivale a garantizar una resolución física de 10 Hz en señales amortiguadas.
Se conserva la banda común 100–20000 Hz, incluidos sus extremos.
El límite inferior reduce la contribución de variaciones lentas; el superior
queda por debajo de Nyquist (24000 Hz). Esto no demuestra una respuesta plana
del teléfono en esa banda ni permite medir presión sonora calibrada.

Con `f[k]` y potencia `P[k]` dentro de esa banda:

- **Frecuencia prominente fₚ:** frecuencia del máximo de P, en Hz; sin interpolación.
- **Centroide C:** `suma(f*P)/suma(P)`, en Hz.
- **Ancho B:** `raíz(suma((f-C)²*P)/suma(P))`, en Hz.
- **Ancho relativo B/C:** cociente adimensional; es el tercer predictor espectral.

Los momentos se ponderan por potencia, no por amplitud. fₚ es un máximo
espectral de la señal medida, no una frecuencia modal identificada.
El espectro principal conserva el fondo. Como diagnóstico se calcula también
una versión con resta del promedio de tres espectros de fondo de 100 ms,
con el mismo taper, y potencias negativas recortadas a cero. Esta versión
no sustituye al predictor principal y también puede introducir sesgo.

La convención de escalado corresponde a la definición de densidad espectral
unilateral descrita en la [documentación oficial de periodogram de SciPy](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.periodogram.html).
La implementación utiliza NumPy; no requiere instalar SciPy para esta etapa.
Los momentos y la ventana asimétrica son definiciones explícitas de este proyecto.

## D90

Se usa la señal temporal completa, sin filtrado a la banda espectral ni taper.
Se quita la media del fondo
y, para cada bloque de 1 ms, se calcula:

`E[j] = máximo(suma(x² en bloque j) - N[j]*potencia_fondo, 0)`.

Se acumulan esas energías y se localizan t05 y t95, donde se alcanza el 5 %
y el 95 % de la energía corregida. Se interpola suponiendo energía uniforme
dentro de cada bloque; la resolución efectiva sigue siendo aproximadamente
1 ms. `D90 = t95-t05`, en segundos. t05 y t95 se expresan respecto al inicio
ajustado, no respecto al inicio del archivo. No son τ ni un tiempo modal.

La sustracción se realiza antes de rectificar la energía de cada bloque.
La rectificación evita incrementos negativos, pero deja un sesgo positivo de
ruido residual: no garantiza eliminar el fondo. Por eso se conserva también
D90 sin sustracción y se comprueba la sensibilidad a medio fondo, 1.5 veces el
fondo y un final 50 ms más tarde cuando hay espacio antes del límite.

## Avisos y resúmenes

Se señalan ventanas cuya potencia media observada/fondo es inferior a 10 dB,
sin confundir ese cociente con una SNR de fuente aislada. También se señalan
cambios relativos de D90 mayores que 20 % al variar fondo/final, y cambios
de centroide o frecuencia prominente mayores que 20 % con ventanas de 80 y 120 ms. Esos umbrales son
avisos operativos, no pruebas de hipótesis ni intervalos de confianza.
Las alternativas y los valores sin redondear quedan en `calculo.json`.

Por objeto se informan mediana y percentiles 25 y 75 de los golpes aceptados,
con el número disponible para cada descriptor. Se incluyen valores con avisos
para conservar trazabilidad, pero los D90 no estimables no entran en el resumen.
Las medianas no representan categorías completas: hay solo dos objetos por
material y un participante. Los golpes de un objeto son repeticiones.
No se entrenan modelos ni se evalúan hipótesis en esta etapa.

## Reproducción y verificaciones

`PYTHONPATH=src .venv/bin/python -m acustica_materiales descriptores-piloto`

El comando se niega a sobrescribir sus salidas. Conserva hashes, coordenadas,
parámetros, espectros alternativos y copias de ventanas sin alterar amplitud.
Las pruebas sintéticas verifican los momentos de un espectro conocido, un
tono de 1000 Hz, el escalado de potencia, D90 de energía constante (0.9 T),
D90 de una envolvente exponencial, invariancia a ganancia y manejo de silencio.
Esas pruebas verifican cálculos, no la generalización del experimento.
