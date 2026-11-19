from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from firmware_config_compiler import SchemaError, compare_schemas, generate_files, parse_schema
from firmware_config_compiler.cli import main


def sample_schema() -> dict:
    return {
        "schema_version": 2,
        "device": "sensor_node",
        "settings": [
            {"name": "enabled", "type": "bool", "default": True},
            {"name": "delta", "type": "int32", "default": -4, "min": -10, "max": 10},
            {"name": "sample_ms", "type": "uint32", "default": 100, "min": 1, "max": 1000},
            {"name": "label", "type": "string", "default": 'node "a"', "max_length": 24},
            {"name": "mode", "type": "enum", "default": "safe", "values": ["safe", "fast"]},
        ],
    }


class CompilerTests(unittest.TestCase):
    def test_generates_bounded_static_c_and_host_defaults_deterministically(self) -> None:
        schema = parse_schema(sample_schema())
        first = generate_files(schema)
        second = generate_files(schema)
        self.assertEqual(first, second)
        self.assertIn("char label[25];", first["firmware_config.h"])
        self.assertIn("FIRMWARE_CONFIG_MODE_FAST = 1", first["firmware_config.h"])
        self.assertIn('memcpy(out->label, "node \\"a\\"", 8U);', first["firmware_config.c"])
        self.assertIn("character < 0x20U || character > 0x7EU", first["firmware_config.c"])
        self.assertIn("config->sample_ms > UINT32_C(1000)", first["firmware_config.c"])
        self.assertEqual(json.loads(first["defaults.json"])["mode"], "safe")
        for forbidden in ("malloc(", "calloc(", "realloc(", "free("):
            self.assertNotIn(forbidden, first["firmware_config.c"])

    def test_validates_defaults_and_runtime_values(self) -> None:
        schema = parse_schema(sample_schema())
        values = schema.defaults()
        schema.validate_values(values)
        values["sample_ms"] = 1001
        with self.assertRaises(SchemaError):
            schema.validate_values(values)
        with self.assertRaises(SchemaError):
            schema.validate_values({1: "non-string key"})

    def test_rejects_schema_shape_duplicates_and_keyword_names(self) -> None:
        with self.assertRaises(SchemaError):
            parse_schema({**sample_schema(), "surprise": True})
        duplicate = sample_schema()
        duplicate["settings"].append(dict(duplicate["settings"][0]))
        with self.assertRaises(SchemaError):
            parse_schema(duplicate)
        keyword = sample_schema()
        keyword["settings"][0]["name"] = "struct"
        with self.assertRaises(SchemaError):
            parse_schema(keyword)
        colliding_enums = sample_schema()
        colliding_enums["settings"][4]["values"].append("fast_slow")
        colliding_enums["settings"].append({
            "name": "mode_fast",
            "type": "enum",
            "default": "slow",
            "values": ["slow"],
        })
        with self.assertRaises(SchemaError):
            parse_schema(colliding_enums)

    def test_rejects_numeric_overflow_and_invalid_string_defaults(self) -> None:
        bad_integer = sample_schema()
        bad_integer["settings"][2]["max"] = 4_294_967_296
        with self.assertRaises(SchemaError):
            parse_schema(bad_integer)
        bad_string = sample_schema()
        bad_string["settings"][3]["default"] = "not printable\n"
        with self.assertRaises(SchemaError):
            parse_schema(bad_string)
        bool_as_integer = sample_schema()
        bool_as_integer["settings"][2]["default"] = True
        with self.assertRaises(SchemaError):
            parse_schema(bool_as_integer)

    def test_compares_migration_changes(self) -> None:
        previous = parse_schema(sample_schema())
        changed = sample_schema()
        changed["schema_version"] = 3
        changed["settings"][1]["min"] = -5
        changed["settings"].append({"name": "new_flag", "type": "bool", "default": False})
        current = parse_schema(changed)
        differences = compare_schemas(previous, current)
        self.assertEqual([change["kind"] for change in differences], ["added", "range-changed"])
        self.assertEqual(differences[0]["severity"], "migration-needed")

    def test_cli_refuses_unversioned_changes_and_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_schema = root / "old.json"
            new_schema = root / "new.json"
            old_schema.write_text(json.dumps(sample_schema()), encoding="utf-8")
            changed = sample_schema()
            changed["settings"][0]["default"] = False
            new_schema.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                main([str(new_schema), "--out", str(root / "blocked"), "--check-from", str(old_schema)])
            self.assertEqual(error.exception.code, 2)
            changed["schema_version"] = 3
            new_schema.write_text(json.dumps(changed), encoding="utf-8")
            output = root / "generated"
            self.assertEqual(main([str(new_schema), "--out", str(output), "--check-from", str(old_schema)]), 0)
            self.assertEqual({path.name for path in output.iterdir()}, {"firmware_config.h", "firmware_config.c", "defaults.json"})


if __name__ == "__main__":
    unittest.main()
