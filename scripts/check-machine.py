#!/usr/bin/env python
"""Check whether a machine model exists in the local Machine Catalog API."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.parse import urljoin

import requests


def request_json(base_url: str, path: str, params: dict[str, str | int | None] | None = None) -> dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    response = requests.get(url, params={k: v for k, v in (params or {}).items() if v is not None}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success", False):
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def print_match(item: dict[str, Any]) -> None:
    print("-" * 80)
    print(f"ID:           {item.get('id')}")
    print(f"Modelo:       {item.get('model_name')}")
    print(f"Fabricante:   {item.get('manufacturer_name')}")
    print(f"Categoria:    {item.get('primary_category_code')}")
    print(f"Confianza:    {item.get('confidence_score')}")
    print(f"URL fuente:   {item.get('source_url')}")


def print_detail(detail: dict[str, Any]) -> None:
    print("\nDetalle del primer resultado")
    print("-" * 80)
    for key in (
        "id",
        "model_name",
        "normalized_model_name",
        "manufacturer_name",
        "primary_category_code",
        "status",
        "confidence_score",
        "source_url",
        "description",
    ):
        value = detail.get(key)
        if value is not None:
            print(f"{key}: {value}")

    specs = detail.get("specifications")
    if specs:
        print("\nEspecificaciones:")
        print(json.dumps(specs, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search a machine model in the local Machine Catalog API.",
    )
    parser.add_argument("query", nargs="+", help="Machine/model text to search, for example: Barista 600")
    parser.add_argument("--base-url", default="http://localhost:3000", help="Local API base URL")
    parser.add_argument("--category", default=None, help="Optional category filter, for example: coffee")
    parser.add_argument("--limit", type=int, default=10, help="Maximum matches to print")
    parser.add_argument("--detail", action="store_true", help="Fetch detail for the first match")
    args = parser.parse_args()

    query = " ".join(args.query).strip()
    if not query:
        parser.error("query is required")

    try:
        payload = request_json(
            args.base_url,
            "/api/v1/catalog/search",
            {"q": query, "category": args.category},
        )
    except requests.ConnectionError:
        print(
            f"No pude conectar con {args.base_url}. Levanta la API con: npm run dev",
            file=sys.stderr,
        )
        return 2
    except requests.HTTPError as exc:
        print(f"La API respondio con error HTTP: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error consultando la API: {exc}", file=sys.stderr)
        return 2

    matches = payload.get("data", [])
    print(f"Consulta: {query}")
    print(f"Coincidencias encontradas: {len(matches)}")

    if not matches:
        print("Resultado: no existe una maquina publicada que coincida con esa busqueda.")
        return 1

    print("Resultado: existe al menos una maquina publicada que coincide.")
    for item in matches[: args.limit]:
        print_match(item)

    if args.detail:
        first_id = matches[0].get("id")
        if first_id:
            detail_payload = request_json(args.base_url, f"/api/v1/catalog/machine-models/{first_id}")
            print_detail(detail_payload.get("data", {}))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
