from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,47}\Z")
_C_KEYWORDS = {
    "auto", "break", "case", "char", "const", "continue", "default", "do", "double",
    "else", "enum", "extern", "float", "for", "goto", "if", "inline", "int", "long",
    "register", "restrict", "return", "short", "signed", "sizeof", "static", "struct",
    "switch", "typedef", "union", "unsigned", "void", "volatile", "while", "_Alignas",
    "_Alignof", "_Atomic", "_Bool", "_Complex", "_Generic", "_Imaginary", "_Noreturn",
    "_Static_assert", "_Thread_local",
}
_TOP_LEVEL_KEYS = {"schema_version", "device", "settings"}
_TYPE_KEYS = {
    "bool": {"name", "type", "default"},
    "int32": {"name", "type", "default", "min", "max"},
    "uint32": {"name", "type", "default", "min", "max"},
    "string": {"name", "type", "default", "max_length"},
    "enum": {"name", "type", "default", "values"},
}


class SchemaError(ValueError):
    """A schema is malformed or cannot be represented safely in C."""


@dataclass(frozen=True)
class Setting:
    name: str
    kind: str
    default: Any
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = None
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConfigSchema:
    version: int
    device: str
    settings: tuple[Setting, ...]

    def defaults(self) -> dict[str, Any]:
        return {setting.name: setting.default for setting in self.settings}

    def validate_values(self, values: Mapping[str, Any]) -> None:
        if not isinstance(values, Mapping):
            raise SchemaError("configuration values must be a mapping")
        if any(not isinstance(key, str) for key in values):
            raise SchemaError("configuration keys must be strings")
        expected = {setting.name for setting in self.settings}
        actual = set(values)
        if actual != expected:
            missing = sorted(expected - actual)
            unknown = sorted(actual - expected)
            raise SchemaError("configuration keys differ; missing=" + repr(missing) + ", unknown=" + repr(unknown))
        for setting in self.settings:
            value = values[setting.name]
            if setting.kind == "bool":
                valid = type(value) is bool
            elif setting.kind in {"int32", "uint32"}:
                valid = type(value) is int and setting.minimum <= value <= setting.maximum
            elif setting.kind == "string":
                valid = (
                    isinstance(value, str)
                    and value.isascii()
                    and all(0x20 <= ord(character) <= 0x7E for character in value)
                    and len(value) <= setting.max_length
                )
            else:
                valid = isinstance(value, str) and value in setting.values
            if not valid:
                raise SchemaError("invalid value for setting " + setting.name)


def parse_schema(value: Any) -> ConfigSchema:
    if not isinstance(value, dict) or set(value) != _TOP_LEVEL_KEYS:
        raise SchemaError("schema must contain exactly schema_version, device, and settings")
    version = value["schema_version"]
    if type(version) is not int or not 1 <= version <= 2_147_483_647:
        raise SchemaError("schema_version must be an integer from 1 to INT32_MAX")
    device = value["device"]
    if not isinstance(device, str) or not _valid_identifier(device):
        raise SchemaError("device must be a lowercase C identifier")
    raw_settings = value["settings"]
    if not isinstance(raw_settings, list) or not 1 <= len(raw_settings) <= 128:
        raise SchemaError("settings must contain between 1 and 128 entries")

    settings: list[Setting] = []
    seen: set[str] = set()
    for raw in raw_settings:
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            raise SchemaError("each setting must be an object with a type")
        kind = raw["type"]
        if kind not in _TYPE_KEYS or set(raw) != _TYPE_KEYS[kind]:
            raise SchemaError("setting has unknown fields or an unsupported type")
        name = raw["name"]
        if not isinstance(name, str) or not _valid_identifier(name):
            raise SchemaError("setting names must be lowercase C identifiers")
        if name in seen:
            raise SchemaError("duplicate setting name: " + name)
        seen.add(name)
        setting = _parse_setting(name, kind, raw)
        settings.append(setting)

    symbols: set[str] = set()
    for setting in settings:
        if setting.kind != "enum":
            continue
        for item in setting.values:
            symbol = "FIRMWARE_CONFIG_" + setting.name.upper() + "_" + item.upper()
            if symbol in symbols:
                raise SchemaError("enum settings generate a duplicate C symbol: " + symbol)
            symbols.add(symbol)

    return ConfigSchema(version=version, device=device, settings=tuple(settings))


