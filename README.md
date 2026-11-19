# Firmware Config Compiler

Compile one strict JSON settings schema into a bounded C11 struct, defaults function, validator, and a JSON defaults file for host tools. Generated C uses fixed-size storage and has no heap allocation.

## Run

Use Python 3.11 or newer. Install with pip install .; run the compiler with python -m firmware_config_compiler examples/weather_node.json --out build/generated. Run the Python test suite with python -m unittest discover -s tests -v.

Use --check-from old-schema.json to compare against a prior version. Any setting change requires a greater schema_version. The comparison reports additions, removals, type changes, range changes, default changes, string-length changes, and enum changes.

## Schema types

Supported settings are bool, int32, uint32, bounded ASCII string, and enum. Numeric types require min and max. Strings reserve one extra byte for a terminating NUL. The compiler rejects duplicate fields, invalid C identifiers, out-of-range defaults, unknown properties, and unsupported values before writing output.

## Output

The generated header and source define firmware_config_set_defaults and firmware_config_validate. Include the header in a C11 project and call the validator after loading configuration from flash or a transport. The JSON defaults file can seed a manufacturing tool or host-side test.

CI compiles generated code with warnings treated as errors and runs a small C smoke test. The local unit suite validates schema checks and output behavior; it does not require a local C compiler.

## Scope

This is an initial code generator, not a wire protocol, flash-storage driver, or automatic firmware migration engine. Cross-device version migration remains an application decision informed by the schema comparison.

MIT licensed. See LICENSE.
