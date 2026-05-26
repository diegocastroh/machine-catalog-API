# Direct Supabase CSV Pipeline

Este pipeline lee `vending-machines-formateado.csv`, extrae datos con Firecrawl si hay clave disponible y guarda directamente en Supabase.

## Instalacion local

```powershell
python -m pip install -r scripts/requirements-supabase-pipeline.txt
python -m playwright install chromium
```

Variables esperadas en `.env`:

```text
SUPABASE_URL=https://yptzopnarugsoighqnph.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
SERPER_API_KEY=...
FIRECRAWL_API_KEY=...
```

`SERPER_API_KEY` solo se usa si la columna `URL` viene vacia. `FIRECRAWL_API_KEY` activa extraccion estructurada; si falta, el script usa extraccion HTML basica.

## Extractores

Firecrawl:

```powershell
python scripts/scrape_csv_to_supabase.py --extractor firecrawl
```

Crawl4AI local y gratuito:

```powershell
python scripts/scrape_csv_to_supabase.py --extractor crawl4ai
```

HTML basico sin navegador:

```powershell
python scripts/scrape_csv_to_supabase.py --extractor basic
```

## Ejecutar

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --start-row 1
```

Modo prueba:

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --start-row 1 --limit 5 --dry-run
```

Ver outputs de cada extraccion sin guardar:

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1 --limit 5 --dry-run --verbose
```

El modo verbose muestra URL resuelta, imagen, categoria, specs detectadas, extracto relevante y score de calidad. Ese score ayuda a detectar paginas genericas, resultados sin imagen, sin specs o donde no aparece el modelo.

Ejecutar con control de calidad:

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --start-row 1 --limit 50 --verbose --min-quality 0.45 --review-below-quality 0.70
```

Con `--min-quality`, el script no guarda filas debajo del umbral. Con `--review-below-quality`, las filas guardadas debajo del umbral quedan como `pending_review`; por encima quedan `approved`.

Ejecutar Crawl4AI con IA local en todas las filas:

```powershell
ollama pull qwen2.5:7b-instruct
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --extractor crawl4ai --ai-mode always --ai-model qwen2.5:7b-instruct --start-row 1 --limit 20 --verbose --review-below-quality 0.85
```

La IA local no reemplaza la extraccion por reglas: la complementa. Si encuentra campos que faltan, los agrega. Si contradice datos ya detectados por reglas, conserva el dato deterministico, agrega `ai_conflict:*` en warnings y baja la confianza para que el modelo quede en revision.

Flags de IA:

- `--ai-mode off`: no usa IA.
- `--ai-mode fallback`: usa IA solo cuando el score por reglas esta debajo de `--ai-fallback-below-quality`.
- `--ai-mode always`: usa IA en todas las filas.
- `--ai-provider ollama`: proveedor local soportado.
- `--ai-model`: modelo instalado en Ollama.
- `--ai-base-url`: endpoint local de Ollama, por defecto `http://localhost:11434`.
- `--ai-timeout`: timeout por fila para la llamada IA.
- `--ai-max-chars`: maximo de caracteres enviados al modelo por fila.
- `--ai-num-ctx`: ventana de contexto de Ollama; usa `4096` o `8192` para reducir presion de VRAM/RAM.

Reanudar:

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --start-row 434
```

## Crawl4AI mejorado

El extractor local combina el markdown renderizado por navegador con el HTML visible, limpia banners de cookies, normaliza URLs de imagen, resuelve paginas genericas hacia paginas de producto cuando puede y aplica reglas especificas para fabricantes con estructuras especiales.

Casos cubiertos:

- Rheavendors: una URL de coleccion o categoria puede resolverse a la pagina concreta del modelo.
- Sielaff SiLine Public Series: variantes como `SiLine GF L RP` se resuelven a la pagina de serie y se leen specs de las secciones inferiores.
- Sitios con banners de cookies: se filtran textos de consentimiento para que no terminen como descripcion principal.
- Imagenes: se priorizan JPG/PNG/WebP de producto y se descartan logos, favicons, iconos sociales y placeholders.

## Comportamiento de duplicados

Por defecto usa `--mode update`: si ya existe el mismo fabricante/modelo, actualiza specs, URL e imagen sin crear duplicados.

Para omitir existentes:

```powershell
python scripts/scrape_csv_to_supabase.py --mode skip
```

No elimina datos existentes.
