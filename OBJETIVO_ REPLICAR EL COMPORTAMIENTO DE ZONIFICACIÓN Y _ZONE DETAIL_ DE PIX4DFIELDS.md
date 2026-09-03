# OBJETIVO: REPLICAR EL COMPORTAMIENTO DE ZONIFICACIÓN Y "ZONE DETAIL" DE PIX4DFIELDS

Necesito que analices y mejores completamente el sistema de zonificación de este proyecto.

Existe una carpeta llamada:

`referencia pix4d fields`

Esa carpeta contiene material, resultados, ejemplos, capturas, código o referencias relacionadas con el comportamiento que quiero reproducir.

NO QUIERO QUE MODIFIQUES ÚNICAMENTE UNA FUNCIÓN DE SUAVIZADO.

Quiero que revises TODO EL PIPELINE DE ZONIFICACIÓN actual y determines por qué nuestros resultados espaciales son diferentes a PIX4Dfields.

---

## REFERENCIA FUNCIONAL

Usa también como referencia conceptual el comportamiento descrito por PIX4Dfields para Targeted Operations / Zonation:

https://support.pix4d.com/hc/en-us/articles/360000899466

El sistema de PIX4Dfields trabaja conceptualmente con:

1. Raster o índice base.
2. Boundary del lote.
3. Obstáculos/máscaras.
4. Creación de una grilla.
5. Cálculo del valor representativo de cada celda:
   - Mean
   - Minimum
   - Maximum
6. Filtrado por histogram range / visible pixels.
7. Clasificación en un número determinado de zonas.
8. Métodos de distribución:
   - Equal intervals
   - Quantile
   - Manual intervals
9. Generación de las zonas iniciales.
10. Aplicación de un parámetro espacial llamado `Zone detail`.

El objetivo de `Zone detail` es que:

- Fine conserve mayor detalle espacial.
- Al mover el control hacia Coarse se simplifique progresivamente la zonificación.
- Se eliminen pequeñas islas y ruido espacial.
- Regiones cercanas de una misma clase se consoliden.
- Los límites de las zonas sean más limpios.
- No se destruya innecesariamente la estructura agronómica importante.
- El resultado siga correspondiendo a los valores originales del índice.

---

# FASE 1 — AUDITORÍA

ANTES DE CAMBIAR CÓDIGO:

Recorre el repositorio completo y localiza TODO lo relacionado con:

- zonificación
- generación de zones
- raster
- grid
- clasificación
- quantiles
- equal intervals
- histogram
- connected components
- smoothing
- simplification
- morphology
- neighborhood
- majority filters
- adjacency
- region merging
- polygons
- contour generation
- GeoJSON
- prescription maps
- `detail_level`
- `zone_detail`
- funciones similares a `_minimum_component_cells`
- funciones similares a `_adjacent_classes`

No asumas que el problema está únicamente en una función.

Reconstruye el flujo completo:

`raster → grid → valores por celda → clasificación → zones → limpieza espacial → suavizado/simplificación → polígonos → render`

Documenta internamente qué archivo y qué función participa en cada etapa.

---

# FASE 2 — ANALIZAR LA REFERENCIA PIX4D

Inspecciona COMPLETAMENTE la carpeta:

`referencia pix4d fields`

No revises solamente nombres de archivos.

Analiza:

- código
- imágenes
- resultados
- configuraciones
- ejemplos
- archivos raster/vectoriales
- parámetros
- capturas
- cualquier otra referencia disponible

Compara visual y estructuralmente nuestros resultados con PIX4Dfields.

Determina específicamente diferencias en:

- cantidad de pequeñas regiones
- fragmentación
- continuidad de zonas
- bordes
- islas
- agujeros internos
- diagonales
- conectividad
- tamaño mínimo de regiones
- agresividad del smoothing
- conservación de zonas grandes
- comportamiento cerca de boundaries
- comportamiento en transiciones entre clases

---

# FASE 3 — INVESTIGAR EL ALGORITMO ACTUAL

Quiero que determines exactamente qué está haciendo actualmente nuestro parámetro de detalle.

Por ejemplo, si existe algo como:

