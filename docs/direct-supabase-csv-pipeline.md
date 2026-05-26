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
