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

Reanudar:

```powershell
python scripts/scrape_csv_to_supabase.py --csv C:\Users\diego\Downloads\vending-machines-formateado.csv --start-row 434
```

## Comportamiento de duplicados

Por defecto usa `--mode update`: si ya existe el mismo fabricante/modelo, actualiza specs, URL e imagen sin crear duplicados.

Para omitir existentes:

```powershell
python scripts/scrape_csv_to_supabase.py --mode skip
```

No elimina datos existentes.
