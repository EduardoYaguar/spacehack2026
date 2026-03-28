# Diccionario de Datos — terrestrial_usa_nynj_savannah.json
> GreenRoute Intelligence Platform · Corredor NY/NJ → Savannah · Versión 2.0

---

## Resumen del dataset

| Propiedad | Valor |
|---|---|
| `grid_id` | `terrestrial-usa-nynj-savannah` |
| `mode` | `trucking` |
| `generated_at` | `2026-03-28T00:27:21.718768+00:00` (UTC) |
| `version` | `2.0` |
| `window.label` | `P1` |
| `window.start` | `2026-03-05` |
| `window.end` | `2026-03-19` |
| `window.days` | `14` días |
| Grilla | 200 filas × 180 columnas = 36,000 celdas totales |
| Celdas de carretera (road_mask = 1) | 17,651 (49.0%) |
| Celdas sin carretera (road_mask = 0) | 18,349 (51.0%) |
| Fuente de road_mask | `TIGER/2016/Roads — S1100 interstates + S1200 US highways, buffer 5 km` |

---

## 1. Metadatos del dataset

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `grid_id` | `string` | Identificador único del dataset | `"terrestrial-usa-nynj-savannah"` |
| `mode` | `string` | Modo de transporte del corredor | `"trucking"` |
| `generated_at` | `string` (ISO 8601) | Timestamp de generación del payload en UTC | `2026-03-28T00:27:21.718768+00:00` |
| `version` | `string` | Versión del esquema del payload | `"2.0"` |
| `window.label` | `string` | Etiqueta de la ventana temporal del compuesto | `"P1"` (período 1) |
| `window.start` | `string` (ISO 8601 date) | Inicio de la ventana de agregación | `"2026-03-05"` |
| `window.end` | `string` (ISO 8601 date) | Fin de la ventana de agregación | `"2026-03-19"` |
| `window.days` | `int` | Duración de la ventana en días | `14` |

> **Primer modo terrestre del sistema.** A diferencia de los modos marítimo (`maritime`) y aéreo (`aviation`), el modo `trucking` introduce capas sin equivalente en los otros modos: **slope** (pendiente del terreno), **snow_cover** (cobertura de nieve MODIS), **precipitation** (GPM IMERG), **temperature** (ERA5-Land) y **congestion vial** (VIIRS DNB como proxy de densidad de tráfico en carretera). La road_mask reemplaza a la land_mask marítima con una fuente catastral oficial (TIGER 2016).

---

## 2. Puntos de origen y destino

