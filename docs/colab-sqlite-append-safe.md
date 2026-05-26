# Colab SQLite Append Safe

El script de Colab que genera `vending_api_data.db` no borra la tabla porque usa:

```python
CREATE TABLE IF NOT EXISTS catalogo_vending (...)
```

Eso conserva la base existente. La cantidad final puede ser menor a la esperada por estas razones:

- `START_ROW = 434` omite todas las filas anteriores del CSV.
- `RUN_LIMIT` limita filas si no esta en `None`.
- `SKIP_ALREADY_SAVED = True` evita guardar otra vez la misma combinacion `fabricante + modelo + url_oficial`.
- Si Serper no encuentra URL o Firecrawl no devuelve JSON valido, la fila no se guarda.
- El script solo inserta al final cuando `scrape_with_firecrawl()` devuelve datos validos.

Para procesar todo desde el inicio y seguir acumulando nuevos registros:

```python
START_ROW = 1
RUN_LIMIT = None
SKIP_ALREADY_SAVED = True
```

No cambies `CREATE TABLE IF NOT EXISTS` por `DROP TABLE` ni elimines el archivo `.db`.

Si quieres permitir duplicados exactos en SQLite, usa:

```python
SKIP_ALREADY_SAVED = False
```

No se recomienda para el catalogo productivo, porque Supabase mantiene unicidad por fabricante/modelo para evitar duplicados visibles en la API publica.

Diagnostico local:

```powershell
python scripts/inspect-vending-sqlite.py --db C:\Users\diego\Downloads\vending_api_data.db
```

Importar nuevos registros sin borrar nada:

```powershell
python scripts/import-vending-sqlite.py --db C:\Users\diego\Downloads\vending_api_data.db --base-url http://localhost:3000
```
