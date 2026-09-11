# Contexto del proyecto: Publicación de resultados hacia una base de datos central

## 1. Contexto general

Existe una aplicación actualmente funcional que procesa información y
trabaja con una base de datos propia. El sistema genera y muestra
resultados derivados de distintos procesos, incluyendo índices como
NDVI, estadísticas (promedios, medias) y resultados relacionados con
motores de prescripción.

La aplicación y su base de datos actual NO deben reemplazarse. El
requerimiento nuevo consiste en agregar un mecanismo para publicar
determinados resultados hacia una segunda base de datos, destinada a
alimentar un dashboard web.

## 2. Necesidad solicitada

Se requiere incorporar en la aplicación una acción o botón llamado
**"Publicar"**.

Cuando el usuario presione este botón, el sistema deberá:

1.  Identificar los resultados que se desean publicar.
2.  Obtenerlos desde el sistema/base de datos actual.
3.  Prepararlos en una estructura definida, probablemente JSON.
4.  Enviarlos mediante una API.
5.  La API deberá almacenar la información en una **segunda base de
    datos central**.
6.  Un dashboard web consumirá posteriormente esta información para
    visualizar los resultados.

Flujo esperado:

`Procesamiento -> BD actual -> Publicar -> API -> BD nueva/central -> Dashboard`

## 3. Interpretación del audio/requerimiento

De acuerdo con la nota de voz proporcionada, la aplicación ya calcula y
conserva información como índices, NDVI, promedios/medias y resultados
de los procesos existentes.

El nuevo requerimiento no consiste en rehacer el sistema actual, sino en
crear una vía de publicación para que los resultados seleccionados
puedan salir del entorno actual y quedar disponibles en otra base de
datos para su posterior consulta desde un dashboard.

Por lo tanto, deben mantenerse separadas dos responsabilidades:

-   **Base de datos actual:** operación, procesamiento y almacenamiento
    interno de la aplicación.
-   **Nueva base de datos:** almacenamiento de información ya publicada
    y preparada para ser consumida por el dashboard.

## 4. Propuesta inicial de tablas para la nueva BD

La estructura definitiva depende de conocer los datos exactos que
necesita el dashboard, pero inicialmente pueden considerarse:

### `projects` / `fields`

Identificación del proyecto, lote, parcela, vuelo u otra unidad de
trabajo.

### `analyses`

Información del análisis realizado: NDVI, prescripción, conteo u otro
tipo de procesamiento.

### `results`

Resultados finales y métricas que serán mostrados en el dashboard:
valores, promedios, medias, fechas, estados, etc.

### `publications`

Control de publicaciones: qué información fue publicada, cuándo se
publicó, estado de la publicación y posibles errores.

### `layers` / `files` (si aplica)

Referencias a archivos o productos geoespaciales, por ejemplo GeoJSON,
raster, ortomosaicos, capas o URLs de almacenamiento.

Relación conceptual inicial:

`Proyecto -> Análisis -> Resultado -> Publicación`

## 5. Consideraciones importantes para el agente

Antes de implementar, NO asumir que toda la BD actual debe duplicarse.

Primero se debe determinar:

-   Qué resultados exactos necesita consumir el dashboard.
-   Qué campos deben enviarse.
-   Qué identificadores relacionarán proyectos/análisis/resultados.
-   Qué información geoespacial debe almacenarse directamente y cuál
    mediante referencias/URLs.
-   El contrato JSON de la API.
-   Cómo autenticar las publicaciones.
-   Cómo evitar publicaciones duplicadas.
-   Qué ocurre si la API o la nueva BD no están disponibles.
-   Si un resultado publicado puede actualizarse posteriormente.
-   Qué estados de publicación se requieren.

## 6. Objetivo para el agente

Analizar la arquitectura existente y diseñar la solución más simple y
mantenible para incorporar esta funcionalidad sin romper el flujo
actual.

No modificar ni eliminar la base de datos existente sin una razón
explícita.

La prioridad es construir una integración desacoplada:

**Sistema existente -\> servicio de publicación/API -\> nueva BD -\>
dashboard**

Antes de escribir código o crear tablas definitivas, revisar el modelo
de datos actual y confirmar qué información necesita realmente el
dashboard.