### `origin` — object

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del puerto de origen | `"Port NY/NJ (Newark)"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `40.68` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `-74.15` |

### `destination` — object

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `name` | `string` | Nombre del puerto de destino | `"Port of Savannah"` |
| `lat` | `float` | Latitud en grados decimales (EPSG:4326) | `32.08` |
| `lon` | `float` | Longitud en grados decimales (EPSG:4326) | `-81.09` |

> **Corredor intermodal:** Este corredor conecta los dos mayores puertos de la costa este de EE.UU. El tráfico predominante son camiones de carga intermodal (contenedores en chassis) operando por la I-95 y rutas US-17/US-301. La distancia por carretera es aproximadamente 1,370 km (~852 millas).

---

## 3. Definición de la grilla — `grid_definition`

| Campo | Tipo | Descripción | Valor |
|---|---|---|---|
| `bounds.north` | `float` | Límite norte del bounding box | `41.5°N` |
| `bounds.south` | `float` | Límite sur del bounding box | `31.5°N` |
| `bounds.east` | `float` | Límite este del bounding box | `−73.5°W` |
| `bounds.west` | `float` | Límite oeste del bounding box | `−82.5°W` |
| `cell_size_degrees` | `float` | Resolución angular de cada celda | `0.05°` |
| `cell_size_approx_km` | `float` | Resolución espacial aproximada en km | `5.6 km` |
| `rows` | `int` | Número de filas (eje latitud, N→S) | `200` |
| `cols` | `int` | Número de columnas (eje longitud, W→E) | `180` |
| `total_cells` | `int` | Total de celdas en la grilla (200 × 180) | `36,000` |
| `road_cells` | `int` | Celdas con road_mask = 1 (transitables) | `17,651` |
| `road_mask_source` | `string` | Fuente de la máscara de carreteras | `TIGER/2016/Roads — clases S1100 (interstates) y S1200 (US highways), buffer 5 km` |
| `coordinate_system` | `string` | Sistema de coordenadas geográficas | `"EPSG:4326"` |

**Fórmula de conversión [row, col] → [lat, lon]:**

```python
lat = 41.5 - (row * 0.05) - 0.025   # centro de la celda
lon = -82.5 + (col * 0.05) + 0.025  # centro de la celda
```

**Ejemplo de conversión:**
- Celda `[row=0, col=0]` → `lat: 41.475°N, lon: −82.475°W` (esquina noroeste)
- Celda `[row=199, col=179]` → `lat: 31.525°N, lon: −73.525°W` (esquina sureste)

**Ejemplo de localización de puertos en la grilla:**

| Puerto | Lat / Lon | row | col |
|---|---|---|---|
| Port NY/NJ (Newark) | 40.68°N / −74.15°W | `16` | `167` |
| Port of Savannah | 32.08°N / −81.09°W | `188` | `28` |

```python
# Verificación NY/NJ: row = floor((41.5 - 40.68) / 0.05) = floor(16.4) = 16 ✓
# Verificación Savannah: row = floor((41.5 - 32.08) / 0.05) = floor(188.4) = 188 ✓
```

**Comparativa de resolución entre modos:**

| Parámetro | Marítimo (SGP→PKL) | Aviación (PVG→AMS) | Terrestre (NY/NJ→SAV) |
|---|---|---|---|
| Resolución celda | `0.1°` (~11.1 km) | `1.0°` (~111 km) | `0.05°` (~5.6 km) |
| Dimensiones | 40 × 60 | 60 × 125 | 200 × 180 |
| Total celdas | 2,400 | 7,500 | 36,000 |
| Máscara | Land mask (agua/tierra) | Sin máscara | Road mask (TIGER 2016) |
| Celdas válidas | 892 agua | 7,173 sin null | 17,651 viales |

> La resolución de `0.05°` (~5.6 km) es la más alta del sistema, coherente con la precisión catastral de las vías de TIGER/2016 y con la granularidad necesaria para diferenciar rutas alternativas en zonas urbanas densas como el NJ Turnpike o el área metropolitana de Washington D.C.

---

## 4. Máscara vial — `road_mask`

| Campo | Tipo | Descripción | Detalle |
|---|---|---|---|
| `desc` | `string` | Descripción de los valores | `"1 = road cell (transitable), 0 = no road"` |
| `data` | `matrix [200×180]` | Matriz binaria de transitabilidad vial | `0.0` (sin carretera) o `1.0` (con carretera) |

**Estadísticas verificadas:**

| Valor | Celdas | Porcentaje |
|---|---|---|
| `1.0` (carretera) | `17,651` | `49.0%` |
| `0.0` (sin carretera) | `18,349` | `51.0%` |
| Total | `36,000` | `100%` |

**Fuente y criterio de inclusión:**

La road_mask se construyó a partir del dataset **TIGER/2016 Roads** del U.S. Census Bureau, filtrando únicamente las clases:
- `S1100` — Primary Roads (interstates, autopistas de acceso controlado)
- `S1200` — Secondary Roads (US Highways numeradas)

Cada segmento vial calificado se dilató con un **buffer de 5 km** para asegurar que las celdas de 5.6 km capturen la carretera aunque no pase exactamente por el centro de la celda.

**Implicación para el CorridorOptimizer:** Solo las celdas con `road_mask = 1` se incluyen como nodos en el grafo NetworkX. Las celdas con `road_mask = 0` son excluidas del pathfinding A*, incluso si tienen datos satelitales válidos. Rutas secundarias (county roads, state routes menores) no están incluidas — el optimizer trabaja exclusivamente sobre la red de autopistas federales.

> **Diferencia clave con modo marítimo:** La land_mask marítima es binaria agua/tierra derivada de datos físicos (SRTM + JRC). La road_mask terrestre es una máscara **catastral** derivada del inventario vial federal — no del terreno físico. Una celda puede ser transitada por carretera aunque esté en zona montañosa o boscosa.

---

## 5. Capas estáticas — `static_layers`

Las capas estáticas no varían entre ventanas temporales. Son propiedades físicas permanentes del terreno que se calculan una sola vez y se reusan en todas las ejecuciones. Solo existen en el modo `trucking` — no tienen equivalente en los modos marítimo o aéreo.

---

### 5.1 `static_layers.elevation_m` — Elevación del terreno

**Rol en el sistema:** Dato de referencia altimétrico. Informa el contexto topográfico del corredor y es la base para calcular el `slope_deg`. No tiene peso directo en el green_score, pero es insumo indirecto a través de la pendiente.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"SRTM elevation"` |
| `source` | `string` | `USGS SRTM 30m` |
| `unit` | `string` | `metros sobre el nivel del mar` |
| `stats.mean` | `float` | `239.0 m` |
| `stats.max` | `float` | `1,649 m` (crestas de los Apalaches en Virginia/Carolina del Norte) |
| `stats.min` | `float` | `0 m` (zonas costeras en NJ y GA) |
| `valid_cells` | `int` | `17,632` |
| `data` | `matrix [200×180]` | Valores en metros; `null` en celdas sin road_mask |

> **Nota geográfica:** El corredor NY/NJ→Savannah cruza las montañas Blue Ridge y la región Piedmont. Las celdas de elevación > 800 m corresponden a los pasos montañosos de Virginia y Carolina del Norte. Estos segmentos son de particular relevancia para el cálculo de pendiente y consumo de combustible.

---

### 5.2 `static_layers.slope_deg` — Pendiente del terreno

**Rol en el sistema:** Indicador de consumo adicional de combustible por esfuerzo del motor en ascensos. Es uno de los dos factores con mayor peso en el green_score terrestre (junto con NO2 y congestion). Una pendiente de 5°+ puede duplicar el consumo de un camión de 40 toneladas.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Terrain slope — 5°+ doubles truck fuel consumption"` |
| `source` | `string` | `ee.Terrain.slope(SRTM)` — calculado sobre Google Earth Engine a partir del DEM SRTM |
| `unit` | `string` | `grados (°)` |
| `stats.mean` | `float` | `0.4°` (corredor predominantemente plano en zonas costeras) |
| `stats.max` | `float` | `6.34°` (paso montañoso en los Apalaches) |
| `stats.min` | `float` | `0°` (llanuras costeras de NJ, DE, MD, VA, NC, SC, GA) |
| `valid_cells` | `int` | `17,651` |
| `data` | `matrix [200×180]` | Valores en grados; `null` en celdas sin road_mask |