```python
def _minimum_component_cells(detail_level: float) -> int:
    ...
```

NO asumas que aumentar el número de celdas mínimas resolverá el problema.

Analiza si el pipeline actual únicamente:

- elimina componentes pequeños

cuando en realidad necesitamos una combinación de operaciones espaciales.

Una zonificación tipo PIX4D probablemente requiere conceptualmente trabajar con varios de estos mecanismos:

- connected-component analysis
- majority/neighborhood filtering
- region adjacency
- region merging
- minimum mapping unit
- eliminación de pequeñas islas
- llenado de pequeños huecos
- suavizado de fronteras
- simplificación basada en escala espacial

Determina cuáles tienen sentido para ESTE código.

---

# FASE 4 — IMPLEMENTAR UN `ZONE DETAIL` REAL

Necesito que `detail_level` represente una ESCALA DE SIMPLIFICACIÓN ESPACIAL, no solamente un threshold arbitrario.

El comportamiento esperado debe ser aproximadamente:

### Fine / detail ≈ 1.0

- conservar casi toda la clasificación original
- mantener pequeñas estructuras reales
- muy poca simplificación
- quantiles deben conservar aproximadamente sus coberturas originales
- no alterar innecesariamente los valores de las zonas

### Detail intermedio

- eliminar ruido aislado
- fusionar pequeñas islas
- reducir regiones fragmentadas
- mantener estructuras medianas y grandes
- mejorar continuidad espacial

### Coarse / detail ≈ 0.0

- simplificación fuerte
- regiones grandes y compactas
- pocas islas
- fronteras más simples
- pequeñas regiones absorbidas por zonas vecinas apropiadas
- conservar la tendencia espacial principal del raster

La transición entre Fine y Coarse DEBE SER PROGRESIVA.

Evita saltos bruscos.

---

# REGLA IMPORTANTE PARA FUSIONAR REGIONES

Cuando una región pequeña tenga que desaparecer, NO la asignes simplemente a una clase arbitraria.

Evalúa como mínimo:

1. longitud de frontera compartida con cada clase vecina
2. similitud del índice medio de la región con las zonas vecinas
3. conectividad resultante
4. tamaño de las regiones vecinas

Prioriza una combinación de:

`shared_boundary + spectral/index_similarity + spatial_continuity`

Ejemplo conceptual:

```text
merge_score =
    boundary_weight * normalized_shared_boundary
    +
    value_weight * index_similarity
    +
    continuity_weight * spatial_continuity
```

La clasificación final debe continuar teniendo sentido agronómico.

---

# FILTRO DE MAYORÍA / VECINDAD

Evalúa implementar un filtro espacial iterativo sobre la matriz de clases.

Para cada celda:

- analiza vecinos
- detecta ruido aislado
- cambia clase solamente cuando exista evidencia espacial suficiente
- evita modificar celdas en transiciones legítimas

Considera conectividad de 8 vecinos cuando sea apropiado.

El radio y número de iteraciones deben depender de `detail_level`.

NO aplicar blur directamente sobre los IDs de clase.

NO interpolar IDs categóricos como si fueran valores continuos.

---

# COMPONENTES CONECTADOS

Después del filtro espacial:

1. encuentra connected components por clase
2. calcula tamaño en celdas o área
3. identifica componentes demasiado pequeños
4. encuentra clases vecinas
5. selecciona la mejor clase receptora
6. fusiona el componente
7. repite hasta estabilización o hasta un máximo razonable de iteraciones

El tamaño mínimo NO debe depender solamente de un número mágico fijo.

Debe considerar:

- resolución/cell size
- dimensión total del grid
- detail level
- escala física de la zonificación

Si tenemos información de tamaño físico de celda, preferir trabajar en superficie:

`minimum_region_area_m2`

en lugar de únicamente:

`minimum_component_cells`

---

# PRESERVACIÓN ESTADÍSTICA

Muy importante:

El suavizado espacial NO debe destruir completamente la distribución estadística inicial.

Especialmente cuando se usa `Quantile` con Fine:

la documentación de PIX4Dfields indica que las zonas deberían representar aproximadamente áreas equivalentes cuando Zone detail está en Fine.

