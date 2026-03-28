# Diccionario de Datos — aviation_shanghai_dubai_amsterdam.json
> GreenRoute Intelligence Platform · Corredor PVG → DXB → AMS · Versión 2.0

---

## Resumen del dataset

| Propiedad | Valor |
|---|---|
| `grid_id` | `aviation-shanghai-dubai-amsterdam` |
| `mode` | `aviation` |
| `generated_at` | `2026-03-27T20:02:24.972915+00:00` (UTC) |
| `version` | `2.0` |
| `window.label` | `P1` |
| `window.start` | `2026-03-04` |
| `window.end` | `2026-03-18` |
| `window.days` | `14` días |
| Grilla | 60 filas × 125 columnas = 7,500 celdas totales |
| Celdas válidas (no null) | 7,173 |
| Land mask | **No aplica** — las aeronaves vuelan sobre todo el dominio |

---

## 1. Metadatos del dataset

| Campo | Tipo | Descripción | Valores posibles |
|---|---|---|---|
| `grid_id` | `string` | Identificador único del dataset | `"aviation-shanghai-dubai-amsterdam"` |
| `mode` | `string` | Modo de transporte del corredor | `"aviation"` \| `"maritime"` |
| `generated_at` | `string` (ISO 8601) | Timestamp de generación del payload en UTC | ej. `2026-03-27T20:02:24.972915+00:00` |
| `version` | `string` | Versión del esquema del payload | `"2.0"` |
| `window.label` | `string` | Etiqueta de la ventana temporal del compuesto | `"P1"` (período 1) |
| `window.start` | `string` (ISO 8601 date) | Inicio de la ventana de agregación | `"2026-03-04"` |
| `window.end` | `string` (ISO 8601 date) | Fin de la ventana de agregación | `"2026-03-18"` |
| `window.days` | `int` | Duración de la ventana en días | `14` |

> **Nota:** A diferencia del modo marítimo (7 días), el corredor de aviación usa una ventana compuesta de **14 días** para mejorar la cobertura en latitudes altas donde la nubosidad y la disponibilidad de datos Sentinel-5P es más variable.

---

## 2. Puntos de origen, waypoint y destino

### `origin` — object

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del aeropuerto de origen | `"Shanghai Pudong (PVG)"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `31.14` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `121.81` |

### `waypoint` — object

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del aeropuerto de escala | `"Dubai Intl (DXB)"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `25.25` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `55.36` |

> **Diferencia clave con el modo marítimo:** El modo de aviación incorpora un `waypoint` intermedio obligatorio (DXB) además del origen y destino. El A* debe generar un path que pase por las proximidades de este nodo. El modo marítimo solo tiene `origin` y `destination`.