**Peso en green_score:** `0.20` — compartido con NO2 como el mayor peso individual del corredor terrestre.

**Regla de negocio:** Celdas con `slope_deg ≥ 5.0` deben ser marcadas como de **alto costo de combustible**. El CorridorOptimizer puede proponer desvíos con mayor distancia pero menor pendiente acumulada si el ahorro de CO2 por reducción de slope supera el costo adicional de distancia.

> **Capa sin equivalente en modos marítimo y aéreo.** El modo marítimo usa `wave_height_m` como análogo de resistencia física al movimiento, pero la lógica de cálculo y el impacto en emisiones son completamente distintos.

---

## 6. Capas dinámicas — `layers`

Las capas dinámicas se recalculan en cada ventana temporal (P1, P2, etc.). Corresponden a condiciones ambientales y de tráfico que cambian con el tiempo. El corredor terrestre tiene **10 capas dinámicas**, frente a 7 del marítimo y 8 de la aviación.

---

### 6.1 `layers.no2_mol_m2` — Dióxido de nitrógeno troposférico

**Rol en el sistema:** En el modo trucking, el NO2 es un **proxy de saturación del corredor por tráfico diesel pesado**. Un NO2 elevado indica alta densidad de camiones en ese segmento vial — señal de congestión potencial y alta huella de emisiones por unidad de distancia.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Tropospheric NO₂ — diesel emissions, corridor saturation"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `collection` | `string` | `COPERNICUS/S5P/OFFL/L3_NO2` |
| `band` | `string` | `tropospheric_NO2_column_number_density` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Compuesto 14 días (2026-03-05 → 2026-03-19) |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `3.710 × 10⁻⁵ mol/m²` |
| `stats.max` | `float` | `1.936 × 10⁻⁴ mol/m²` (área metropolitana NY/NJ) |
| `stats.min` | `float` | `1.2 × 10⁻⁵ mol/m²` |
| `data` | `matrix [200×180]` | Valores en mol/m²; `null` en celdas sin road_mask |

**Peso en green_score:** `0.20` — mayor peso junto con slope y congestion.

> **Regla de negocio:** Si `no2_mean > 2.5×10⁻⁵ mol/m²` en un segmento → el SatelliteAnalyst debe correlacionar con `co_mol_m2` y `viirs_nw` para confirmar si la señal es de tráfico vial o de fuente industrial puntual (refinería, central eléctrica). El NJ Turnpike y la I-95 en los tramos urbanos de Baltimore y Washington D.C. presentarán NO2 estructuralmente alto — no es una anomalía sino la línea base esperada del corredor.

> **Confound urbano:** Las celdas sobre el área metropolitana de NY/NJ, Philadelphia, Baltimore y Washington D.C. tienen NO2 elevado de múltiples fuentes (vehículos ligeros, industria, calefacción). El CertificationJudge no debe atribuir este NO2 exclusivamente al tráfico de camiones. Usar `co_mol_m2` como discriminador: CO alto + NO2 alto → tráfico denso; NO2 alto sin CO correlativo → fuente industrial estacionaria.

---

### 6.2 `layers.so2_mol_m2` — Dióxido de azufre

**Rol en el sistema:** Indicador de calidad del combustible diésel y presencia de fuentes industriales fijas a lo largo del corredor. En el contexto terrestre EE.UU., el SO2 de origen vehicular es bajo (combustible ULSD, azufre < 15 ppm), por lo que valores elevados suelen indicar fuentes industriales (plantas de carbón, refinerías) cercanas a la ruta.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"SO₂ — fuel quality and industrial pollution"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `collection` | `string` | `COPERNICUS/S5P/OFFL/L3_SO2` |
| `band` | `string` | `SO2_column_number_density` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Compuesto 14 días |
| `valid_cells` | `int` | `10,018` (cobertura parcial por nubosidad) |
| `stats.mean` | `float` | `1.377 × 10⁻⁴ mol/m²` (media sobre celdas con datos) |
| `stats.max` | `float` | `1.022 × 10⁻³ mol/m²` |
| `stats.min` | `float` | `0.0 mol/m²` |
| `data` | `matrix [200×180]` | Valores en mol/m²; `null` en celdas sin datos o sin road_mask |

**Peso en green_score:** `0.05` — peso menor, ya que en EE.UU. el SO2 vehicular es residual por regulación EPA.

> **Advertencia de cobertura:** Solo `10,018` de las `17,651` celdas de carretera tienen datos SO2 válidos (~57% de cobertura). Las celdas con `null` en esta capa no deben penalizarse en el green_score — el CorridorOptimizer debe usar el valor medio de las celdas adyacentes válidas como fallback o excluir la capa del scoring para esa celda.

> **Confound industrial:** Celdas adyacentes a la planta de generación de carbón de Dominion Energy en Virginia y la refinería de Marcus Hook en Pennsylvania pueden mostrar SO2 elevado sin relación con el tráfico de camiones. El CertificationJudge debe verificar la distancia a instalaciones industriales registradas antes de emitir WARN por SO2 en estos segmentos.

---

### 6.3 `layers.co_mol_m2` — Monóxido de carbono troposférico

