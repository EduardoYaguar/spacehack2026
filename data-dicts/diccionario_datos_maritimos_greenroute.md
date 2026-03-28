# Diccionario de Datos — maritime_portklang_singapore.json
> GreenRoute Intelligence Platform · Corredor SGP → PKL · Versión 2.0

---

## Resumen del dataset

| Propiedad | Valor |
|---|---|
| `grid_id` | `maritime-portklang-singapore` |
| `mode` | `maritime` |
| `generated_at` | `2026-03-27T17:19:00.849771+00:00` (UTC) |
| `version` | `2.0` |
| Grilla | 40 filas × 60 columnas = 2,400 celdas totales |
| Celdas navegables | 892 (land_mask = 1) |
| Celdas tierra | 1,508 (land_mask = 0) |

---

## 1. Metadatos del dataset

| Campo | Tipo | Descripción | Valores posibles |
|---|---|---|---|
| `grid_id` | `string` | Identificador único del dataset | `"maritime-portklang-singapore"` |
| `mode` | `string` | Modo de transporte del corredor | `"maritime"` \| `"aviation"` |
| `generated_at` | `string` (ISO 8601) | Timestamp de generación del payload en UTC | ej. `2026-03-27T17:19:00.849771+00:00` |
| `version` | `string` | Versión del esquema del payload | `"2.0"` |

---

## 2. Puntos de origen y destino

### `origin` — object
| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del puerto de origen | `"Port Klang, Malaysia"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `2.99` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `101.39` |

### `destination` — object
| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del puerto de destino | `"Port of Singapore"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `1.26` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `103.84` |

---

## 3. Definición de la grilla — `grid_definition`

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `bounds.north` | `float` | Límite norte del bounding box | `4.5°N` |
| `bounds.south` | `float` | Límite sur del bounding box | `0.5°N` |
| `bounds.east` | `float` | Límite este del bounding box | `105.5°E` |
| `bounds.west` | `float` | Límite oeste del bounding box | `99.5°E` |
| `cell_size_degrees` | `float` | Resolución angular de cada celda | `0.1°` |
| `cell_size_approx_km` | `float` | Resolución espacial aproximada en km | `11.1 km` |
| `rows` | `int` | Número de filas (eje latitud, N→S) | `40` |
| `cols` | `int` | Número de columnas (eje longitud, W→E) | `60` |
| `total_cells` | `int` | Total de celdas en la grilla (40 × 60) | `2,400` |
| `navigable_cells` | `int` | Celdas con land_mask = 1 (agua) | `892` |
| `land_mask_source` | `string` | Fuente de datos de la máscara terrestre | `"SRTM + JRC Global Surface Water"` |
| `coordinate_system` | `string` | Sistema de coordenadas geográficas | `"EPSG:4326"` |
| `cell_to_coords` | `string` | Fórmula de conversión [row, col] → [lat, lon] | `lat = north − (row × cell_size) − cell_size/2` · `lon = west + (col × cell_size) + cell_size/2` |

**Ejemplo de conversión:**
- Celda `[row=0, col=0]` → `lat: 4.45°N, lon: 99.55°E` (esquina noroeste)
- Celda `[row=39, col=59]` → `lat: 0.55°N, lon: 105.45°E` (esquina sureste)

---

## 4. Máscara terrestre — `land_mask`

| Campo | Tipo | Descripción | Detalle |
|---|---|---|---|
| `description` | `string` | Descripción de los valores | `"1 = water (navigable), 0 = land"` |
| `data` | `matrix [40×60]` | Matriz binaria de navegabilidad | Floats `0.0` (tierra) o `1.0` (agua) |

**Notas de uso:**
- Solo las celdas con valor `1.0` son incluidas como nodos en el grafo NetworkX para el pathfinding A*.
- La matriz tiene 40 filas × 60 columnas. `data[row][col]` da el valor de navegabilidad de la celda en esa posición.

---

## 5. Capas satelitales — `layers`

Cada capa es un objeto con campos descriptivos y un campo `data` que contiene la matriz 40×60 de valores.

---

### 5.1 `layers.no2_mol_m2` — Dióxido de nitrógeno troposférico

**Rol en el sistema:** Indicador primario de emisiones. Mayor peso en el green_score.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Tropospheric NO2 column density — primary emissions indicator"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `gee_collection` | `string` | `COPERNICUS/S5P/OFFL/L3_NO2` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Media compuesta 7 días (2026-03-10 → 2026-03-17) |
| `spatial_aggregation` | `string` | Media de píxeles nativos ~3.5 km por celda de ~11 km |
| `quality_filter` | `string` | `cloud_fraction < 0.3` |
| `valid_cells` | `int` | `892` |
| `stats.mean` | `float` | `2.29 × 10⁻⁵ mol/m²` |
| `stats.max` | `float` | `1.96 × 10⁻⁴ mol/m²` |
| `stats.min` | `float` | `5.35 × 10⁻⁶ mol/m²` |
| `data` | `matrix [40×60]` | Valores en mol/m², `null` en celdas tierra |