### `destination` — object

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del aeropuerto de destino | `"Amsterdam Schiphol (AMS)"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `52.31` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `4.76` |

---

## 3. Definición de la grilla — `grid_definition`

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `bounds.north` | `float` | Límite norte del bounding box | `75.0°N` |
| `bounds.south` | `float` | Límite sur del bounding box | `15.0°N` |
| `bounds.east` | `float` | Límite este del bounding box | `125.0°E` |
| `bounds.west` | `float` | Límite oeste del bounding box | `0.0°E` |
| `cell_size_degrees` | `float` | Resolución angular de cada celda | `1.0°` |
| `cell_size_approx_km` | `float` | Resolución espacial aproximada en km | `111.0 km` |
| `rows` | `int` | Número de filas (eje latitud, N→S) | `60` |
| `cols` | `int` | Número de columnas (eje longitud, W→E) | `125` |
| `total_cells` | `int` | Total de celdas en la grilla (60 × 125) | `7,500` |
| `land_mask` | `string` | Política de máscara terrestre | `"none — aircraft fly over everything"` |
| `coordinate_system` | `string` | Sistema de coordenadas geográficas | `"EPSG:4326"` |
| `cell_to_coords` | `string` | Fórmula de conversión [row, col] → [lat, lon] | `lat = north − (row × cell_size) − (cell_size/2)` · `lon = west + (col × cell_size) + (cell_size/2)` |

**Ejemplo de conversión:**
- Celda `[row=0, col=0]` → `lat: 74.5°N, lon: 0.5°E` (esquina noroeste)
- Celda `[row=59, col=124]` → `lat: 15.5°N, lon: 124.5°E` (esquina sureste)

**Diferencias clave respecto al modo marítimo:**

| Parámetro | Modo marítimo (SGP→PKL) | Modo aviación (PVG→DXB→AMS) |
|---|---|---|
| Resolución de celda | `0.1°` (~11.1 km) | `1.0°` (~111 km) |
| Dimensiones | 40 × 60 = 2,400 celdas | 60 × 125 = 7,500 celdas |
| Land mask | Binaria (agua / tierra) | No aplica |
| Ventana temporal | 7 días | 14 días |
| Waypoints obligatorios | 2 (Raffles Lighthouse, One Fathom Bank) | 1 (DXB) |

> La resolución de `1.0°` (~111 km) es consistente con la resolución nativa de los modelos de viento en niveles de presión (ERA5/GFS) y con la escala operacional de las rutas de largo radio.

---

## 4. Land Mask — No aplica en aviación

| Campo | Valor |
|---|---|
| `land_mask` | `"none — aircraft fly over everything"` |

A diferencia del modo marítimo, **no existe una máscara binaria de navegabilidad**. Todas las celdas de la grilla son potencialmente transitables por aeronaves, incluyendo las que se encuentran sobre masa continental (desiertos, montañas, zonas de conflicto aéreo). Las restricciones de espacio aéreo, si aplican, se modelan como costos elevados en celdas específicas, no como exclusiones.

**Implicación para el CorridorOptimizer:** El `build_graph` incluye los 7,500 nodos sin filtrar por land_mask. El pathfinding A* pondera todas las celdas, y las celdas con `null` en alguna capa satelital reciben valores de fallback o se excluyen por calidad de datos.

---

## 5. Capas satelitales — `layers`

El corredor de aviación tiene **8 capas** frente a las 7 del modo marítimo. Se eliminan `wave_height_m` y `viirs_radiance_nw` (irrelevantes en aviación) y se añaden 5 capas nuevas: `co_mol_m2`, `turbulence_index`, `contrail_risk`, `cloud_top_height_m` y `aerosol_index`. La capa `aod` (Aerosol Optical Depth) aparece como capa derivada adicional.

---

### 5.1 `layers.no2_mol_m2` — Dióxido de nitrógeno troposférico

**Rol en el sistema:** En aviación, el NO2 troposférico funciona como **proxy de tráfico aéreo** y como indicador de emisiones en corredores de alta densidad. Peso menor que en modo marítimo porque el jet stream y la turbulencia tienen mayor relevancia operacional.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Tropospheric NO₂ — aviation traffic proxy and emissions indicator"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `gee_collection` | `string` | `COPERNICUS/S5P/OFFL/L3_NO2` |
| `band` | `string` | `tropospheric_NO2_column_number_density` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Compuesto diario → media 14 días (2026-03-04 → 2026-03-18) |
| `valid_cells` | `int` | `7,173` de 7,500 totales |
| `stats.mean` | `float` | `1.687 × 10⁻⁵ mol/m²` |
| `stats.max` | `float` | `4.125 × 10⁻⁴ mol/m²` |
| `data` | `matrix [60×125]` | Valores en mol/m²; `null` en celdas sin datos Sentinel-5P válidos |

**Peso en green_score:** `0.10` (aviación)

> **Regla de negocio:** Si `no2_mean > 2.5×10⁻⁵ mol/m²` en la celda de origen PVG o en el segmento Este de Asia → el SatelliteAnalyst debe registrar el hotspot y correlacionar con la capa `co_mol_m2` para distinguir entre tráfico aéreo y contaminación industrial terrestre.

> **Confound relevante:** Las celdas sobre Europa Occidental (cols ~0–30, rows ~0–15) presentan NO2 elevado de origen terrestre (tráfico urbano, industria). Este NO2 **no es atribuible a aeronaves** en tránsito a FL350+. El CertificationJudge debe considerar la altitud de vuelo al evaluar la exposición real.

---

### 5.2 `layers.co_mol_m2` — Monóxido de carbono troposférico

**Rol en el sistema:** Indicador complementario de combustión incompleta. En aviación, valores elevados de CO sobre rutas establecidas pueden indicar condiciones de combustión anómala o contaminación de fondo en corredores de alta densidad.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"CO total column — combustion tracer"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `gee_collection` | `string` | `COPERNICUS/S5P/OFFL/L3_CO` |
| `band` | `string` | `CO_column_number_density` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Compuesto diario → media 14 días |
| `valid_cells` | `int` | `7,173` |
| `stats.mean` | `float` | Ver payload — variable por región |
| `data` | `matrix [60×125]` | Valores en mol/m²; `null` en celdas sin cobertura |

**Peso en green_score:** `0.05` (aviación)

> **Regla de negocio:** CO elevado sobre la región del Golfo Pérsico (área de waypoint DXB) puede reflejar actividad petroquímica terrestre. El CertificationJudge debe verificar que las celdas afectadas no sean sobre el Golfo mismo antes de penalizar la ruta.

> **Capa sin equivalente en modo marítimo.** No existe en el payload SGP→PKL.

---

### 5.3 `layers.wind_u_ms` — Componente U del viento a 250 hPa (este-oeste)

**Rol en el sistema:** Componente horizontal este-oeste del jet stream en el nivel de vuelo estándar de largo radio (~FL340-FL390, ~250 hPa). Positivo = sopla hacia el este (viento de cola en trayectos hacia AMS).

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Zonal wind at 250 hPa — jet stream U component"` |
| `source` | `string` | `NOAA GFS 0.25°` o `ERA5 reanalysis` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el este) |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `7,500` (sin nulls — modelo global) |
| `data` | `matrix [60×125]` | Valores en m/s |