**Rol en el sistema:** En modo terrestre, el CO es el mejor **proxy de tráfico stop-and-go** y combustión incompleta por ralentí prolongado. Valores elevados en segmentos de autopista indican congestión severa con motores al ralentí — la condición de mayor consumo de combustible y emisiones por kilómetro para un camión pesado.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"CO — stop-and-go traffic proxy, incomplete combustion"` |
| `source` | `string` | `Sentinel-5P TROPOMI` |
| `collection` | `string` | `COPERNICUS/S5P/OFFL/L3_CO` |
| `band` | `string` | `CO_column_number_density` |
| `unit` | `string` | `mol/m²` |
| `temporal_aggregation` | `string` | Compuesto 14 días |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `0.0303 mol/m²` |
| `stats.max` | `float` | `0.0370 mol/m²` |
| `stats.min` | `float` | `0.0236 mol/m²` |
| `data` | `matrix [200×180]` | Valores en mol/m²; `null` en celdas sin road_mask |

**Peso en green_score:** `0.10`

> **Regla de negocio:** CO > `0.035 mol/m²` en celdas de autopista es indicativo de congestión severa con emisiones de combustión incompleta. Correlacionar siempre con `viirs_nw` (congestion proxy): CO alto + VIIRS alto = congestión activa confirmada; CO alto + VIIRS bajo = posible fuente puntual no vial (incendio, industria).

---

### 6.4 `layers.temperature_k` — Temperatura superficial del aire

**Rol en el sistema:** La temperatura afecta directamente la **eficiencia del motor diésel y la carga del sistema de climatización** del camión. Temperaturas muy bajas (< 270 K / −3°C) incrementan el consumo por calefacción de cabina y por mayor viscosidad del aceite. Temperaturas muy altas (> 305 K / 32°C) incrementan el consumo por aire acondicionado y reducen la eficiencia volumétrica del motor.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Surface air temp — engine efficiency, A/C load"` |
| `source` | `string` | `ERA5-Land` |
| `collection` | `string` | `ECMWF/ERA5_LAND/HOURLY` |
| `band` | `string` | `temperature_2m` |
| `unit` | `string` | `Kelvin (K)` |
| `temporal_aggregation` | `string` | Media 14 días (media horaria ERA5-Land) |
| `valid_cells` | `int` | `17,327` |
| `stats.mean` | `float` | `284.9 K` (~11.8°C — clima de transición primaveral en el corredor) |
| `stats.max` | `float` | `292.6 K` (~19.5°C — costa de Georgia, zona de Savannah) |
| `stats.min` | `float` | `277.3 K` (~4.1°C — segmentos del norte de New Jersey) |
| `data` | `matrix [200×180]` | Valores en Kelvin; `null` en celdas sin datos ERA5 o sin road_mask |

**Peso en green_score:** No tiene peso directo — es una capa informativa que contextualiza el consumo de combustible esperado. El CertificationJudge puede referenciarla al evaluar el razonamiento del SatelliteAnalyst.

> **Conversión de referencia:** `K - 273.15 = °C`. El rango observado (277–293 K) corresponde a 4–20°C, condiciones óptimas para motores diésel pesados — sin penalización significativa por temperatura en esta ventana P1 de marzo.

> **Capa sin equivalente en modos marítimo y aéreo** en su forma actual. El modo marítimo usa la capa de viento (ERA5/GFS) pero no temperatura de superficie. El modo aéreo opera a 250 hPa donde la temperatura es siempre < −50°C y se modela dentro de la capa `contrail_risk`.

---

### 6.5 `layers.wind_u_ms` — Componente U del viento a 10 m (este-oeste)

**Rol en el sistema:** Componente de resistencia o asistencia del viento en la dirección de marcha este-oeste para los camiones. Un viento predominantemente del oeste (wind_u positivo) genera resistencia aerodinámica en la dirección NY→Savannah, incrementando el consumo de combustible.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Eastward wind 10m — headwind drag on trucks"` |
| `source` | `string` | `NOAA GFS` |
| `collection` | `string` | `NOAA/GFS0P25` |
| `band` | `string` | `u_component_of_wind_10m_above_ground` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el este) |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `1.16 m/s` (viento leve del oeste → ligero headwind en tramos orientados hacia el sur) |
| `stats.max` | `float` | `3.18 m/s` |
| `stats.min` | `float` | `−0.71 m/s` (viento del este en zonas costeras) |
| `data` | `matrix [200×180]` | Valores en m/s |

**Peso combinado wind_u + wind_v en green_score:** `0.05` — peso muy bajo. El viento a superficie tiene impacto moderado en camiones pesados (resistencia aerodinámica ~ 15–20% del consumo total a 90 km/h) y es el factor de menor variabilidad espacial en este corredor.

> **Diferencia con modos anteriores:** En el modo marítimo, el viento tiene peso `0.20` porque afecta directamente la propulsión de los barcos. En aviación, es `0.35` por el impacto del jet stream. En trucking, el viento es un factor secundario — la pendiente y la congestión dominan el consumo de combustible de un camión pesado.

---

### 6.6 `layers.wind_v_ms` — Componente V del viento a 10 m (norte-sur)

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Northward wind 10m"` |
| `source` | `string` | `NOAA GFS` |
| `collection` | `string` | `NOAA/GFS0P25` |
| `band` | `string` | `v_component_of_wind_10m_above_ground` |
| `unit` | `string` | `m/s` (positivo = sopla hacia el norte) |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `0.89 m/s` (viento leve del sur → asistencia en tramos orientados al norte) |
| `stats.max` | `float` | `2.01 m/s` |
| `stats.min` | `float` | `−0.26 m/s` |
| `data` | `matrix [200×180]` | Valores en m/s |

