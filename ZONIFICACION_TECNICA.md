# Zonificación técnica actual de GeoField Dashboard

Este documento describe la implementación vigente de zonificación para **NDVI, NDWI y NDRE**. El motor está inspirado en el flujo de PIX4Dfields: construye una grilla métrica, resume los píxeles visibles dentro de cada celda, clasifica esos valores y permite pasar gradualmente de una zonificación detallada a otra espacialmente simplificada.

La implementación principal está en `BE/geofield/services/raster_service.py`, especialmente en `_prepare_index_classification()` y `_regularize_zones()`. El frontend envía los parámetros desde `FE/src/services/api.ts` al endpoint `POST /ndvi_zoning` definido en `BE/geofield/api/routes.py`.

## 1. Flujo general

```text
Ortomosaico multiespectral + ROI
                |
                v
 Cálculo del índice a resolución nativa
                |
                v
 Construcción de una grilla métrica rotada
                |
                v
 Agregación de todos los píxeles por celda
        Mean / Min / Max
                |
                v
 Clasificación estadística inicial
 Quantiles / Equal intervals / Manual
                |
                v
 Zone Detail: Fine ---------> Coarse
 suavizado + mayoría + unión de regiones pequeñas
                |
                v
 Raster, tiles, GeoJSON, leyenda y estadísticas
```

La zonificación y la prescripción utilizan el mismo motor. La diferencia es que la prescripción asigna posteriormente una dosis a cada clase y genera sus formatos de exportación.

## 2. Índices y bandas

Todos los índices se calculan como una diferencia normalizada:

```text
índice = (banda_positiva - banda_negativa)
         ---------------------------------
         (banda_positiva + banda_negativa)
```

Las combinaciones utilizadas son:

| Índice | Banda positiva | Banda negativa | Fórmula |
|---|---|---|---|
| NDVI | NIR | Rojo | `(NIR - Rojo) / (NIR + Rojo)` |
| NDWI | Verde | NIR | `(Verde - NIR) / (Verde + NIR)` |
| NDRE | NIR | Red Edge | `(NIR - RedEdge) / (NIR + RedEdge)` |

La aplicación identifica los números de banda según el sensor y los metadatos del ortomosaico. Solo considera válido un píxel cuando ambas bandas son positivas, finitas, tienen máscara válida y el denominador no es cero.

## 3. Entradas y validaciones

El frontend envía al endpoint `/ndvi_zoning`:

- `orthomosaic_id`: vuelo activo.
- `index_name`: `NDVI`, `NDWI` o `NDRE`.
- `geojson`: geometría del ROI.
- `zone_count`: número de clases, de 2 a 10.
- `cell_size_m`: lado de celda, de 1 a 50 metros.
- `grid_angle_deg`: rotación de la grilla, de -90° a 90°.
- `classification_method`: `quantiles`, `equal_intervals` o `manual`.
- `cell_value_mode`: `mean`, `min` o `max`.
- `detail_level`: valor continuo de 0 a 1.
- `manual_breaks`: cortes internos cuando el método es manual.
- `analysis_min` y `analysis_max`: rango visible/activo del histograma.

Convención de `detail_level`:

- `1.0`: Fine; clasificación estadística sin regularización espacial.
- `0.0`: Coarse; máxima simplificación espacial.
- Cualquier valor intermedio produce una transición continua.

La grilla se limita a 150,000 celdas. Si el tamaño seleccionado excede ese límite, el backend solicita una celda mayor.

## 4. Construcción de la grilla

El ROI llega en WGS84 (`EPSG:4326`). Para trabajar en metros:

1. Si el raster ya tiene un CRS proyectado cuyas unidades son metros, se conserva ese CRS.
2. Si no, se selecciona automáticamente la zona UTM correspondiente al centro del raster.
3. El ROI se proyecta al CRS métrico.
4. Se rota temporalmente el ROI en sentido contrario a `grid_angle_deg` para obtener el rectángulo de cobertura.
5. Se calculan filas y columnas con el tamaño de celda solicitado.
6. Se construye una transformación Affine que incorpora origen, tamaño y rotación.

La misma transformación se conserva para el raster clasificado, la retícula y los GeoJSON. Esto evita desplazamientos entre la zonificación, el ortomosaico y Leaflet.

## 5. Píxeles visibles y NoData

Antes de calcular las celdas se crea una máscara que combina:

- La geometría del ROI.
- Las máscaras de las bandas requeridas.
- La máscara general del dataset.
- Valores numéricos válidos del índice.
- El intervalo `analysis_min <= índice <= analysis_max`, cuando está activo.

Los píxeles fuera de estas condiciones se convierten en `NaN` y no participan en la agregación, clasificación ni estadísticas.

La máscara es una barrera espacial: el suavizado no atraviesa huecos, NoData ni el límite del ROI.