**Peso combinado wind_u + wind_v en green_score:** `0.35` (aviación) — mayor peso que en modo marítimo (`0.20`) por el impacto del jet stream en consumo de combustible y tiempo de vuelo.

> **Diferencia crítica con modo marítimo:** El modo marítimo usa viento a **10 m** (superficie). El modo aviación usa viento a **250 hPa** (~10,600 m), que corresponde al nivel de crucero de largo radio. Valores típicos del jet stream: 20–60 m/s (72–216 km/h). Viento de cola reduce consumo de combustible hasta un 15%.

---

### 5.4 `layers.wind_v_ms` — Componente V del viento a 250 hPa (norte-sur)

**Rol en el sistema:** Componente horizontal norte-sur del jet stream en nivel de crucero. Valores negativos predominantes indican flujo hacia el sur, consistente con la posición del jet stream polar en marzo.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Meridional wind at 250 hPa — jet stream V component"` |
| `source` | `string` | `NOAA GFS 0.25°` o `ERA5 reanalysis` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el norte) |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `7,500` |
| `data` | `matrix [60×125]` | Valores en m/s |

> **Nota estacional:** En marzo, el jet stream polar se sitúa típicamente entre 40°N–60°N. Las rutas PVG→AMS aprovechan el flujo zonal del jet stream en el segmento Europa Central. El CorridorOptimizer debe priorizar celdas con viento zonal alto (wind_u positivo) en latitudes medias.

---

### 5.5 `layers.turbulence_index` — Índice de turbulencia en nivel de crucero

**Rol en el sistema:** Indicador de Clear Air Turbulence (CAT) y turbulencia convectiva en el nivel de vuelo. Un índice alto implica mayor consumo de combustible por desvíos verticales, incomodidad para pasajeros y riesgo operacional.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Turbulence index at cruise level — CAT and convective turbulence"` |
| `source` | `string` | Derivado de GFS/ERA5 (wind shear + vorticity) |
| `unit` | `string` | `Índice adimensional 0–30` |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `7,500` |
| `stats` | `float` | Ver payload por región |
| `data` | `matrix [60×125]` | Valores adimensionales 0–30 |

**Peso en green_score:** `0.15` (aviación)

