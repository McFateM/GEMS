"""Describe an Alma XML record's contribution to a GEMS template CSV."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as element_tree
from pathlib import Path
from typing import Any

from .alma import DC_PREFIXES, XSI_TYPE, _extract_dc_metadata
from .pipeline import apply_rule, build_template_row, is_template_map

DEFAULT_MAP = Path(__file__).resolve().parent.parent / "maps" / "alma-dc-to-grinnell.json"


def markdown_cell(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace(
        "|", "&#124;"
    ).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def metadata_key(element: element_tree.Element) -> str:
    namespace, _, name = (
        element.tag[1:].rpartition("}") if element.tag.startswith("{") else ("", "", element.tag)
    )
    prefix = DC_PREFIXES.get(namespace)
    key = f"{prefix}:{name}" if prefix else name
    return f"{key} ({element.get(XSI_TYPE)})" if element.get(XSI_TYPE) else key


def rule_sources(rule: dict[str, Any]) -> list[str]:
    sources = rule.get("from", [])
    return [sources] if isinstance(sources, str) else sources


def active_sources(
    rule: dict[str, Any], record: dict[str, Any], metadata: dict[str, str]
) -> set[str]:
    """Find sources that survive filtering and first-value source precedence."""
    if "value" in rule:
        return set()
    active: set[str] = set()
    for source in rule_sources(rule):
        probe = {key: value for key, value in rule.items() if key != "fallback"}
        probe["from"] = source
        if apply_rule(probe, record, metadata, {}):
            active.add(source)
            if not rule.get("combine"):
                break
    return active


def audit_xml(xml: str, field_map: dict[str, Any], *, mms_id: str = "") -> str:
    root = element_tree.fromstring(xml)
    if not is_template_map(field_map):
        raise ValueError("The field map must contain a columns list and template rules.")
    records = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "record"]
    if len(records) != 1:
        raise ValueError("Input must contain exactly one XML metadata record.")
    root = records[0]
    metadata = _extract_dc_metadata([element_tree.tostring(root, encoding="unicode")])
    record: dict[str, Any] = {"metadata": metadata}
    if mms_id:
        record["mms_id"] = mms_id
    columns = field_map["columns"]
    rules = field_map.get("rules", {})
    if not all(isinstance(column, str) for column in columns) or not isinstance(rules, dict):
        raise ValueError("Template columns must be strings and rules must be an object.")
    for rule in rules.values():
        if not isinstance(rule, dict):
            raise ValueError("Each template rule must be an object.")
        sources = rule_sources(rule)
        if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources):
            raise ValueError("Rule sources must be a string or a list of strings.")
    row = build_template_row(columns, rules, record, metadata, {}, child=False)
    active = {
        column: active_sources(rule, record, metadata)
        for column, rule in rules.items() if column in columns and isinstance(rule, dict)
    }
    lines = [
        "## Alma XML to GEMS CSV mapping audit",
        "",
        "This table evaluates the current template rules for the main row of one Alma bib.",
        "Repeated fields are combined as GEMS combines them; each XML occurrence is listed separately.",
        "No representation files, generated IDs, or legacy MODS are supplied. File-derived values",
        "and MODS fallbacks cannot be determined from this XML alone. An optional MMS ID supplies",
        "`record.mms_id`; it is not inferred from XML identifiers.",
        "",
        "| # | XML field | Source value | Target CSV column(s) | Result / omission |",
        "| --- | --- | --- | --- | --- |",
    ]
    for number, element in enumerate(list(root), start=1):
        key = metadata_key(element)
        value = (element.text or "").strip()
        source = f"metadata.{key}"
        targets: list[str] = []
        results: list[str] = []
        referenced = False
        for column in columns:
            rule = rules.get(column)
            if not isinstance(rule, dict) or source not in rule_sources(rule):
                continue
            referenced = True
            probe = {name: setting for name, setting in rule.items() if name != "fallback"}
            probe["from"] = source
            transformed = apply_rule(probe, record, {key: value}, {})
            if transformed and source in active.get(column, set()):
                targets.append(column)
                results.append(f"{column}: {row[column]}")
            elif not transformed:
                results.append(f"{column}: omitted by filtering or empty source value.")
            else:
                results.append(f"{column}: omitted because a constant or earlier source takes precedence.")
        if not referenced:
            results.append("Omitted: no target column rule reads this XML field.")
        if key == "dc:identifier" and mms_id and value == mms_id:
            indirect = [
                column for column in columns
                if "record.mms_id" in active.get(column, set())
            ]
            if indirect:
                results.append(
                    "Separately retained through supplied record.mms_id in " + ", ".join(indirect) + "."
                )
        cells = [str(number), key, value, "; ".join(targets) or "None", " ".join(results)]
        lines.append("| " + " | ".join(markdown_cell(cell) for cell in cells) + " |")
    lines.extend([
        "",
        "### Attribute and row-structure notes",
        "",
        "- Per-element `xml:lang` attributes are not retained by GEMS.",
        "- `xsi:type` is retained in manifest field keys, not as a separate CSV column.",
        "- Namespace declarations identify fields; they are not CSV values.",
        "- Repeated values are de-duplicated and joined with `; `.",
        "- Generated file-child rows use each rule's `child` override or remain blank when none exists.",
        "- The default map does not read `compoundrelationship`: separate Alma bibs are not joined",
        "  into the legacy compound by that field. CSV compounds are generated from a bib's files.",
        "",
        "### Target columns without an XML-derived value",
        "",
        "| Target CSV column | Current value / other source |",
        "| --- | --- |",
    ])
    xml_columns = {
        column for column, sources in active.items() if any(source.startswith("metadata.") for source in sources)
    }
    for column in columns:
        if column in xml_columns:
            continue
        rule = rules.get(column)
        if not isinstance(rule, dict):
            detail = "Blank: no rule."
        elif row[column]:
            detail = f"Value: {row[column]} (constant or supplied non-XML source)."
        else:
            sources = rule_sources(rule)
            fallback = rule.get("fallback")
            if isinstance(fallback, dict):
                sources = sources + rule_sources(fallback)
            detail = "Blank for this input."
            if sources:
                detail += " Rule sources: " + "; ".join(sources) + "."
        lines.append("| " + markdown_cell(column) + " | " + markdown_cell(detail) + " |")
    return "\n".join(lines) + "\n"


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Alma XML metadata file, or - for standard input")
    parser.add_argument("--field-map", type=Path, default=DEFAULT_MAP, help="GEMS template map JSON")
    parser.add_argument("--mms-id", default="", help="Optional top-level Alma MMS ID (not inferred)")
    parser.add_argument("--output", type=Path, help="Write Markdown to this file instead of stdout")
    args = parser.parse_args()
    if args.output and args.source != "-" and args.output.resolve() == Path(args.source).resolve():
        parser.error("--output must not overwrite the XML source")
    if args.output and args.output.resolve() == args.field_map.resolve():
        parser.error("--output must not overwrite the field map")
    try:
        xml = sys.stdin.read() if args.source == "-" else Path(args.source).read_text(encoding="utf-8")
        field_map = json.loads(args.field_map.read_text(encoding="utf-8"))
        report = audit_xml(xml, field_map, mms_id=args.mms_id)
        if args.output:
            args.output.write_text(report, encoding="utf-8")
        else:
            print(report, end="")
    except (OSError, ValueError, element_tree.ParseError) as error:
        parser.exit(1, f"Mapping audit failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
