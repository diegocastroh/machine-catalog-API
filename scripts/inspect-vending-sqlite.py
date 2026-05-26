#!/usr/bin/env python
"""Inspect the Colab SQLite vending database before importing it."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Show counts and duplicate patterns in vending_api_data.db.")
    parser.add_argument("--db", default=r"C:\Users\diego\Downloads\vending_api_data.db")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"No existe la base SQLite: {db_path}")
        return 2

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    tables = [
        row["name"]
        for row in connection.execute("select name from sqlite_master where type='table' order by name")
    ]
    if "catalogo_vending" not in tables:
        print("No existe la tabla catalogo_vending.")
        return 2

    rows = list(
        connection.execute(
            """
            select id, fabricante, modelo, url_oficial, tipo_maquina, imagen_url, timestamp
            from catalogo_vending
            order by id
            """
        )
    )

    duplicate_keys = Counter(
        (
            (row["fabricante"] or "").strip().lower(),
            (row["modelo"] or "").strip().lower(),
            (row["url_oficial"] or "").strip().lower(),
        )
        for row in rows
    )
    duplicate_count = sum(count - 1 for count in duplicate_keys.values() if count > 1)
    by_manufacturer = Counter((row["fabricante"] or "SIN FABRICANTE").strip() for row in rows)
    by_type = Counter((row["tipo_maquina"] or "SIN TIPO").strip() for row in rows)

    summary = {
        "db": str(db_path),
        "tables": tables,
        "total_rows": len(rows),
        "min_id": min((row["id"] for row in rows), default=None),
        "max_id": max((row["id"] for row in rows), default=None),
        "duplicate_exact_rows": duplicate_count,
        "manufacturers": len(by_manufacturer),
        "top_manufacturers": by_manufacturer.most_common(20),
        "types": by_type.most_common(),
        "first_rows": [dict(row) for row in rows[:5]],
        "last_rows": [dict(row) for row in rows[-5:]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