> **Regla de negocio:** Índices > 15 sobre el Himalaya/Hindu Kush (rows ~20–30, cols ~80–100 aprox.) son esperables en esta temporada. El CorridorOptimizer puede rodear estas zonas aunque implique mayor distancia. El CertificationJudge debe verificar si el índice alto es estructural (orografía) o episódico.

> **Capa sin equivalente en modo marítimo.**

---

### 5.6 `layers.contrail_risk` — Riesgo de formación de estelas de condensación

**Rol en el sistema:** Las estelas de condensación (contrails) tienen un efecto de forzamiento radiativo que amplifica el impacto climático de los vuelos. Minimizar el riesgo de contrails persistentes es un objetivo de la certificación verde de aviación.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Contrail formation risk based on temperature and humidity at FL"` |
| `source` | `string` | Derivado de ERA5 (temperatura + humedad relativa a 250 hPa) |
| `unit` | `string` | `Probabilidad 0.0 – 1.0` |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `7,500` |
| `data` | `matrix [60×125]` | Valores probabilísticos 0.0–1.0 |

**Peso en green_score:** `0.10` (aviación)

> **Regla de negocio:** Celdas con `contrail_risk > 0.75` en regiones de alta persistencia (latitudes medias, 40°N–60°N en invierno/primavera) deben marcarse como de alto impacto climático. El CorridorOptimizer puede sugerir descenso de nivel de vuelo en estos segmentos como mitigación, aunque esto se registra como nota y no como restricción hard.

> **Capa sin equivalente en modo marítimo.**

---

### 5.7 `layers.cloud_top_height_m` — Altura de la cima de nubes

**Rol en el sistema:** Indicator de presencia de cumulonimbus y convección profunda en la ruta. Alturas de cima superiores a 12,000 m indican sistemas convectivos que pueden obligar a desvíos laterales o verticales significativos.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Cloud top height — convection and cumulonimbus indicator"` |
| `source` | `string` | Derivado de GFS (cloud top pressure convertida a altura) |
| `unit` | `string` | `metros` |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `7,500` |
| `normalization.max` | `float` | `15,000 m` |
| `data` | `matrix [60×125]` | Valores en metros; 0 = cielo despejado en ese nivel |

**Peso en green_score:** `0.10` (aviación)

> **Regla de negocio:** Celdas sobre el Mar Arábigo y el norte de la India (rows ~30–40, cols ~50–80 aprox.) pueden mostrar cloud_top_height elevado en el período de transición de monzón. En marzo esto es moderado; la temporada crítica es junio–septiembre.

> **Capa sin equivalente en modo marítimo.**

---

### 5.8 `layers.aerosol_index` — Índice de aerosoles UV

**Rol en el sistema:** Detecta presencia de aerosoles absorbentes (polvo del desierto, humo de incendios) en la columna atmosférica. Sobre Oriente Medio y el norte de África, el polvo sahariano y árabe puede afectar la calidad del aire en las proximidades de los aeropuertos y degradar la visibilidad en aproximación.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"UV Aerosol Index — dust, smoke and absorbing aerosol detection"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `gee_collection` | `string` | `COPERNICUS/S5P/OFFL/L3_AER_AI` |
| `band` | `string` | `absorbing_aerosol_index` |
| `unit` | `string` | `Índice adimensional (−1 a +5)` |
| `temporal_aggregation` | `string` | Compuesto 14 días |
| `valid_cells` | `int` | `7,173` |
| `normalization.min` | `float` | `−1` |
| `normalization.max` | `float` | `5` |
| `data` | `matrix [60×125]` | Valores adimensionales; negativos = aerosoles no absorbentes o superficie clara |

**Peso en green_score:** `0.10` (aviación)

> **Regla de negocio:** Valores > 2.0 sobre el Golfo Pérsico y la Península Arábiga (celdas del waypoint DXB) son frecuentes en marzo por tormentas de polvo (shamal). El SatelliteAnalyst debe reportar el aerosol_index máximo en un radio de 3 celdas (~300 km) alrededor de DXB.

