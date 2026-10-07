"""Generate the frontend's response types from FastAPI OpenAPI schemas."""

from pathlib import Path

from prism.main import app

TARGET = Path(__file__).resolve().parents[2] / "web/src/lib/api-types.ts"
NAMES = (
    "Video",
    "SearchResult",
    "VideoResult",
    "SearchResponse",
    "VisualQueryResult",
    "VisualQueryResponse",
    "CollectionItem",
    "Collection",
)


def ts_type(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in schema:
        return " | ".join(ts_type(item) for item in schema["anyOf"])
    if "enum" in schema:
        return " | ".join(repr(item).replace("'", '"') for item in schema["enum"])
    kind = schema.get("type")
    if kind == "array":
        return f"Array<{ts_type(schema['items'])}>"
    return {
        "string": "string",
        "number": "number",
        "integer": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


def main() -> None:
    schemas = app.openapi()["components"]["schemas"]
    lines = ["// Generated from FastAPI OpenAPI. Run: python -m prism.generate_api_types", ""]
    for name in NAMES:
        schema = schemas[name]
        required = set(schema.get("required", []))
        lines.append(f"export type {name} = {{")
        for field, value in schema["properties"].items():
            optional = "" if field in required else "?"
            lines.append(f"  {field}{optional}: {ts_type(value)};")
        lines.extend(["};", ""])
    TARGET.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
