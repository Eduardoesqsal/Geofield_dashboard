# Procesamiento de ortomosaicos grandes

La API, el frontend y las reglas de clasificacion permanecen en los servicios
existentes. `RasterService` delega las lecturas por bloques y la cache de calculos
a `geofield/services/raster_processing.py`, sin nuevas dependencias.

- Los indices se calculan a resolucion nativa en bloques de hasta 1024 x 1024.
- La zonificacion conserva la agregacion GDAL original (mean/min/max). Si el ROI
  supera 4 millones de pixeles, las matrices intermedias se escriben en un TIFF
  temporal; no se reducen las bandas ni se muestrean los valores del analisis.
- La grilla y sus estadisticas se guardan en `cache/classification`. Cambiar
  clases, cortes o detalle reutiliza la grilla cuando los parametros de lectura
  y agregacion siguen siendo iguales. Cambiar ROI, bandas, filtro, grilla o la
  identidad del archivo (ruta, tamano, fecha de modificacion) cambia la clave.
- Los rangos nativos de indices se calculan por bloques y se guardan en
  `cache/index-ranges`.
- Los tiles RGB de recortes reutilizan el tile RGB original y se guardan por
  geometria, para reutilizarlos incluso al seleccionar otra vez el mismo ROI.
- La exportacion del recorte de datos escribe bloques a un TIFF temporal,
  conservando valores, mascara, CRS, transformacion y metadatos de bandas.

## Recursos y limites

La mascara del poligono se rasteriza completa para conservar exactamente las
decisiones originales de GDAL en los bordes (`all_touched`). Esta mascara aun
ocupa aproximadamente un byte por pixel, con memoria adicional transitoria al
crearla. El procesamiento no tiene un limite de RAM independiente del ROI.

El TIFF temporal de zonificacion necesita aproximadamente ocho bytes por pixel
del rectangulo del ROI. Se elimina al terminar o al producirse una excepcion.
La cache persistente contiene las grillas pequenas, no ese TIFF intermedio.
Debe haber espacio libre suficiente en el disco de `cache`.

La subida inicial, la exportacion visual RGBA y las respuestas de descarga en
bytes mantienen su implementacion o contrato actual. La descarga de datos aun
carga el TIFF comprimido final en memoria para devolverlo. La primera lectura
de un archivo grande sigue dependiendo del disco y del area seleccionada.

## Validacion

Ejecutar desde `BE`:

```powershell
venv/Scripts/python.exe -m unittest discover -s tests
```

Las pruebas comparan la agregacion nueva contra las matrices completas del
algoritmo anterior, incluyendo filtros, NoData, bordes, grillas rotadas,
mean/min/max, ventanas fraccionarias, invalidacion de cache y exportacion.

Medicion local sobre una seccion de 2304 x 2304 pixeles del ortomosaico del
2026-09-07: preparacion de grilla 1.660 s; repeticion con cache 0.077 s, con
valores identicos. Es una medicion de la grilla sobre una seccion, no del flujo
completo ni una comparacion de velocidad contra la version anterior.