> **Nota:** El corredor NY/NJ→Savannah tiene orientación predominantemente norte-sur (~ N→S). Por tanto, `wind_v_ms` es la componente más relevante para calcular el headwind/tailwind real en este corredor. Un `wind_v_ms` positivo (viento del sur) implica viento en contra para el tramo NY→Savannah.

---

### 6.7 `layers.viirs_nw` — Radiancia nocturna VIIRS (proxy de congestión vial)

**Rol en el sistema:** En el modo terrestre, la radiancia VIIRS es un **proxy de densidad de tráfico en carretera**, específicamente de la intensidad lumínica de los faroles vehiculares y señalización vial capturada en imágenes nocturnas. A mayor radiancia en una celda de autopista, mayor densidad de vehículos en ese tramo durante el mes de referencia.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Nighttime radiance — highway congestion proxy"` |
| `source` | `string` | `VIIRS Day/Night Band monthly composite` |
| `collection` | `string` | `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG` |
| `band` | `string` | `avg_rad` |
| `unit` | `string` | `nW/cm²/sr` |
| `temporal_aggregation` | `string` | Compuesto mensual (febrero 2026) |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `4.07 nW/cm²/sr` |
| `stats.max` | `float` | `158.32 nW/cm²/sr` (área metropolitana NY/NJ — mayor densidad lumínica del corredor) |
| `stats.min` | `float` | `0.0 nW/cm²/sr` (tramos rurales de Carolina del Sur y Georgia) |
| `data` | `matrix [200×180]` | Valores en nW/cm²/sr; `null` en celdas sin road_mask |

**Peso en green_score:** `0.20` — uno de los mayores pesos, reflejando que la congestión vial es el factor de mayor impacto en emisiones por km recorrido para un camión pesado.

**Normalización:** `min=0, max=60 nW/cm²/sr`. Valores superiores a 60 (como el máximo de 158.32 en NY/NJ) se truncan al máximo de normalización — la escala captura el rango operacional relevante de la red de autopistas, excluyendo el ruido urbano extremo de las zonas metropolitanas densas.

> **Advertencia de interpretación:** Al igual que en el modo marítimo, VIIRS es un **promedio mensual** — no refleja congestión en tiempo real sino la densidad estructural histórica de cada tramo. Un tramo con VIIRS alto es estructuralmente congestionado (ej. I-95 en el NJ Turnpike), no necesariamente congestionado en el momento de la evaluación. El CertificationJudge no debe emitir RED solo por VIIRS alto aislado.

---

### 6.8 `layers.precip_mm` — Precipitación

**Rol en el sistema:** La precipitación activa reduce la tracción del camión, obliga a reducir la velocidad por seguridad, incrementa el riesgo de aquaplaning y puede provocar el cierre temporal de tramos de autopista. Es el único factor de **riesgo de seguridad vial** con peso explícito en el green_score.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Precipitation — traction loss, speed reduction, safety risk"` |
| `source` | `string` | `NASA GPM IMERG` |
| `collection` | `string` | `NASA/GPM_L3/IMERG_V07` |
| `band` | `string` | `precipitation` |
| `unit` | `string` | `mm/hr` |
| `temporal_aggregation` | `string` | Media 14 días (2026-03-05 → 2026-03-19) |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `0.132 mm/hr` (precipitación leve — típica de marzo en el corredor) |
| `stats.max` | `float` | `0.423 mm/hr` (eventos de lluvia moderada en el Piedmont de Carolina del Norte) |
| `stats.min` | `float` | `0.025 mm/hr` |
| `data` | `matrix [200×180]` | Valores en mm/hr; `null` en celdas sin road_mask |

**Peso en green_score:** `0.08`

**Normalización:** `min=0, max=5 mm/hr`. El rango observado (0.025–0.423 mm/hr) está en el extremo bajo de la escala — condiciones de lluvia leve a moderada. Valores > 2 mm/hr (lluvia intensa) son excepcionales en este corredor en marzo y dispararían un aumento significativo del costo de celda.

> **Regla de negocio:** Si `precip_mm > 1.5 mm/hr` en más del 20% de las celdas de un segmento → el SatelliteAnalyst debe marcarlo como `weather_hazard: true` en el SatelliteReport. El CertificationJudge debe considerar si el evento es puntual o sistémico antes de emitir WARN.

> **Fuente de alta resolución espacial:** GPM IMERG tiene resolución nativa de ~11 km, remuestreada a ~5.6 km por la grilla. Es la fuente de precipitación de mayor cobertura global para este uso, superando a los pluviómetros de superficie en cobertura espacial.

---

### 6.9 `layers.snow_cover` — Cobertura de nieve NDSI