> **Capa sin equivalente en modo marítimo.**

---

### 5.9 `layers.aod` — Profundidad Óptica de Aerosoles (AOD)

**Rol en el sistema:** Complementa al `aerosol_index` con una medida cuantitativa de la extinción de luz por aerosoles en toda la columna. AOD alto implica alta carga de partículas (polvo, sulfatos, carbono negro) que reduce la visibilidad y puede afectar los sistemas ópticos de las aeronaves.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Aerosol Optical Depth at 550 nm — total aerosol loading"` |
| `source` | `string` | `MODIS Terra/Aqua` o `Sentinel-5P TROPOMI` |
| `unit` | `string` | `Adimensional 0.0 – 1.0+` |
| `temporal_aggregation` | `string` | Compuesto 14 días |
| `valid_cells` | `int` | `7,173` |
| `normalization.min` | `float` | `0` |
| `normalization.max` | `float` | `1` |
| `data` | `matrix [60×125]` | Valores AOD adimensionales; valores > 1.0 posibles en eventos extremos de polvo |

**Peso en green_score:** `0.05` (aviación)

> **Nota de interpretación:** AOD y `aerosol_index` son complementarios. El índice UV detecta aerosoles **absorbentes** (polvo, humo); el AOD mide la **carga total** de aerosoles incluyendo los no absorbentes (sulfatos marinos, sal). Para la ruta DXB, ambas capas deben evaluarse juntas.

> **Capa sin equivalente en modo marítimo.**

---

### 5.10 `layers.green_score` — Score verde precomputado (aviación)

**Rol en el sistema:** Score 0–100 calibrado para el modo aviación, listo para usarse en el dashboard como heatmap de ruta y en el CorridorOptimizer como `cost_node = 100 - green_score`.

| Campo | Tipo | Valor |
|---|---|---|
| `description` | `string` | `"Pre-computed green score (0-100) combining all aviation indicators. 100 = greenest."` |
| `source` | `string` | `Computed from all aviation layers` |
| `unit` | `string` | `Score 0–100` |
| `formula` | `string` | `score = 100 × (1 - weighted_cost)` donde `cost = 0.35×wind + 0.15×turbulence + 0.10×contrail + 0.10×no2 + 0.05×co + 0.10×cloud_top + 0.10×aerosol + 0.05×aod` |
| `valid_cells` | `int` | `7,173` |
| `stats.mean` | `float` | ~`46.0` (estimado del payload — ruta transcontinental con jet stream invernal) |
| `stats.max` | `float` | ~`65.2` |
| `stats.min` | `float` | ~`35.1` |
| `distribution.GREEN_gte65` | `int` | Minoritario — condiciones exigentes en invierno boreal |
| `distribution.WARN_45to64` | `int` | Mayoría de celdas en rango WARN por jet stream y turbulencia |
| `distribution.RED_lt45` | `int` | Celdas sobre zonas convectivas activas y polvo árabe |
| `data` | `matrix [60×125]` | Valores score 0–100 |

> **Diferencia crítica con modo marítimo:** El green_score medio del corredor aéreo (~46) es estructuralmente más bajo que el marítimo (~74.5) porque los pesos del jet stream y turbulencia penalizan más fuertemente. Un score WARN en aviación no implica emergencia — es la condición esperada en rutas de largo radio en invierno boreal. El CertificationJudge debe contextualizar el score con la estacionalidad.

---

## 6. Configuración del optimizador — `corridoriq_config`

### 6.1 Descripción general

| Campo | Valor |
|---|---|
| `description` | `"Aviation-specific A* pathfinding parameters"` |

### 6.2 `edge_cost_weights` — Pesos del costo de arista para A* (aviación)

