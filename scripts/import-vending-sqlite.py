#!/usr/bin/env python
"""Import Colab SQLite vending data into the Machine Catalog API."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen


CATEGORY_MAP = {
    "coffee": "coffee",
    "snack": "snack_drink",
    "combo": "snack_drink",
    "drink": "cold_beverage",
    "beverage": "cold_beverage",
    "frozen": "ice_cream",
    "locker": "smart_locker",
    "industrial": "industrial",
}


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request_json(
    method: str,
    base_url: str,
    path: str,
    admin_api_key: str,
    payload: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode(params)}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "content-type": "application/json",
            "x-admin-api-key": admin_api_key,
        },
    )
    try:
        with urlopen(request, timeout=45) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc
    result = json.loads(body)
    if not result.get("success"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def public_request_json(base_url: str, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode(params)}"
    with urlopen(Request(url, method="GET"), timeout=45) as response:
        body = response.read().decode("utf-8")
    result = json.loads(body)
    if not result.get("success"):
        raise RuntimeError(json.dumps(result, ensure_ascii=False))
    return result


def normalize_slug(value: str) -> str:
    chars = [c.lower() if c.isalnum() else "-" for c in value.strip()]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "unknown"


def category_for(tipo: str | None, model_name: str, specs: dict[str, Any]) -> str:
    tipo_normalized = (tipo or "").strip().lower()
    if tipo_normalized == "food":
        text = f"{model_name} {json.dumps(specs, ensure_ascii=False)}".lower()
        return "hot_food" if "hot" in text or "heated" in text else "fresh_food"
    return CATEGORY_MAP.get(tipo_normalized, "other")


def description_for(specs: dict[str, Any]) -> str | None:
    parts = []
    versions = specs.get("versiones_disponibles") or []
    if versions:
        parts.append("Versiones: " + ", ".join(str(v) for v in versions[:5]))
    hardware = specs.get("componentes_hardware") or {}
    extraction = hardware.get("mecanica_extraccion")
    if extraction:
        parts.append(f"Mecanica: {extraction}")
    channels = hardware.get("capacidad_canales_o_espirales")
    if channels:
        parts.append(f"Capacidad: {channels}")
    return ". ".join(parts) if parts else None


def load_rows(db_path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    rows = []
    for row in connection.execute(
        """
        select id, fabricante, modelo, url_oficial, tipo_maquina, imagen_url, datos_json, timestamp
        from catalogo_vending
        order by id
        """
    ):
        item = dict(row)
        try:
            item["datos"] = json.loads(item.pop("datos_json") or "{}")
        except json.JSONDecodeError:
            item["datos"] = {}
        rows.append(item)
    connection.close()
    return rows


def find_manufacturer(base_url: str, admin_api_key: str, name: str) -> dict[str, Any] | None:
    result = request_json("GET", base_url, "/api/v1/catalog/manufacturers", admin_api_key, params={"q": name})
    slug = normalize_slug(name)
    for item in result["data"]:
        if item.get("slug") == slug or item.get("name", "").strip().lower() == name.strip().lower():
            return item
    return None


def ensure_manufacturer(base_url: str, admin_api_key: str, name: str) -> dict[str, Any]:
    existing = find_manufacturer(base_url, admin_api_key, name)
    if existing:
        return existing
    return request_json(
        "POST",
        base_url,
        "/api/v1/admin/catalog/manufacturers",
        admin_api_key,
        {
            "name": name,
            "slug": normalize_slug(name),
            "status": "active",
            "source_confidence": 0.9,
        },
    )["data"]


def model_exists(base_url: str, admin_api_key: str, manufacturer_id: str, model_name: str) -> bool:
    result = request_json(
        "GET",
        base_url,
        "/api/v1/admin/catalog/machine-models",
        admin_api_key,
        params={"q": model_name},
    )
    wanted = model_name.strip().lower()
    return any(
        item.get("manufacturer_id") == manufacturer_id and item.get("model_name", "").strip().lower() == wanted
        for item in result["data"]
    )


def import_row(base_url: str, admin_api_key: str, row: dict[str, Any], dry_run: bool) -> str:
    manufacturer_name = (row.get("fabricante") or "").strip()
    model_name = (row.get("modelo") or "").strip()
    if not manufacturer_name or not model_name:
        return "skipped_incomplete"

    specs = row.get("datos") or {}
    category_code = category_for(row.get("tipo_maquina"), model_name, specs)
    if dry_run:
        return "dry_run"

    manufacturer = ensure_manufacturer(base_url, admin_api_key, manufacturer_name)
    if model_exists(base_url, admin_api_key, manufacturer["id"], model_name):
        return "skipped_duplicate"

    model = request_json(
        "POST",
        base_url,
        "/api/v1/admin/catalog/machine-models",
        admin_api_key,
        {
            "manufacturer_id": manufacturer["id"],
            "model_name": model_name,
            "category_code": category_code,
            "status": "approved",
            "lifecycle_status": "unknown",
            "source_url": row.get("url_oficial") or None,
            "official_product_url": row.get("url_oficial") or None,
            "short_description": description_for(specs),
            "confidence_score": 0.82,
            "specs": {
                **specs,
                "_import": {
                    "source": "colab_firecrawl_sqlite",
                    "sqlite_id": row.get("id"),
                    "timestamp": row.get("timestamp"),
                },
            },
        },
    )["data"]

    image_url = row.get("imagen_url")
    if image_url:
        try:
            request_json(
                "POST",
                base_url,
                f"/api/v1/admin/catalog/machine-models/{model['id']}/images",
                admin_api_key,
                {
                    "source_image_url": image_url,
                    "source_page_url": row.get("url_oficial") or None,
                    "image_type": "front_photo",
                    "alt_text": f"{manufacturer_name} {model_name}",
                    "is_primary": True,
                    "is_official": True,
                    "license_status": "official_reference_only",
                },
            )
        except Exception:
            return "created_without_image"

    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import vending_api_data.db into Machine Catalog API.")
    parser.add_argument("--db", default=r"C:\Users\diego\Downloads\vending_api_data.db")
    parser.add_argument("--base-url", default=os.environ.get("CATALOG_API_URL", "http://localhost:3000"))
    parser.add_argument("--admin-api-key", default=os.environ.get("ADMIN_API_KEY"))
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--from-id", type=int, default=None)
    parser.add_argument("--to-id", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env_values = load_dotenv(Path(args.env_file))
    admin_api_key = args.admin_api_key or env_values.get("ADMIN_API_KEY")
    if not admin_api_key:
        print("Falta ADMIN_API_KEY. Pasalo con --admin-api-key o dejalo en .env.", file=sys.stderr)
        return 2

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"No existe la base SQLite: {db_path}", file=sys.stderr)
        return 2

    try:
        public_request_json(args.base_url, "/health")
    except (HTTPError, URLError, TimeoutError) as exc:
        print(f"No pude conectar con la API en {args.base_url}: {exc}", file=sys.stderr)
        return 2

    counters: dict[str, int] = {}
    rows = load_rows(db_path)
    if args.from_id is not None:
        rows = [row for row in rows if int(row["id"]) >= args.from_id]
    if args.to_id is not None:
        rows = [row for row in rows if int(row["id"]) <= args.to_id]

    for row in rows:
        try:
            status = import_row(args.base_url, admin_api_key, row, args.dry_run)
        except Exception as exc:
            status = "failed"
            print(f"[{row.get('id')}] {row.get('fabricante')} / {row.get('modelo')}: {exc}", file=sys.stderr)
        counters[status] = counters.get(status, 0) + 1
        print(f"[{row.get('id')}] {row.get('fabricante')} / {row.get('modelo')} -> {status}")

    print(json.dumps(counters, ensure_ascii=False, indent=2))
    return 0 if counters.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