def _parse_setting(name: str, kind: str, raw: dict[str, Any]) -> Setting:
    default = raw["default"]
    if kind == "bool":
        if type(default) is not bool:
            raise SchemaError("bool default must be true or false")
        return Setting(name, kind, default)
    if kind in {"int32", "uint32"}:
        lower, upper = (-2_147_483_648, 2_147_483_647) if kind == "int32" else (0, 4_294_967_295)
        minimum, maximum = raw["min"], raw["max"]
        if type(minimum) is not int or type(maximum) is not int or minimum > maximum:
            raise SchemaError("numeric min and max must be ordered integers")
        if minimum < lower or maximum > upper:
            raise SchemaError(kind + " range is outside its C type bounds")
        if type(default) is not int or not minimum <= default <= maximum:
            raise SchemaError("numeric default must fit within min and max")
        return Setting(name, kind, default, minimum=minimum, maximum=maximum)
    if kind == "string":
        maximum = raw["max_length"]
        if type(maximum) is not int or not 1 <= maximum <= 255:
            raise SchemaError("string max_length must be from 1 to 255")
        if (
            not isinstance(default, str)
            or not default.isascii()
            or any(ord(character) < 0x20 or ord(character) > 0x7E for character in default)
            or len(default) > maximum
        ):
            raise SchemaError("string default must be printable ASCII within max_length")
        return Setting(name, kind, default, max_length=maximum)
    values = raw["values"]
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 32
        or any(not isinstance(item, str) or not _valid_identifier(item) for item in values)
        or len(set(values)) != len(values)
        or not isinstance(default, str)
        or default not in values
    ):
        raise SchemaError("enum values must be unique C identifiers and include the default")
    return Setting(name, kind, default, values=tuple(values))


def _valid_identifier(value: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(value)) and value not in _C_KEYWORDS


def compare_schemas(previous: ConfigSchema, current: ConfigSchema) -> list[dict[str, str]]:
    old = {setting.name: setting for setting in previous.settings}
    new = {setting.name: setting for setting in current.settings}
    changes: list[dict[str, str]] = []
    for name in sorted(old.keys() - new.keys()):
        changes.append({"setting": name, "kind": "removed", "severity": "breaking"})
    for name in sorted(new.keys() - old.keys()):
        changes.append({"setting": name, "kind": "added", "severity": "migration-needed"})
    for name in sorted(old.keys() & new.keys()):
        before, after = old[name], new[name]
        if before.kind != after.kind:
            changes.append({"setting": name, "kind": "type-changed", "severity": "breaking"})
            continue
        if before.default != after.default:
            changes.append({"setting": name, "kind": "default-changed", "severity": "migration-needed"})
        if before.kind in {"int32", "uint32"} and (
            before.minimum != after.minimum or before.maximum != after.maximum
        ):
            changes.append({"setting": name, "kind": "range-changed", "severity": "migration-needed"})
        if before.kind == "string" and before.max_length != after.max_length:
            changes.append({"setting": name, "kind": "length-changed", "severity": "migration-needed"})
        if before.kind == "enum" and before.values != after.values:
            removed = set(before.values) - set(after.values)
            changes.append({
                "setting": name,
                "kind": "enum-values-removed" if removed else "enum-values-added",
                "severity": "breaking" if removed else "migration-needed",
            })
    return changes


