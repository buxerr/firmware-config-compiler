from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .compiler import ConfigSchema, SchemaError, compare_schemas, generate_files, parse_schema


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SchemaError("duplicate JSON field: " + key)
        result[key] = value
    return result


def _load_schema(path: Path) -> ConfigSchema:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SchemaError("could not read valid JSON from " + str(path)) from error
    return parse_schema(value)


def _write_outputs(directory: Path, files: dict[str, str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    try:
        for name, content in files.items():
            target = directory / name
            descriptor, temporary_name = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=directory)
            temporary = Path(temporary_name)
            staged.append((temporary, target))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        for temporary, target in staged:
            os.replace(temporary, target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile one bounded firmware settings schema into C and host defaults.")
    parser.add_argument("schema", type=Path, help="input schema JSON")
    parser.add_argument("--out", required=True, type=Path, help="output directory")
    parser.add_argument("--check-from", type=Path, help="previous schema JSON to compare for migration safety")
    args = parser.parse_args(argv)
    try:
        schema = _load_schema(args.schema)
        if args.check_from is not None:
            previous = _load_schema(args.check_from)
            changes = compare_schemas(previous, schema)
            if changes and schema.version <= previous.version:
                raise SchemaError("schema changes require a schema_version greater than " + str(previous.version))
            for change in changes:
                print(change["severity"] + ": " + change["kind"] + " setting " + change["setting"])
        _write_outputs(args.out, generate_files(schema))
    except (SchemaError, OSError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