| Campo | Peso | Descripción |
|---|---|---|
| `wind` | `0.35` | Mayor peso — jet stream a 250 hPa, impacto directo en consumo y tiempo |
| `turbulence` | `0.15` | CAT y turbulencia convectiva en nivel de crucero |
| `contrail` | `0.10` | Riesgo de estelas persistentes — forzamiento radiativo |
| `no2` | `0.10` | Proxy de tráfico aéreo y emisiones en corredor |
| `cloud_top` | `0.10` | Convección profunda — obliga a desvíos significativos |
| `aerosol` | `0.10` | Polvo y humo — visibilidad y calidad de aire en aeropuertos |
| `co` | `0.05` | Trazador de combustión — indicador secundario |
| `aod` | `0.05` | Carga total de aerosoles — complementa aerosol_index |
| **Total** | **1.00** | Los pesos suman 1.0 |

**Comparativa de pesos marítimo vs aviación:**

| Capa | Modo marítimo | Modo aviación | Razón del cambio |
|---|---|---|---|
| `wind` | `0.20` | `0.35` | Jet stream tiene impacto mucho mayor en FL350+ |
| `no2` | `0.30` | `0.10` | En aviación es proxy secundario, no la señal primaria |
| `wave` | `0.15` | — | No aplica en aviación |
| `traffic (viirs)` | `0.15` | — | No aplica en aviación |
| `turbulence` | — | `0.15` | Nuevo — CAT es riesgo operacional crítico |
| `contrail` | — | `0.10` | Nuevo — impacto climático diferenciado |
| `cloud_top` | — | `0.10` | Nuevo — convección profunda obliga a desvíos |
| `aerosol / aod` | — | `0.15` total | Nuevo — polvo árabe en ruta DXB |
| `co` | — | `0.05` | Nuevo — trazador de combustión |
| `so2` | `0.10` | — | Eliminado — ECA no aplica en aviación |

### 6.3 `normalization` — Rangos de normalización por capa

| Capa | Min | Max | Nota |
|---|---|---|---|
| `no2_mol_m2` | `0` | `0.0002` | mol/m² |
| `co_mol_m2` | `0` | `0.05` | mol/m² |
| `wind_speed_250` | `0` | `60` | m/s — **mayor velocidad = MEJOR** (viento de cola) |
| `turbulence` | `0` | `30` | Índice adimensional — mayor = peor |
| `contrail_risk` | `0` | `1` | Probabilidad — mayor = peor |
| `cloud_top_height_m` | `0` | `15,000` | metros — mayor = peor (convección activa) |
| `aerosol_index` | `-1` | `5` | Adimensional — mayor = peor |
| `aod` | `0` | `1` | Adimensional — mayor = peor |

> **Inversión de lógica para viento:** A diferencia de todas las demás capas donde mayor valor = peor, para `wind_speed_250` la normalización es **inversa** — mayor velocidad de viento en la dirección de vuelo es favorable (viento de cola reduce consumo). El CorridorOptimizer debe aplicar la inversión correcta según la componente de viento alineada con el heading de la ruta.

### 6.4 `badge_thresholds` — Umbrales de certificación

| Badge | Condición | Acción recomendada |
|---|---|---|
| `GREEN` | `score ≥ 65` | Ruta óptima confirmada — condiciones favorables |
| `WARN` | `45 ≤ score < 65` | Condición esperada en invierno boreal — evaluar segmentos de mayor riesgo |
| `RED` | `score < 45` | Evaluar ruta alternativa — turbulencia severa, polvo extremo o convección activa |

> **Nota operacional:** Un score WARN (`45–64`) en el corredor PVG→DXB→AMS en marzo es la **condición base esperada** para rutas de largo radio en invierno boreal. El CertificationJudge no debe emitir RED automáticamente si el score es 48–55 y el trigger es `scheduler`. El contexto estacional es determinante.

---

## 7. Estructura del campo `data` en cada capa

Todas las capas en `layers.*` tienen la misma estructura de matriz:

```
data[row][col]  →  valor de la celda en fila=row, columna=col

- row: 0..59  (norte a sur, row=0 = lat 74.5°N)
- col: 0..124 (oeste a este, col=0 = lon 0.5°E)
- Celdas sin datos satelitales: null (solo en capas Sentinel-5P)
- Capas de modelo (GFS/ERA5): sin nulls — cobertura global completa
```

**Fórmula de conversión índice → coordenadas:**

