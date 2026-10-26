# Diccionario de metadatos

Los archivos usan CSV con coma como separador y UTF-8. Se admite BOM de Excel.
Conserva los encabezados y escribe decimales con punto. En las medidas opcionales,
una celda vacía significa desconocido; no escribas cero para reemplazarla.

## Objetos

Archivo: datos/metadatos/objetos.csv. Una fila representa un objeto físico.

| Campo | Contenido |
| --- | --- |
| objeto_id | Identificador único obligatorio, por ejemplo OBJ001. |
| material | madera, vidrio, hierro o plastico_rigido. |
| descripcion | Descripción breve del objeto y composición conocida o declarada. |
| largo_mm, ancho_mm, alto_mm | Dimensiones en milímetros, si pueden medirse. |
| espesor_mm | Espesor en milímetros, si tiene sentido para la geometría. |
| observaciones | Forma, orientación de fibra, humedad conocida u otras particularidades. |

plastico_rigido es el identificador informático de la categoría “plástico rígido”.
El programa usa “hierro” como etiqueta acordada, sin certificar composición.
Los objetos no reciben un nuevo ID cuando cambian de colocación o teléfono.

En el registro de Yiyi, las medidas originales están en centímetros y se
conservan en `datos/metadatos/registro_aportado.json`, junto con el material
específico declarado y la correspondencia confirmada con cada archivo.
Largo y ancho se convierten a milímetros en objetos.csv (1 cm = 10 mm).
La columna original «Grosor/alto (cm)» se conserva en observaciones con su
unidad; alto_mm y espesor_mm quedan vacíos porque no se indicó cuál de las
dos dimensiones representa. El primer objeto de cada material corresponde
al archivo 01 y el segundo al 02.

## Sesiones

Archivo: datos/metadatos/sesiones.csv. Una sesión es una grabación continua
de un objeto en una colocación y configuración de adquisición.

| Campo | Contenido |
| --- | --- |
| sesion_id | Identificador único obligatorio. |
| objeto_id | Objeto registrado en objetos.csv; obligatorio. |
| participante_id | Código del integrante, por ejemplo P01; obligatorio. |
| archivo | Ruta relativa a datos/originales/, por ejemplo P01/SES001.wav; obligatoria. |
| fecha_hora | Fecha y hora ISO 8601 cuando se conozca, incluyendo zona horaria. |
| telefono | Modelo del dispositivo. |
| app_grabacion | Aplicación y ajustes de audio conocidos. |
| colocacion_id | Identificador de colocación del objeto; obligatorio. |
| recinto_id, ciudad | Contexto de grabación, sin direcciones privadas. |
| apoyo | Mesa, soporte y forma de contacto. |
| percutor | Descripción del percutor utilizado. |
| distancia_cm | Distancia medida o nominal en centímetros, cuando se conozca. |
| orientacion_microfono | Posición del micrófono respecto al golpe. |
| observaciones | Cambios de ganancia, procesamiento conocido e incidencias. |

Se obtiene frecuencia de muestreo y formato real directamente del archivo,
sin depender de una transcripción manual. Un archivo solo puede asociarse a
una sesión. Si contiene distintos objetos, habrá que preparar un registro
específico antes de continuar; no se asumirá que todos sus golpes pertenecen a uno.

## Impactos

Archivo: datos/metadatos/impactos.csv. Se completa al segmentar.

| Campo | Contenido |
| --- | --- |
| impacto_id | Identificador único del evento. |
| sesion_id | Sesión existente a la que pertenece. |
| inicio_muestra | Índice entero inicial, empezando en cero, del archivo original decodificado. |
| fin_muestra | Índice final excluido: el segmento incluye inicio, pero no fin. |
| aceptado | pendiente, si o no. |
| motivo_exclusion | Obligatorio si aceptado es no. |
| observaciones | Revisión manual, golpe doble, ruido y otras incidencias. |

El intervalo debe cumplir 0 <= inicio < fin <= muestras del archivo.
Los índices corresponden a frames: una posición temporal por canal,
no a muestras intercaladas de todos los canales. El tiempo es índice / fs.
Un evento pendiente puede no tener límites todavía.

## Relación entre registros

Un objeto tiene una o varias sesiones. Una sesión contiene uno o varios impactos.
Los descriptores futuros llevarán los identificadores necesarios para volver
al archivo y construir particiones por objeto. Una medición adicional del mismo
objeto nunca se considera una muestra independiente nueva de material.

La validación comprueba claves y relaciones; no demuestra que los objetos sean
físicamente distintos ni que los metadatos declarados sean correctos.
