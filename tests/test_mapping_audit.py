from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gems.mapping_audit import DEFAULT_MAP, audit_xml
from gems.alma import _extract_dc_metadata
from gems.pipeline import build_template_row


class MappingAuditTests(unittest.TestCase):
    def test_requested_fields_and_type_precedence(self):
        mapping = json.loads(DEFAULT_MAP.read_text(encoding="utf-8"))
        xml = """<record xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:dcterms="http://purl.org/dc/terms/"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <dcterms:relation>Related A</dcterms:relation>
          <dcterms:relation>Related B</dcterms:relation>
          <dc:relation>Related C</dc:relation>
          <dc:relation>Related A</dc:relation>
          <dcterms:provenance>Cynthia Levy</dcterms:provenance>
          <dc:subject>1950s</dc:subject><dc:subject>Grinnell</dc:subject>
          <dc:subject>1950s</dc:subject>
          <dc:subject xsi:type="dcterms:LCSH">Typed keyword excluded</dc:subject>
          <dc:type>image</dc:type>
        </record>"""
        metadata = _extract_dc_metadata([xml])
        def row(child=False):
            return build_template_row(
                mapping["columns"], mapping["rules"], {}, metadata,
                {"dcmi_type": "Still Image"}, child=child,
            )
        parent = row()
        self.assertEqual("Related A; Related B; Related C", parent["related"])
        self.assertEqual("Cynthia Levy", parent["provenance"])
        self.assertEqual("1950s; Grinnell", parent["keywords"])
        self.assertEqual("image", parent["type"])
        child = row(child=True)
        self.assertEqual("Still Image", child["type"])
        for column in ("related", "provenance", "keywords"):
            self.assertEqual("", child[column])
        metadata["dcterms:type (dcterms:DCMIType)"] = "Text"
        self.assertEqual("Text", row()["type"])
        metadata["dcterms:type (dcterms:DCMIType)"] = ""
        metadata["dc:type"] = ""
        self.assertEqual("Still Image", row()["type"])

    def test_format_combines_mime_type_and_unqualified_dc_format(self):
        mapping = json.loads(DEFAULT_MAP.read_text(encoding="utf-8"))
        xml = """<record xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:dcterms="http://purl.org/dc/terms/"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <dc:format>reformatted digital</dc:format>
          <dcterms:format xsi:type="dcterms:IMT">image/tiff</dcterms:format>
        </record>"""
        metadata = _extract_dc_metadata([xml])
        def row(mime, child=False):
            return build_template_row(
                mapping["columns"], mapping["rules"], {}, metadata,
                {"mime_type": mime}, child=child,
            )
        self.assertEqual("image/jpeg; reformatted digital", row("image/jpeg")["format"])
        self.assertEqual("image/jpeg; reformatted digital", row("image/jpeg", child=True)["format"])
        self.assertEqual("reformatted digital", row("")["format"])

    def test_example_covers_every_occurrence_and_omissions(self):
        xml = """<record xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:dcterms="http://purl.org/dc/terms/"
            xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
          <compoundrelationship>child of: grinnell:11995</compoundrelationship>
          <googlesheetsource>0242 https://example.org/sheet</googlesheetsource>
          <dcterms:abstract>From left to right: Ivan Palmer, Lorraine Palmer and Mary Lou Palmer.</dcterms:abstract>
          <dcterms:created>1952</dcterms:created>
          <dcterms:extent>1 sheet</dcterms:extent>
          <dc:format>reformatted digital</dc:format>
          <dcterms:format xsi:type="dcterms:IMT">image/tiff</dcterms:format>
          <dc:identifier>991011597366604641</dc:identifier>
          <dc:identifier>grinnell:11992</dc:identifier>
          <dc:identifier>http://hdl.handle.net/11084/11992</dc:identifier>
          <dc:identifier>alma:01GCL_INST/bibs/991011597366604641</dc:identifier>
          <dcterms:isPartOf>Poweshiek History Preservation Project</dcterms:isPartOf>
          <dcterms:isPartOf>Drake Community Library (Grinnell, Iowa) Archives</dcterms:isPartOf>
          <dcterms:isPartOf>Digital Grinnell</dcterms:isPartOf>
          <dc:language>English</dc:language>
          <dcterms:provenance>Cynthia Levy</dcterms:provenance>
          <dcterms:publisher>Poweshiek History Preservation Project</dcterms:publisher>
          <dc:relation>Hula Dancing at the Country Club</dc:relation>
          <dc:rights>Copyright to this work is held by the author(s).</dc:rights>
          <dcterms:spatial>Grinnell (Iowa)</dcterms:spatial>
          <dc:subject>1950s</dc:subject>
          <dc:subject>Grinnell</dc:subject>
          <dc:subject>Family Life</dc:subject>
          <dcterms:subject xsi:type="dcterms:LCSH">Family reunions</dcterms:subject>
          <dcterms:subject xsi:type="dcterms:LCSH">Palmer family</dcterms:subject>
          <dcterms:subject xsi:type="dcterms:LCSH">Hula (Dance)</dcterms:subject>
          <dc:title>Hula Dancing at the Country Club, 1 of 3</dc:title>
          <dc:type>image</dc:type>
          <dcterms:type xsi:type="dcterms:DCMIType">Still Image</dcterms:type>
        </record>"""
        report = audit_xml(xml, json.loads(DEFAULT_MAP.read_text()), mms_id="991011597366604641")
        numbered = [line for line in report.splitlines() if line.startswith("| ") and line.split("|")[1].strip().isdigit()]
        self.assertEqual(29, len(numbered))
        self.assertIn("subject_topic: Family reunions; Palmer family; Hula (Dance)", report)
        self.assertIn("provenance: Cynthia Levy", report)
        self.assertIn("keywords: 1950s; Grinnell; Family Life", report)
        self.assertIn("type: omitted because a constant or earlier source takes precedence", report)
        self.assertIn("related: Hula Dancing at the Country Club", report)
        self.assertIn("| dc:format | reformatted digital | format | format: reformatted digital |", report)
        for field in ("compoundrelationship", "googlesheetsource"):
            lines = [line for line in numbered if f"| {field} |" in line]
            self.assertTrue(lines, field)
            self.assertTrue(all("Omitted: no target column rule" in line for line in lines), field)
        self.assertIn("Separately retained through supplied record.mms_id in originating_system_id", report)
        self.assertIn("digital_collection_title: omitted by filtering", report)

    def test_precedence_combination_and_markdown_escaping(self):
        xml = '<record xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>A|B &amp; C</dc:title><dc:description>Other</dc:description></record>'
        mapping = {
            "columns": ["first", "combined", "constant"],
            "rules": {
                "first": {"from": ["metadata.dc:title", "metadata.dc:description"]},
                "combined": {"from": ["metadata.dc:title", "metadata.dc:description"], "combine": True},
                "constant": {"value": "Fixed", "from": "metadata.dc:title"},
            },
        }
        report = audit_xml(xml, mapping)
        self.assertIn("A&#124;B &amp; C", report)
        self.assertIn("first: omitted because a constant or earlier source takes precedence", report)
        self.assertIn("combined: A&#124;B &amp; C; Other", report)
        self.assertIn("constant: omitted because a constant or earlier source takes precedence", report)

    def test_rejects_invalid_xml_and_multiple_records(self):
        mapping = {"columns": ["title"], "rules": {}}
        with self.assertRaises(ValueError):
            audit_xml("<records><record/><record/></records>", mapping)
        result = subprocess.run(
            [sys.executable, "-m", "gems.mapping_audit", "-"],
            input="<record>", capture_output=True, text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("Mapping audit failed", result.stderr)

    def test_cli_accepts_stdin(self):
        result = subprocess.run(
            [sys.executable, "-m", "gems.mapping_audit", "-"],
            input='<record xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title></record>',
            capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("| 1 | dc:title | Test | title | title: Test |", result.stdout)

    def test_cli_writes_output_and_protects_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "record.xml"
            output = Path(directory) / "report.md"
            xml = '<record xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Test</dc:title></record>'
            source.write_text(xml, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "gems.mapping_audit", str(source), "--output", str(output)],
                capture_output=True, text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("", result.stdout)
            self.assertIn("title: Test", output.read_text(encoding="utf-8"))
            result = subprocess.run(
                [sys.executable, "-m", "gems.mapping_audit", str(source), "--output", str(source)],
                capture_output=True, text=True,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("must not overwrite", result.stderr)
            self.assertEqual(xml, source.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