```python
lat = 75.0 - (row * 1.0) - 0.5   # centro de la celda
lon = 0.0  + (col * 1.0) + 0.5   # centro de la celda
```

**Ejemplo de localización de aeropuertos en la grilla:**

| Aeropuerto | Lat / Lon | row | col |
|---|---|---|---|
| PVG (Shanghai Pudong) | 31.14°N / 121.81°E | `43` | `121` |
| DXB (Dubai Intl) | 25.25°N / 55.36°E | `49` | `55` |
| AMS (Amsterdam Schiphol) | 52.31°N / 4.76°E | `22` | `4` |

```python
# Verificación PVG: row = floor((75.0 - 31.14) / 1.0) = floor(43.86) = 43 ✓
# Verificación DXB: row = floor((75.0 - 25.25) / 1.0) = floor(49.75) = 49 ✓
# Verificación AMS: row = floor((75.0 - 52.31) / 1.0) = floor(22.69) = 22 ✓
```

---

## 8. Resumen de fuentes de datos

| Capa | Satélite / Modelo | Colección GEE | Resolución nativa | Frecuencia |
|---|---|---|---|---|
| `no2_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_NO2` | ~3.5 km | Diario |
| `co_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_CO` | ~7 km | Diario |
| `wind_u_ms` / `wind_v_ms` | NOAA GFS 0.25° / ERA5 | `NOAA/GFS0P25` | ~28 km | 6-horario |
| `turbulence_index` | Derivado de GFS/ERA5 | — | ~28 km | 6-horario |
| `contrail_risk` | Derivado de ERA5 | — | ~28 km | 6-horario |
| `cloud_top_height_m` | Derivado de GFS | — | ~28 km | 6-horario |
| `aerosol_index` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_AER_AI` | ~3.5 km | Diario |
| `aod` | MODIS / Sentinel-5P | `MODIS/006/MOD04_L2` | ~3–10 km | Diario |
| `green_score` | Calculado | — | ~111 km | Por ejecución |

---

## 9. Consideraciones de riesgo específicas del modo aviación

### Jet stream polar (diciembre–marzo)
El jet stream sobre Europa Central puede superar los 50 m/s (~180 km/h) en invierno. Las rutas hacia el oeste (PVG→AMS) enfrentan fuertes vientos en contra en latitudes medias. El CorridorOptimizer debe evaluar si una ruta más al sur (sobre el Mediterráneo) con menor headwind compensa la mayor distancia.

### Polvo árabe y shamal sobre DXB (todo el año, pico en primavera)
Las tormentas shamal pueden elevar el AOD a >1.5 y el aerosol_index a >3.5 en el área de Dubai. Estas condiciones pueden reducir la visibilidad en aproximación al aeropuerto. Si `aerosol_index > 2.5` en las 3 celdas más cercanas a DXB → el CertificationJudge debe emitir WARN para el segmento intermedio aunque el score global sea GREEN.

### Clear Air Turbulence (CAT) sobre el Himalaya
Las celdas sobre Nepal/Tibet (~rows 28–35, cols ~85–100) muestran turbulencia alta de forma estructural debido al wind shear del jet stream al pasar sobre la orografía. El CorridorOptimizer debe tener configuradas estas celdas como de alto costo independientemente del índice reportado.

### Contrails persistentes en latitudes medias (40°N–60°N)
La banda 40°N–60°N en invierno y primavera temprana presenta las condiciones más favorables para contrails persistentes (humedad alta a FL350, temperaturas < −50°C). El CertificationJudge debe reportar el `contrail_risk` medio del segmento europeo de la ruta (cols ~0–40) y comparar con el baseline histórico de la ventana P1.

### Cobertura nubosa Sentinel-5P sobre latitudes altas
Por encima de 65°N, la cobertura nubosa persistente puede invalidar datos TROPOMI en hasta el 40–50% de las celdas en invierno. Las celdas con `null` en `no2_mol_m2` y `aerosol_index` en el sector polar de la grilla (rows ~0–10, lat > 65°N) deben rellenarse con el valor medio de las filas adyacentes o excluirse del scoring con un flag `data_quality: "low"`.