**Peso en green_score:** `0.30` (marítimo) / `0.45` (aviación)

**Regla de negocio:** Si `no2_mean > 2.5×10⁻⁵ mol/m²` → el SatelliteAnalyst debe llamar `query_so2_hotspots`.

---

### 5.2 `layers.so2_mol_m2` — Dióxido de azufre

**Rol en el sistema:** Detector de uso de combustible HFO y violaciones de la Zona de Control de Emisiones (ECA).

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"SO2 column density — detects high-sulfur fuel use"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `gee_collection` | `string` | `COPERNICUS/S5P/OFFL/L3_SO2` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Media compuesta 7 días |
| `quality_filter` | `string` | `cloud_fraction < 0.3` |
| `valid_cells` | `int` | `892` |
| `stats.mean` | `float` | `2.85 × 10⁻⁵ mol/m²` |
| `stats.max` | `float` | `4.73 × 10⁻⁴ mol/m²` |
| `stats.min` | `float` | `0.0 mol/m²` |
| `data` | `matrix [40×60]` | Valores en mol/m² |

**Peso en green_score:** `0.10` (marítimo) / `0.15` (aviación)

**Advertencia de confound:** Celdas dentro de `0.2°` de Jurong Island (`1.27°N, 103.68°E`) pueden tener SO₂ de origen petroquímico industrial, no de barcos. No usar como evidencia de violación ECA.

---

### 5.3 `layers.wind_u_ms` — Componente U del viento (este-oeste)

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Eastward wind component at 10m. Positive = blowing east."` |
| `source` | `string` | `NOAA GFS 0.25°` |
| `gee_collection` | `string` | `NOAA/GFS0P25` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el este) |
| `temporal_aggregation` | `string` | Media 7 días (2026-03-10 → 2026-03-17) |
| `spatial_aggregation` | `string` | GFS nativo ~28 km remuestreado a ~11 km |
| `valid_cells` | `int` | `892` |
| `data range` | `float` | `[−4.04, 0.86] m/s` |
| `data mean` | `float` | `−1.57 m/s` |
| `data` | `matrix [40×60]` | Valores en m/s |

---

### 5.4 `layers.wind_v_ms` — Componente V del viento (norte-sur)

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Northward wind component at 10m. Positive = blowing north."` |
| `source` | `string` | `NOAA GFS 0.25°` |
| `gee_collection` | `string` | `NOAA/GFS0P25` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el norte) |
| `temporal_aggregation` | `string` | Media 7 días |
| `valid_cells` | `int` | `892` |
| `data range` | `float` | `[−5.69, 0.16] m/s` |
| `data mean` | `float` | `−3.03 m/s` |
| `data` | `matrix [40×60]` | Valores en m/s |

**Peso combinado wind_u + wind_v en green_score:** `0.20` (marítimo) / `0.30` (aviación)

**Nota:** Los valores negativos predominantes en wind_v indican viento neto hacia el sur durante el período — consistente con el inicio del monzón NE.

---

### 5.5 `layers.wave_height_m` — Altura significativa de olas

**Rol en el sistema:** Indicador de condiciones marítimas para seguridad de navegación. Solo aplica en modo marítimo.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Estimated significant wave height from Pierson-Moskowitz (Hs = 0.0246 × V²)"` |
| `source` | `string` | `Derivado de NOAA GFS wind speed` |
| `unit` | `string` | `metros` |
| `derivation` | `string` | `Pierson-Moskowitz fully developed sea: Hs = 0.0246 × V²` |
| `valid_cells` | `int` | `892` |
| `stats.mean` | `float` | `0.42 m` |
| `stats.max` | `float` | `0.88 m` |
| `data range` | `float` | `[~0.0001, 0.88] m` |
| `data` | `matrix [40×60]` | Valores en metros |

**Peso en green_score:** `0.15` (marítimo) / `N/A` (no aplica en aviación)

---

### 5.6 `layers.viirs_radiance_nw` — Radiancia nocturna VIIRS