Por lo tanto:

clasificación estadística y simplificación espacial deben ser etapas SEPARADAS.

Primero:

`index → quantile/equal interval classification`

Después:

`class map → spatial simplification`

No recalcules quantiles continuamente durante el suavizado.

---

# BOUNDARIES

Respeta estrictamente:

- boundary del lote
- NoData
- máscaras
- obstáculos

Nunca permitas que el smoothing:

- atraviese NoData
- conecte regiones separadas físicamente
- cree zonas fuera del lote
- rellene obstáculos

---

# POLÍGONOS

Después de estabilizar el raster categórico:

genera los polígonos.

Evita intentar solucionar toda la fragmentación únicamente con `polygon.simplify()`.

La limpieza principal debe ocurrir ANTES, en espacio raster/grid.

La simplificación geométrica final solamente debe:

- reducir vértices innecesarios
- preservar topología
- mantener límites coherentes

---

# PERFORMANCE

La operación debe funcionar con grids grandes.

Evita:

- loops Python por píxel cuando puedan vectorizarse
- recalcular connected components innecesariamente
- recorridos completos repetidos sin condición de convergencia

Puedes utilizar NumPy/SciPy/OpenCV/rasterio/shapely según lo que ya use el proyecto.

No agregues dependencias pesadas sin necesidad.

---

# PRUEBAS QUE DEBES REALIZAR

Compara como mínimo:

### Caso 1
`detail_level = 1.0`

Esperado:
máximo detalle.

### Caso 2
`detail_level = 0.75`

Esperado:
ligera reducción de ruido.

### Caso 3
`detail_level = 0.50`

Esperado:
zonas visiblemente más compactas.

### Caso 4
`detail_level = 0.25`

Esperado:
simplificación fuerte.

### Caso 5
`detail_level = 0.0`

Esperado:
zonas muy generalizadas pero todavía representativas del patrón original.

Para cada caso calcula:

- número total de connected components
- número de componentes pequeños
- área por zona
- porcentaje de cobertura por zona
- tamaño medio de componente
- tamaño máximo
- perímetro aproximado
- cantidad de agujeros/islas si es posible

---

# VALIDACIÓN VISUAL

Genera comparaciones lado a lado entre:

1. clasificación sin smoothing
2. implementación actual
3. nueva implementación
4. referencia PIX4Dfields disponible en `referencia pix4d fields`

La nueva implementación debe acercarse VISUALMENTE al patrón espacial de PIX4Dfields:

- regiones continuas
- eliminación de pequeños puntos
- menos efecto sal y pimienta
- límites coherentes
- estructuras agronómicas grandes preservadas

NO busco copiar colores.

Busco copiar el comportamiento geométrico y espacial.

---

# MUY IMPORTANTE

NO QUIERO un arreglo superficial como:

```python
return max(2, int(round(2 + strength * 70)))
```

cambiando simplemente `70` por `100`, `200` o `500`.

Eso solamente cambia el minimum mapping unit y no necesariamente reproduce el comportamiento de PIX4Dfields.

Si el diseño actual es insuficiente, REESTRUCTURA EL PIPELINE.

Puedes modificar varias funciones o crear funciones nuevas.

Prefiero una solución correcta y mantenible a un parche pequeño.

---

# ENTREGABLE

Al terminar:

1. Implementa los cambios directamente en el proyecto.
2. Indica todos los archivos modificados.
3. Explica brevemente cuál era el problema real.
4. Explica el nuevo algoritmo de zonificación/smoothing.
5. Indica qué parámetros controla `detail_level`.
6. Muestra métricas antes/después.
7. Ejecuta tests existentes.
8. Agrega tests nuevos si hacen falta.
9. Verifica que no hayas roto:
   - Quantile
   - Equal intervals
   - Manual intervals
   - boundaries
   - NoData
   - generación de polygons
   - exportación.
10. No termines hasta haber comparado visualmente el resultado con `referencia pix4d fields`.

No te limites a sugerir código.

INSPECCIONA → COMPARA → IMPLEMENTA → EJECUTA → MIDE → AJUSTA → VALIDA.