**Rol en el sistema:** Indicador de **riesgo de cierre vial y requisito de cadenas**. En el corredor NY/NJ→Savannah, la nieve activa es relevante en los meses de invierno en los tramos del norte (New Jersey, Delaware, Maryland, Virginia) y en los pasos montañosos de los Apalaches. En el período P1 de marzo, la cobertura es residual pero presente en latitudes altas.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Snow cover NDSI — road closures, chain requirements"` |
| `source` | `string` | `MODIS MOD10A1` |
| `collection` | `string` | `MODIS/061/MOD10A1` |
| `band` | `string` | `NDSI_Snow_Cover` |
| `unit` | `string` | `Índice NDSI 0–100` |
| `temporal_aggregation` | `string` | Media 14 días |
| `valid_cells` | `int` | `17,615` |
| `stats.mean` | `float` | `1.87` (cobertura de nieve baja — consistent con marzo avanzado) |
| `stats.max` | `float` | `36.0` (tramos elevados de los Apalaches en Virginia/NC) |
| `stats.min` | `float` | `0.0` (tramos costeros desde Maryland hacia el sur) |
| `data` | `matrix [200×180]` | Valores NDSI 0–100; `null` en celdas sin datos MODIS o sin road_mask |

**Peso en green_score:** `0.07`

**Interpretación del índice NDSI:**

| Rango NDSI | Cobertura de nieve | Implicación operacional |
|---|---|---|
| `0` | Sin nieve | Normal |
| `1 – 20` | Nieve residual o parcial | Posible hielo en superficie — precaución |
| `21 – 50` | Cobertura moderada | Velocidad reducida — posible requerimiento de cadenas |
| `51 – 100` | Cobertura alta | Riesgo de cierre vial — WARN automático |

> **Regla de negocio:** Si `snow_cover > 40` en cualquier celda del path óptimo → el CertificationJudge debe emitir al menos WARN para ese segmento e incluir `weather_advisory: "snow_chain_required"` en el CertDecision, independientemente del green_score global.

> **Capa sin equivalente en modos marítimo y aéreo.**

---

### 6.10 `layers.aod` — Profundidad Óptica de Aerosoles (AOD)

**Rol en el sistema:** En el contexto terrestre, el AOD es un indicador de **calidad del aire a lo largo del corredor**, relevante tanto para la salud de los conductores como para las regulaciones de emisión en zonas de control de calidad del aire (AQCR) de la EPA. Un AOD elevado puede correlacionar con días de alta contaminación donde los camiones con motores Tier 4 activarán sistemas de post-tratamiento de gases de escape adicionales, reduciendo la eficiencia de combustible.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Aerosol Optical Depth — air quality along corridor"` |
| `source` | `string` | `MODIS MOD08_M3` |
| `collection` | `string` | `MODIS/061/MOD08_M3` |
| `band` | `string` | `Aerosol_Optical_Depth_Land_Ocean_Mean_Mean` |
| `unit` | `string` | `Valor escalar MODIS — escala interna 0–256 (sin factor de escala aplicado)` |
| `valid_cells` | `int` | `14,574` (cobertura parcial — resolución nativa MODIS ~1°) |
| `stats.mean` | `float` | `84.15` (escala interna MODIS) |
| `stats.max` | `float` | `256.0` (valor máximo de saturación MODIS) |
| `stats.min` | `float` | `11.0` |
| `data` | `matrix [200×180]` | Valores en escala interna MODIS 0–256; `null` en celdas sin cobertura |

**Peso en green_score:** `0.05`

**Normalización en el optimizer:** `min=0, max=1` — el corridoriq_config normaliza los valores brutos MODIS al rango [0,1] antes de aplicar el peso. La escala interna MODIS (0–256) se divide por 256 para obtener la fracción normalizada.

> **Advertencia de escala:** A diferencia del modo aéreo donde el AOD está en escala física adimensional (0.0–1.0+), en este payload los valores están en la **escala interna MODIS sin factor de escala aplicado** (0–256). El CorridorOptimizer debe dividir por 256 antes de normalizar. Un valor de 84 en escala interna ≈ 0.33 en escala física AOD — equivalente a condiciones de aerosol moderado.

> **Cobertura reducida:** Solo `14,574` de las `17,651` celdas viales tienen datos AOD válidos (~82.5%). La resolución nativa de MOD08_M3 es ~1°, remuestreada a 0.05° — la cobertura gaps corresponden a celdas en los bordes de los píxeles MODIS originales.

---

## 7. Capa derivada — `derived_layers`

### 7.1 `derived_layers.green_score` — Score verde precomputado (trucking)

**Rol en el sistema:** Score 0–100 calibrado para el modo trucking, incorporando todas las capas dinámicas y estáticas ponderadas según los pesos del `corridoriq_config`. Listo para usarse en el dashboard como heatmap de ruta y en el CorridorOptimizer como `cost_node = 100 - green_score`.

| Campo | Tipo | Valor |
|---|---|---|
| `desc` | `string` | `"Weighted green score (0-100). Road-specific, slope-aware."` |
| `formula` | `string` | `score = 100 × (1 - weighted_cost)` donde `cost = 0.20×NO2 + 0.05×SO2 + 0.10×CO + 0.20×slope + 0.20×congestion + 0.05×wind + 0.08×precip + 0.07×snow + 0.05×aod` |
| `valid_cells` | `int` | `17,651` |
| `stats.mean` | `float` | `82.0` |
| `stats.max` | `float` | `89.0` |
| `stats.min` | `float` | `49.5` |
| `distribution.GREEN` | `int` | `17,502 celdas (99.2%)` |
| `distribution.WARN` | `int` | `149 celdas (0.8%)` |
| `distribution.RED` | `int` | `0 celdas (0.0%)` |
| `data` | `matrix [200×180]` | Valores score 0–100; `null` en celdas sin road_mask |