## 6. Cálculo del valor de cada celda

GeoField reproyecta el índice nativo directamente sobre la grilla con GDAL/Rasterio. Así integra **todos los píxeles fuente que intersectan cada celda**, en lugar de usar una pequeña muestra interna.

Los modos disponibles son:

- `mean`: promedio ponderado espacialmente de los píxeles visibles.
- `min`: menor valor visible dentro de la celda.
- `max`: mayor valor visible dentro de la celda.

También se reproyecta la máscara con promedio para obtener la fracción válida de cada celda. El área final se calcula como:

```text
área válida estimada = fracción válida × tamaño_celda²
área usada = mínimo(área válida estimada, área geométrica dentro del ROI)
```

El área geométrica del ROI se estima con una máscara 4× más fina en cada eje. Esto permite representar razonablemente las celdas parciales del borde.

## 7. Clasificación estadística

Los cortes se calculan sobre los valores agregados de las celdas válidas, no sobre los identificadores de color.

### Quantiles

Usa `numpy.quantile()` para dividir las celdas en grupos con cantidades aproximadamente iguales. Con cuatro zonas y `detail_level = 1`, cada clase contiene aproximadamente 25 % de las celdas. El porcentaje de área puede diferir ligeramente porque las celdas del borde son parciales.

### Equal intervals

Divide uniformemente el rango activo:

```text
paso = (analysis_max - analysis_min) / zone_count
```

Cada intervalo tiene la misma amplitud numérica, aunque no necesariamente la misma cantidad de celdas.

### Manual

Utiliza exactamente los cortes ingresados. Debe haber `zone_count - 1` cortes, todos finitos, ordenados, sin duplicados y dentro del rango activo.

### Asignación inicial

Cada celda se asigna con `numpy.digitize()` al intervalo delimitado por los cortes. Esta matriz se conserva como `initial_zones`; posteriormente Zone Detail produce `final_zones`.

## 8. Relación con la ecualización del histograma

La ecualización del índice es una transformación monotónica utilizada para distribuir mejor los colores de visualización. La zonificación conserva los valores físicos originales del índice y no clasifica colores RGB.

En el método Quantiles, una transformación monotónica mantiene el orden de los valores. Por eso los límites espaciales de la clasificación Fine deben corresponder con la distribución observada en el índice ecualizado, aunque una celda representa el resumen de muchos píxeles y no un único píxel de pantalla.

El histograma devuelto por la zonificación se construye con los mismos valores de celda que alimentan la clasificación. Tiene 48 bins y reporta también los cortes de clase.

## 9. Zone Detail

Zone Detail no cambia el tamaño ni la alineación de la grilla. Modifica solamente la continuidad espacial de las clases.

La intensidad interna de simplificación se calcula como:

```text
strength = (1 - detail_level) ^ 1.10
```

Esto produce una transición no lineal: Fine conserva toda la variación inicial y la simplificación se intensifica hacia Coarse.

Cuando `detail_level >= 0.999`, el backend devuelve una copia exacta de `initial_zones`. Para los demás valores ejecuta tres etapas.

### 9.1 Regularización espectral

La superficie continua del índice se suaviza iterativamente con el kernel:

```text
1  2  1
2  4  2
1  2  1
```

En cada posición solo participan vecinos válidos; los pesos se normalizan por la suma disponible. El número de iteraciones es:

```text
spectral_iterations = ceil(strength × 10)
```

Para evitar borrar información agronómica legítima, una celda solo puede cambiar cuando:

- Su clase original concuerda con su valor crudo y los cortes actuales.
- El componente conectado original tiene al menos 9 celdas.
- No forma parte de una estructura lineal delgada estable.
- La nueva clase está como máximo a una clase de distancia de la original.

### 9.2 Filtro categórico de mayoría

Después se evalúan los ocho vecinos de cada celda. El número de iteraciones es:

```text
neighborhood_iterations = ceil(strength × 5)
```

Una celda cambia únicamente si:

- Tiene al menos tres vecinos válidos.
- La clase ganadora alcanza la fracción de soporte requerida.
- La clase ganadora supera a la actual por al menos dos votos.
- La celda no pertenece a una línea horizontal o vertical estable.

La fracción requerida disminuye gradualmente:

```text
neighbor_support_fraction = 0.90 - strength × 0.20
```

Por tanto, Fine exige mayor evidencia para modificar una celda y Coarse permite una consolidación más fuerte.

### 9.3 Unidad mínima de mapeo y componentes

Las regiones se detectan con conectividad cardinal de cuatro vecinos. Dos celdas que solo se tocan por una esquina se consideran componentes distintos.

La unidad mínima de mapeo se expresa en metros cuadrados y depende tanto de la celda como del área del lote:

```text
área_nominal = percentil 75 de las áreas válidas de celda
ancho_celda = raíz(área_nominal)
ancho_campo = raíz(área_total)
crecimiento_coarse = máximo(2 × ancho_celda, 0.11 × ancho_campo)
ancho_mapeo = ancho_celda + strength × crecimiento_coarse
```

El área objetivo se limita para no colapsar lotes pequeños y nunca puede ser inferior al área nominal de una celda.

Los componentes pequeños se procesan progresivamente con 35 %, 60 %, 80 % y 100 % del área objetivo. Cada nivel puede realizar hasta cuatro pasadas para alcanzar convergencia.

Una región pequeña no se elimina indiscriminadamente. Se puede conservar cuando:

- Representa toda una clase estadísticamente significativa.
- Es una estructura lineal creíble: al menos tres celdas, elongación mínima 3:1 y longitud suficiente respecto a la unidad mínima.
- No existe un vecino válido al cual unirla sin cruzar NoData.

### Selección del vecino receptor

Cuando una región debe absorberse, solo se consideran clases realmente adyacentes. Cada candidata recibe una puntuación:

```text
score = 0.45 × frontera_compartida
      + 0.35 × similitud_espectral
      + 0.05 × continuidad_de_región
      + 0.15 × centralidad_de_clase
```

La región se une a la candidata con mayor puntuación. También se evita absorberla dentro de otra región aún menor cuando ambas están debajo del área objetivo.

## 10. Estadísticas resultantes

El backend calcula:

- Media global del lote ponderada por área válida.
- Media de cada zona ponderada por área.
- Número inicial y final de celdas por clase.
- Área en hectáreas.
- Porcentaje de cobertura.
- Desviación porcentual respecto a la media del lote.
- Rango inferior y superior de cada clase.

La desviación se define como:

```text
desviación_% = ((media_zona - media_campo) / media_campo) × 100
```

El bloque `debug` incluye alineación espacial y métricas antes/después: componentes conectados, celdas aisladas, regiones encerradas, componentes menores al objetivo y perímetro interno aproximado.

## 11. Artefactos y visualización

Cada ejecución genera un identificador UUID nuevo y produce:

- PNG de la clasificación.
- GeoTIFF georreferenciado.
- Tiles XYZ alineados con Leaflet.
- GeoJSON de relleno por celda/zona.
- GeoJSON de retícula.

El frontend monta el relleno y la retícula como capas separadas. Los GeoJSON se solicitan con `cache: "no-store"`. Los tiles pueden utilizar caché inmutable porque cada nueva zonificación tiene una URL basada en un UUID distinto.

## 12. Similitudes con PIX4Dfields

El comportamiento replicado incluye:

- Grilla métrica con tamaño y rotación configurables.
- Cálculo Mean, Min o Max usando píxeles visibles por celda.
- Métodos Quantiles, Equal intervals y Manual.
- Fine como clasificación estadística de máxima resolución.
- Simplificación continua hacia Coarse.
- Conservación de los cortes mientras cambia Zone Detail.
- Consolidación de zonas basada en continuidad espacial y espectral.
- Estadísticas por zona y cobertura.

No es una copia del código propietario de PIX4Dfields. Los parámetros de regularización son una aproximación calibrada mediante observación visual, métricas de fragmentación y pruebas sobre los datos disponibles.

## 13. Puntos de ajuste en el código

| Comportamiento | Función |
|---|---|
| Validación de parámetros | `_normalize_*()` y `_validate_manual_breaks()` |
| Cortes estadísticos | `_classification_breaks()` |
| Construcción y agregación de grilla | `_prepare_index_classification()` |
| Curva Fine/Coarse | `_detail_strength()` |
| Unidad mínima e iteraciones | `_spatial_detail_parameters()` |
| Suavizado del índice | `_spectral_zone_filter()` |
| Mayoría categórica | `_categorical_majority_filter()` |
| Unión de regiones pequeñas | `_merge_small_components()` |
| Elección del vecino | `_select_component_target()` |
| Orquestación de Zone Detail | `_regularize_zones()` |
| Respuesta y artefactos | `ndvi_zoning_map()` |

## 14. Pruebas

Las pruebas están en `BE/tests/test_raster_service.py` y cubren, entre otros casos:

- Dirección correcta de las fórmulas espectrales.
- Agregación Mean/Min/Max.
- Inclusión de todos los píxeles nativos por celda.
- Cuantiles calculados sobre celdas visibles.
- Separación entre clasificación y regularización.
- Progresión de fragmentación Fine → Coarse.
- Islas, huecos, esquinas, espuelas y estructuras lineales.
- Barreras NoData.
- Alineación de raster, GeoJSON, grilla y prescripción.

Para ejecutarlas:

```powershell
cd BE
.\venv\Scripts\python.exe -m unittest discover -s tests
```

La validación del contrato frontend se ejecuta con:

```powershell
cd FE
corepack pnpm run typecheck
corepack pnpm run build
```