def generate_files(schema: ConfigSchema) -> dict[str, str]:
    return {
        "firmware_config.h": _generate_header(schema),
        "firmware_config.c": _generate_source(schema),
        "defaults.json": json.dumps(schema.defaults(), ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    }


def _macro_name(name: str) -> str:
    return name.upper()


def _c_literal(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _integer_literal(setting: Setting, value: int) -> str:
    if setting.kind == "uint32":
        return "UINT32_C(" + str(value) + ")"
    if value == -2_147_483_648:
        return "(-INT32_C(2147483647) - INT32_C(1))"
    if value < 0:
        return "(-INT32_C(" + str(abs(value)) + "))"
    return "INT32_C(" + str(value) + ")"


def _generate_header(schema: ConfigSchema) -> str:
    lines = [
        "#ifndef FIRMWARE_CONFIG_H",
        "#define FIRMWARE_CONFIG_H",
        "",
        "#include <stdbool.h>",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        "#ifdef __cplusplus",
        'extern "C" {',
        "#endif",
        "",
        "#define FIRMWARE_CONFIG_SCHEMA_VERSION UINT32_C(" + str(schema.version) + ")",
        "#define FIRMWARE_CONFIG_DEVICE " + _c_literal(schema.device),
        "",
    ]
    for setting in schema.settings:
        if setting.kind == "enum":
            enum_tag = "firmware_config_" + setting.name
            lines.append("enum " + enum_tag + " {")
            for index, value in enumerate(setting.values):
                comma = "," if index < len(setting.values) - 1 else ""
                lines.append("    FIRMWARE_CONFIG_" + _macro_name(setting.name) + "_" + _macro_name(value) + " = " + str(index) + comma)
            lines.append("};")
            lines.append("")
    lines.append("struct firmware_config {")
    for setting in schema.settings:
        if setting.kind == "bool":
            declaration = "bool " + setting.name + ";"
        elif setting.kind == "int32":
            declaration = "int32_t " + setting.name + ";"
        elif setting.kind == "uint32":
            declaration = "uint32_t " + setting.name + ";"
        elif setting.kind == "string":
            declaration = "char " + setting.name + "[" + str(setting.max_length + 1) + "];"
        else:
            declaration = "enum firmware_config_" + setting.name + " " + setting.name + ";"
        lines.append("    " + declaration)
    lines.extend(["};", "", "void firmware_config_set_defaults(struct firmware_config *out);"])
    lines.append("bool firmware_config_validate(const struct firmware_config *config);")
    lines.extend(["", "#ifdef __cplusplus", "}", "#endif", "", "#endif", ""])
    return "\n".join(lines)


def _generate_source(schema: ConfigSchema) -> str:
    lines = [
        '#include "firmware_config.h"',
        "",
        "#include <string.h>",
        "",
        "void firmware_config_set_defaults(struct firmware_config *out) {",
        "    if (out == NULL) {",
        "        return;",
        "    }",
    ]
    for setting in schema.settings:
        if setting.kind == "bool":
            lines.append("    out->" + setting.name + " = " + ("true" if setting.default else "false") + ";")
        elif setting.kind in {"int32", "uint32"}:
            lines.append("    out->" + setting.name + " = " + _integer_literal(setting, setting.default) + ";")
        elif setting.kind == "string":
            lines.append("    memset(out->" + setting.name + ", 0, sizeof(out->" + setting.name + "));")
            lines.append("    memcpy(out->" + setting.name + ", " + _c_literal(setting.default) + ", " + str(len(setting.default)) + "U);")
        else:
            lines.append(
                "    out->" + setting.name + " = FIRMWARE_CONFIG_" + _macro_name(setting.name) +
                "_" + _macro_name(setting.default) + ";"
            )
    lines.extend(["}", "", "bool firmware_config_validate(const struct firmware_config *config) {", "    if (config == NULL) {", "        return false;", "    }"])
    for setting in schema.settings:
        if setting.kind in {"int32", "uint32"}:
            lower = _integer_literal(setting, setting.minimum)
            upper = _integer_literal(setting, setting.maximum)
            lines.append("    if (config->" + setting.name + " < " + lower + " || config->" + setting.name + " > " + upper + ") {")
            lines.append("        return false;")
            lines.append("    }")
        elif setting.kind == "string":
            lines.append("    {")
            lines.append("        size_t length = 0U;")
            lines.append("        while (length < sizeof(config->" + setting.name + ") && config->" + setting.name + "[length] != '\\0') {")
            lines.append("            unsigned char character = (unsigned char)config->" + setting.name + "[length];")
            lines.append("            if (character < 0x20U || character > 0x7EU) {")
            lines.append("                return false;")
            lines.append("            }")
            lines.append("            ++length;")
            lines.append("        }")
            lines.append("        if (length > " + str(setting.max_length) + "U) {")
            lines.append("            return false;")
            lines.append("        }")
            lines.append("    }")
        elif setting.kind == "enum":
            choices = [
                "config->" + setting.name + " != FIRMWARE_CONFIG_" + _macro_name(setting.name) + "_" + _macro_name(value)
                for value in setting.values
            ]
            lines.append("    if (" + " && ".join(choices) + ") {")
            lines.append("        return false;")
            lines.append("    }")
    lines.extend(["    return true;", "}", ""])
    return "\n".join(lines)