> **Diferencia crítica con modos anteriores:** El green_score medio del corredor terrestre (~82.0) es el **más alto del sistema**, superando al marítimo (~74.5) y muy por encima del aéreo (~46.0). Esto refleja que las condiciones del corredor NY/NJ→Savannah en P1 de marzo son estructuralmente favorables: clima de transición, pendiente media baja (0.4°), y congestión moderada fuera de los tramos metropolitanos del norte. Las celdas WARN (149) están concentradas en los tramos del NJ Turnpike y la I-95 en el área de Washington D.C., donde la congestión VIIRS y el NO2 son estructuralmente elevados.

---

## 8. Configuración del optimizador — `corridoriq_config`

### 8.1 `weights` — Pesos del costo de arista para A* (trucking)

| Capa | Peso | Descripción |
|---|---|---|
| `no2` | `0.20` | Saturación del corredor por tráfico diésel |
| `slope` | `0.20` | Pendiente — factor dominante de consumo de combustible |
| `congestion` | `0.20` | Densidad VIIRS — proxy de congestión estructural |
| `co` | `0.10` | Stop-and-go, combustión incompleta |
| `precip` | `0.08` | Riesgo de tracción — lluvia activa |
| `snow` | `0.07` | Riesgo de cierre vial — nieve y hielo |
| `so2` | `0.05` | Calidad del combustible e industria fija |
| `wind` | `0.05` | Resistencia aerodinámica — factor secundario |
| `aod` | `0.05` | Calidad del aire — carga de aerosoles |
| **Total** | **1.00** | Los pesos suman 1.0 |

**Comparativa de pesos entre los tres modos:**

| Capa | Marítimo | Aviación | Trucking | Nota |
|---|---|---|---|---|
| `no2` | `0.30` | `0.10` | `0.20` | Señal de saturación vial en trucking |
| `so2` | `0.10` | `0.15` | `0.05` | Casi residual en EE.UU. por ULSD |
| `co` | — | `0.05` | `0.10` | Discriminador de congestión stop-and-go |
| `wind` | `0.20` | `0.35` | `0.05` | Menor impacto en camiones vs barcos/aviones |
| `wave` | `0.15` | — | — | Solo marítimo |
| `traffic/viirs` | `0.15` | — | `0.20` (congestion) | En trucking: mayor peso por impacto directo |
| `slope` | — | — | `0.20` | Solo terrestre — factor crítico de consumo |
| `precip` | — | — | `0.08` | Solo terrestre — seguridad vial |
| `snow` | — | — | `0.07` | Solo terrestre — riesgo de cierre |
| `aod` | — | `0.05` | `0.05` | Calidad del aire |
| `turbulence` | — | `0.15` | — | Solo aviación |
| `contrail` | — | `0.10` | — | Solo aviación |
| `cloud_top` | — | `0.10` | — | Solo aviación |
| `temperature` | — | — | Informativa | Sin peso directo en trucking |

### 8.2 `normalization` — Rangos de normalización por capa

| Capa | Min | Max | Unidad | Nota |
|---|---|---|---|---|
| `no2` | `0` | `0.0003` | `mol/m²` | |
| `so2` | `0` | `0.0001` | `mol/m²` | |
| `co` | `0` | `0.05` | `mol/m²` | |
| `slope` | `0` | `15` | `grados` | Máximo de 15° — pendiente extrema de montaña |
| `congestion` | `0` | `60` | `nW/cm²/sr` | Valores VIIRS > 60 se truncan (ruido urbano) |
| `wind` | `0` | `15` | `m/s` | Mayor velocidad = mayor resistencia aerodinámica |
| `precip` | `0` | `5` | `mm/hr` | Lluvia intensa |
| `snow` | `0` | `100` | `NDSI 0–100` | |
| `aod` | `0` | `1` | `adimensional` | Escala física después de dividir por 256 |

> **Nota sobre wind en trucking:** A diferencia del modo aviación donde viento alto es **favorable** (viento de cola), en trucking el viento se normaliza como **costo creciente** — mayor velocidad del viento, mayor resistencia aerodinámica en el camión. No hay inversión de lógica.

### 8.3 `badge_thresholds` — Umbrales de certificación

| Badge | Condición | Acción recomendada |
|---|---|---|
| `GREEN` | `score ≥ 65` | Ruta óptima — condiciones favorables para el corredor |
| `WARN` | `45 ≤ score < 65` | Evaluar segmentos de congestión o clima adverso |
| `RED` | `score < 45` | Rerouting obligatorio — combinación de factores adversos severos |

> **Contexto operacional:** Con un score medio de `82.0` y el 99.2% de celdas en GREEN, este corredor en P1 de marzo está en condiciones óptimas. El CertificationJudge no debe emitir RED a menos que exista una combinación simultánea de: `snow_cover > 40` + `precip > 1.5 mm/hr` + `congestion VIIRS > 50 nW` en el mismo segmento. Un WARN aislado por congestión en el NJ Turnpike es la condición base esperada y no requiere rerouting.

---

## 9. Estructura del campo `data` en cada capa

Todas las capas en `layers.*`, `static_layers.*` y `derived_layers.*` usan la misma estructura de matriz:

```
data[row][col]  →  valor de la celda en fila=row, columna=col

- row: 0..199  (norte a sur, row=0 = lat 41.475°N)
- col: 0..179  (oeste a este, col=0 = lon −82.475°W)
- Celdas sin carretera (road_mask = 0): valor null
- Celdas con carretera (road_mask = 1): valor float de la capa
- Celdas con road_mask = 1 pero sin cobertura satelital: null puntual
```

**Fórmula de conversión índice → coordenadas:**

```python
lat = 41.5 - (row * 0.05) - 0.025   # centro de la celda
lon = -82.5 + (col * 0.05) + 0.025  # centro de la celda
```

**Capas con cobertura parcial (null en celdas viales):**

| Capa | Valid cells | Cobertura sobre road_cells | Razón de gaps |
|---|---|---|---|
| `so2_mol_m2` | `10,018` | `56.8%` | Nubosidad Sentinel-5P — resolución limitada |
| `aod` | `14,574` | `82.5%` | Resolución nativa MODIS ~1° > celda 0.05° |
| `snow_cover` | `17,615` | `99.8%` | Gaps MODIS en bordes de tile |
| `temperature_k` | `17,327` | `98.2%` | Gaps ERA5-Land en celdas limítrofes del bounding box |
| Resto de capas | `17,651` | `100%` | Cobertura completa sobre road_cells |

---

## 10. Resumen de fuentes de datos

| Capa | Satélite / Modelo | Colección GEE | Resolución nativa | Frecuencia |
|---|---|---|---|---|
| `no2_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_NO2` | ~3.5 km | Diario |
| `so2_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_SO2` | ~3.5 km | Diario |
| `co_mol_m2` | Sentinel-5P TROPOMI | `COPERNICUS/S5P/OFFL/L3_CO` | ~7 km | Diario |
| `temperature_k` | ERA5-Land | `ECMWF/ERA5_LAND/HOURLY` | ~9 km | Horario |
| `wind_u_ms` / `wind_v_ms` | NOAA GFS | `NOAA/GFS0P25` | ~28 km | 6-horario |
| `viirs_nw` | VIIRS DNB | `NOAA/VIIRS/DNB/MONTHLY_V1/VCMSLCFG` | ~500 m | Mensual |
| `precip_mm` | NASA GPM IMERG | `NASA/GPM_L3/IMERG_V07` | ~11 km | 30 min |
| `snow_cover` | MODIS Terra | `MODIS/061/MOD10A1` | ~500 m | Diario |
| `aod` | MODIS Terra | `MODIS/061/MOD08_M3` | ~1° | Mensual |
| `elevation_m` | USGS SRTM | `CGIAR/SRTM90_V4` | ~30 m | Estático |
| `slope_deg` | Derivado de SRTM | `ee.Terrain.slope()` | ~30 m | Estático |
| `green_score` | Calculado | — | ~5.6 km | Por ejecución |
| `road_mask` | U.S. Census TIGER | `TIGER/2016/Roads` | Vectorial | Estático |

---

## 11. Consideraciones de riesgo específicas del modo trucking

### Congestión estructural en el NJ Turnpike e I-95 Norte
Los tramos de la I-95 entre Newark y Baltimore presentan VIIRS alto de forma estructural (> 40 nW/cm²/sr), con NO2 y CO correlacionados. Esta congestión es predecible y no debe interpretarse como anomalía — es la condición base del corredor. El CertificationJudge debe establecer baselines específicos para estos segmentos, análogos al `check_baseline_history` del corredor marítimo.

### Paso montañoso de los Apalaches (Virginia / Carolina del Norte)
Las celdas con `slope_deg ≥ 4°` entre las filas ~95–130 del grid (latitudes ~36.5°N–38.0°N) corresponden a los pasos de la I-77 (Fancy Gap) y la I-81 (Shenandoah Valley). En marzo, pueden coincidir `snow_cover > 20` + `precip > 0.5 mm/hr` + `slope ≥ 4°` — la combinación de mayor riesgo de este corredor. El CorridorOptimizer debe evaluar la ruta alternativa costera (I-95 directa) frente a la ruta interior (I-81 + I-77) cuando estas condiciones se presentan simultáneamente.

### Nieve residual en New Jersey y Delaware (marzo)
El segmento norte del corredor (rows ~0–35, lat ~40°N–41.5°N) puede presentar `snow_cover > 20` en marzo tras eventos de nieve tardía. Verificar siempre `snow_cover` en el área NY/NJ antes de ejecutar el pathfinding — si > 30 en más de 5 celdas consecutivas de la ruta, emitir WARN preventivo.

### AOD con escala interna MODIS sin normalizar
El campo `aod` en `layers` contiene valores en escala interna MODIS (0–256), **no** en escala física AOD (0.0–1.0). El CorridorOptimizer y el SatelliteAnalyst deben dividir por 256 antes de cualquier comparación con umbrales físicos o con datos de otras fuentes. No asumir que el valor 84 significa AOD = 0.84 — significa AOD ≈ 0.33.

### Resolución de wind GFS vs celda de 5.6 km
El modelo GFS tiene resolución nativa de ~28 km, remuestreada a celdas de 5.6 km. Los valores de `wind_u_ms` y `wind_v_ms` son prácticamente uniformes entre celdas adyacentes — no reflejan variabilidad local del viento (efectos de canalización en valles, exposición en crestas). El CorridorOptimizer no debe usar el viento para discriminar entre rutas separadas por menos de 30 km.