**Rol en el sistema:** Proxy de densidad estructural de tráfico marítimo. Solo aplica en modo marítimo.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"VIIRS nighttime radiance — ship traffic proxy"` |
| `source` | `string` | `VIIRS Day/Night Band monthly composite` |
| `gee_collection` | `string` | `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG` |
| `unit` | `string` | `nW/cm²/sr` |
| `temporal_aggregation` | `string` | Compuesto mensual (febrero 2026) |
| `valid_cells` | `int` | `892` |
| `stats.mean` | `float` | `0.78 nW/cm²/sr` |
| `stats.max` | `float` | `47.14 nW/cm²/sr` |
| `data range` | `float` | `[0.0, 47.14] nW/cm²/sr` |
| `data` | `matrix [40×60]` | Valores en nW/cm²/sr |

**Peso en green_score:** `0.15` (marítimo) / `N/A` (no aplica en aviación)

**Advertencia de interpretación:** Es un promedio mensual. Un valor alto indica una lane de tráfico estructuralmente densa, no un evento puntual. **No disparar WARN solo por VIIRS alto.**

---

### 5.7 `layers.green_score` — Score verde precomputado

**Rol en el sistema:** Score 0–100 listo para usar en el dashboard React como heatmap y en el CorridorOptimizer como `cost_node = 100 - green_score`.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Pre-computed green score (0-100) combining all indicators. 100 = greenest."` |
| `source` | `string` | `Computed from all layers above` |
| `unit` | `string` | `Score 0–100` |
| `formula` | `string` | `score = 100 × (1 - weighted_cost)` donde `cost = 0.30×NO2 + 0.10×SO2 + 0.20×wind + 0.15×wave + 0.15×traffic` |
| `valid_cells` | `int` | `892` |
| `stats.mean` | `float` | `74.5` |
| `stats.max` | `float` | `82.7` |
| `stats.min` | `float` | `38.3` |
| `distribution.GREEN_gte65` | `int` | `808 celdas (90.6%)` |
| `distribution.WARN_45to64` | `int` | `79 celdas (8.9%)` |
| `distribution.RED_lt45` | `int` | `5 celdas (0.5%)` |
| `data` | `matrix [40×60]` | Valores score 0–100 |

---

## 6. Configuración del optimizador — `corridoriq_config`

### 6.1 `edge_cost_weights` — Pesos del costo de arista para A*

| Campo | Tipo | Peso | Descripción |
|---|---|---|---|
| `no2` | `float` | `0.30` | Mayor peso — señal primaria de emisiones |
| `so2` | `float` | `0.10` | Violaciones ECA / combustible HFO |
| `wind` | `float` | `0.20` | Asistencia o resistencia del viento |
| `wave` | `float` | `0.15` | Solo marítimo (N/A en aviación) |
| `traffic` | `float` | `0.15` | Densidad VIIRS, solo marítimo |
| `distance` | `float` | `0.10` | Distancia haversine normalizada |
| **Total** | | **1.00** | Los pesos suman 1.0 |

**Pesos en modo aviación:** `no2=0.45, so2=0.15, wind=0.30, distance=0.10` (wave y traffic no aplican)

### 6.2 `normalization` — Rangos de normalización por capa

| Capa | min | max | Nota |
|---|---|---|---|
| `no2_mol_m2` | `0` | `0.0002` | mol/m² |
| `so2_mol_m2` | `0` | `0.0001` | mol/m² |
| `wind_speed` | `0` | `15` | m/s — mayor = mejores opciones de asistencia |
| `wave_height_m` | `0` | `6` | metros |
| `viirs_radiance_nw` | `0` | `50` | nW/cm²/sr |

### 6.3 `badge_thresholds` — Umbrales de certificación

| Badge | Condición | Acción recomendada |
|---|---|---|
| `GREEN` | `score ≥ 65` | Mantener ruta — sin acción requerida |
| `WARN` | `45 ≤ score < 65` | Evaluar ruta alternativa |
| `RED` | `score < 45` | Rerouting obligatorio |

### 6.4 `pathfinding_note` — Nota de uso para A*

> "CorridorIQ can use green_score directly as node cost (invert: cost = 100 − green_score) or recompute from raw layers with custom weights"

---

## 7. Estructura del campo `data` en cada capa

Todas las capas en `layers.*` tienen la misma estructura de matriz:

```
data[row][col]  →  valor de la celda en fila=row, columna=col

- row: 0..39  (norte a sur, row=0 = lat 4.45°N)
- col: 0..59  (oeste a este, col=0 = lon 99.55°E)
- Celdas tierra (land_mask=0): valor null
- Celdas agua  (land_mask=1): valor float de la capa
```

**Fórmula de conversión índice → coordenadas:**
```python
lat = 4.5 - (row * 0.1) - 0.05   # centro de la celda
lon = 99.5 + (col * 0.1) + 0.05  # centro de la celda
```

---

## 8. Resumen de fuentes de datos

| Capa | Satélite / Modelo | Colección GEE | Resolución nativa | Frecuencia |
|---|---|---|---|---|
| `no2_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_NO2` | ~3.5 km | Diario |
| `so2_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_SO2` | ~3.5 km | Diario |
| `wind_u_ms` / `wind_v_ms` | NOAA GFS 0.25° | `NOAA/GFS0P25` | ~28 km | 6-horario |
| `wave_height_m` | Derivado de GFS | — | ~28 km | 6-horario |
| `viirs_radiance_nw` | VIIRS DNB | `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG` | ~500 m | Mensual |
| `green_score` | Calculado | — | ~11 km | Por ejecución |
