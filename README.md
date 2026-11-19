# Firmware Configuration Schema Compiler: JSON to Bounded C11

Generate a fixed-size C11 configuration struct, defaults function, validator, and JSON defaults file from one firmware settings schema. The Python compiler keeps device settings in one source of truth and emits static C storage without heap allocation.

Use it when firmware and host-side tools currently duplicate the same setting names, defaults, and value limits.

## Install and compile a schema

Requires Python 3.11 or newer. From a repository checkout:

```sh
git clone https://github.com/buxerr/firmware-config-compiler.git
cd firmware-config-compiler
python -m pip install .
python -m firmware_config_compiler examples/weather_node.json --out build/generated
```

The output directory contains `firmware_config.h`, `firmware_config.c`, and `defaults.json`. Include the generated header in a C11 project, call `firmware_config_set_defaults`, then call `firmware_config_validate` after your application loads settings from flash or a transport.

## Supported setting types

The schema supports `bool`, `int32`, `uint32`, bounded ASCII `string`, and `enum`. Numeric settings require `min` and `max`; strings reserve an extra byte for the terminating NUL. Invalid identifiers, duplicate fields, unsupported properties, and out-of-range defaults are rejected before output is written.

## Check schema compatibility

Compare a schema from your application with its previous version before generating firmware code:

```sh
python -m firmware_config_compiler new_schema.json --out build/generated --check-from old_schema.json
```

Any setting change requires a greater `schema_version`. The comparison reports added or removed settings and changes to types, ranges, defaults, string lengths, and enum values.

The Python test suite runs with `python -m unittest discover -s tests -v`. CI also compiles generated code with warnings treated as errors and runs a small C smoke test.

## Scope and limitations

This is a settings schema compiler, not a wire protocol, flash-storage driver, JSON parser for embedded targets, or automatic firmware migration engine. The application owns serialization and decides how to migrate values between device versions.

## License

MIT. See [LICENSE](LICENSE).
