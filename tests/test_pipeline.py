from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from gems.mods import read_legacy_mods
from gems.pipeline import (
    is_meaningless_name,
    normalize_records,
    process_export,
    process_records,
    representation_items,
)


class PipelineTests(unittest.TestCase):
    def test_normalize_records_honors_field_map_and_expands_files(self):
        records = [
            {
                "record_id": "abc123",
                "metadata": {"display title": "Campus Photo", "license statement": "CC-BY"},
                "descriptiveMetadata": [
                    {"label": "creator name", "value": "University Archives"},
                    {"label": "resource type", "value": "Image"},
                ],
                "files": [
                    {"path": "/tmp/file-one.jpg", "name": "first.jpg"},
                    {"path": "/tmp/file-two.jpg", "name": "second.jpg"},
                ],
            }
        ]

        rows = normalize_records(
            records,
            field_map={"title": "display title", "creator": "creator name", "rights": "license statement"},
            source_system="specto",
        )

        self.assertEqual(2, len(rows))
        self.assertEqual("abc123-1", rows[0]["identifier"])
        self.assertEqual("abc123-2", rows[1]["identifier"])
        self.assertEqual("Campus Photo", rows[0]["title"])
        self.assertEqual("University Archives", rows[0]["creator"])
        self.assertEqual("CC-BY", rows[0]["rights"])
        self.assertEqual("specto", rows[0]["source_system"])

    def test_process_export_writes_collectionbuilder_csv_and_copies_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source_file = tmp / "source.json"
            file_one = tmp / "scan-1.tif"
            file_two = tmp / "scan-2.tif"
            file_one.write_text("image-one", encoding="utf-8")
            file_two.write_text("image-two", encoding="utf-8")
            source_file.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "identifier": "obj-9",
                                "metadata": {"title": "Ledger", "creator": "Town Clerk"},
                                "files": [
                                    {"path": str(file_one), "filename": "ledger-1.tif"},
                                    {"path": str(file_two), "filename": "ledger-2.tif"},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = process_export(source_file, tmp / "out")

            self.assertEqual(2, result.row_count)
            self.assertEqual(2, result.file_count)
            self.assertTrue((tmp / "out" / "objects" / "ledger-1.tif").exists())
            self.assertTrue((tmp / "out" / "objects" / "ledger-2.tif").exists())

            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual("obj-9-1", rows[0]["identifier"])
            self.assertEqual("Ledger", rows[0]["title"])
            self.assertEqual("Town Clerk", rows[0]["creator"])
            self.assertEqual("objects/ledger-1.tif", rows[0]["objectid"])
            self.assertEqual("objects/ledger-2.tif", rows[1]["objectid"])
            self.assertTrue(result.json_path.exists())

    def test_grinnell_template_map_builds_compound_and_single_rows(self):
        field_map = json.loads((Path(__file__).parent.parent / "maps" / "alma-dc-to-grinnell.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            for name in ("grinnell_12_OBJ.jpg", "grinnell_11_OBJ.jpg", "grinnell_5_OBJ.pdf"):
                (tmp / name).write_text(name, encoding="utf-8")
            metadata = {
                "dc:title": "Symposium photos", "dc:creator": "Brown, John, 1800-1859; Des Moines Register",
                "dc:subject": "Old alt title", "dcterms:subject (dcterms:LCSH)": "Slavery; Brown, John, 1800-1859",
                "dc:type": "compound", "dcterms:created": "2011", "dcterms:dateAccepted": "2011-10",
                "dc:identifier": "grinnell:10; http://hdl.handle.net/11084/10; alma:x",
                "dcterms:identifier (dcterms:URI)": "http://hdl.handle.net/11084/10",
                "dcterms:isPartOf": "Social Justice at Grinnell; Digital Grinnell",
                "dc:rights": '<a href="https://rightsstatements.org/page/NoC-US/1.0/?language=en">Public Domain</a>',
            }
            records = [
                {
                    "mms_id": "991", "metadata": metadata,
                    "representations": [
                        {"id": f"rep{number}", "label": f"Photo {number}",
                         "files": {"representation_file": [{"label": f"grinnell_{number}_OBJ.jpg", "thumbnail_url": f"thumb{number}"}]}}
                        for number in (12, 11)
                    ],
                    "files": [{"source": str(tmp / f"grinnell_{number}_OBJ.jpg"), "filename": f"grinnell_{number}_OBJ.jpg"} for number in (12, 11)],
                },
                {
                    "mms_id": "992", "metadata": {"dc:title": "Clipping", "dc:type": "text", "dcterms:type (dcterms:DCMIType)": "Text"},
                    "files": [{"source": str(tmp / "grinnell_5_OBJ.pdf"), "filename": "grinnell_5_OBJ.pdf"}],
                },
                # A metadata-only bib with no files at all.
                {"mms_id": "993", "metadata": {"dc:title": "Finding aid only"}},
            ]

            result = process_records(records, tmp / "out", field_map=field_map)

            self.assertEqual(3, result.file_count)
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(field_map["columns"], reader.fieldnames)
            parent, first, second, single, rec = rows
            self.assertRegex(parent["objectid"], r"^dg_\d{10}$")
            self.assertEqual(("", "compound_object"), (parent["parentid"], parent["display_template"]))
            numbers = [int(row["objectid"].rsplit("_", 1)[1]) for row in rows]
            self.assertEqual(list(range(numbers[0], numbers[0] + 5)), numbers)
            self.assertEqual("Brown, John, 1800-1859", parent["creator_personal"])
            self.assertEqual("Des Moines Register", parent["creator_org"])
            self.assertEqual(("Slavery", "Brown, John, 1800-1859"), (parent["Subject (Topic)"], parent["Subject (Person)"]))
            self.assertEqual("2011", parent["date"])
            self.assertEqual("Still Image", parent["type"])
            self.assertEqual("Social Justice at Grinnell", parent["Digital Collection Title"])
            self.assertEqual(("grinnell:10", "http://hdl.handle.net/11084/10"), (parent["identifier"], parent["Item Permalink"]))
            self.assertEqual(("Public Domain", "http://rightsstatements.org/vocab/NoC-US/1.0/"), (parent["rights"], parent["Standardized Rights"]))
            self.assertEqual("", parent["image_thumb"])
            # DART conventions: children are a `<stem>-NN` sequence on the record's own grinnell PID
            # (D12), and the compound parent's original_file_name is "_" + the first child's name.
            self.assertEqual("_grinnell_12-01.jpg", parent["original_file_name"])
            self.assertEqual("grinnell_12-01.jpg; grinnell_12-02.jpg", parent["Filename"])
            self.assertEqual((parent["objectid"], "image"), (first["parentid"], first["display_template"]))
            self.assertEqual(("Photo 11", "rep11", "grinnell:11"), (first["title"], first["originating_system_id"], first["identifier"]))
            self.assertEqual(("", "image/jpeg"), (first["object_location"], first["format"]))
            self.assertEqual("", first["description"])
            self.assertEqual("Public Domain", first["rights"])
            self.assertEqual("grinnell_12-01.jpg", first["original_file_name"])
            self.assertEqual((parent["objectid"], "grinnell_12-02.jpg"), (second["parentid"], second["original_file_name"]))
            self.assertEqual(("", "pdf", "Text"), (single["parentid"], single["display_template"], single["type"]))
            # A fileless bib is a 'record' row; its original_file_name borrows the objectid so DART can key it.
            self.assertEqual(("", "record"), (rec["parentid"], rec["display_template"]))
            self.assertEqual("_" + rec["objectid"], rec["original_file_name"])
            self.assertEqual("Finding aid only", rec["title"])
            self.assertTrue((tmp / "out" / "objects" / "grinnell_5_OBJ.pdf").exists())

    def test_compound_parent_borrows_a_web_friendly_child_name(self):
        field_map = {"columns": ["objectid", "parentid", "display_template", "original_file_name"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "display_template": {"from": "gems.display_template", "child": "inherit"},
            "original_file_name": {"from": "gems.filename", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            def record(mms_id, *names):
                files = []
                for name in names:
                    path = tmp / name
                    path.write_text(name, encoding="utf-8")
                    files.append({"source": str(path), "filename": name})
                return {"mms_id": mms_id, "files": files}

            records = [
                # The TIFF sorts first naturally, but the parent borrows the JPG.
                record("991", "2001_scan.tiff", "photo.jpg"),
                # TIFFs only, with a PID-bearing label: the stem is the PID.
                record("992", "grinnell_12_highres.tiff", "grinnell_12_lowres.tiff"),
                # No images at all: the parent borrows the first child.
                record("993", "doc1.pdf", "doc2.pdf"),
            ]
            result = process_records(records, tmp / "out", field_map=field_map)

            self.assertEqual(6, result.file_count)
            with result.csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            parents = [row for row in rows if row["display_template"] == "compound_object"]
            self.assertEqual(["_2001_scan-02.jpg", "_grinnell_12-01.tiff", "_doc1-01.pdf"],
                             [row["original_file_name"] for row in parents])
            # Children are renumbered in natural filename order (the TIFF is still 991's first child).
            children = [row["original_file_name"] for row in rows if row["parentid"]]
            self.assertEqual(["2001_scan-01.tiff", "2001_scan-02.jpg", "grinnell_12-01.tiff", "grinnell_12-02.tiff",
                              "doc1-01.pdf", "doc1-02.pdf"], children)

    def test_long_numeric_alma_names_are_rebuilt_from_record_context(self):
        field_map = {"columns": ["objectid", "parentid", "display_template", "original_file_name"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "display_template": {"from": "gems.display_template", "child": "inherit"},
            "original_file_name": {"from": "gems.filename", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            def record(mms_id, metadata, *entries):
                representations, files = [], []
                for pid, stored, content in entries:
                    path = tmp / f"{mms_id}-{pid}-{stored}"
                    path.write_text(content, encoding="utf-8")
                    representations.append({"id": f"rep-{pid}", "files": {"representation_file": [
                        {"pid": pid, "label": stored, "url": str(path), "path": f"store/{pid}/{stored}"}]}})
                    files.append({"source": str(path), "filename": stored})
                return {"mms_id": mms_id, "metadata": metadata, "representations": representations, "files": files}

            records = [
                # The GHM pattern: an MMS-ID-named access image beside a meaningfully named master.
                record("991", {"dc:identifier": "grinnell:21716", "dc:title": "Barn"},
                       ("f1", "991011591179304641.jpg", "access"), ("f2", "grinnell_21716_OBJ.tiff", "master")),
                # Every name numeric-only: rebuilt from the record's legacy grinnell PID.
                record("992", {"dc:identifier": "grinnell:109", "dc:title": "Symposium"},
                       ("f3", "991011532686604641.jpg", "one"), ("f4", "991011532686604642.tiff", "two")),
                # No PID either: rebuilt from the slugified title.
                record("993", {"dc:title": "Horses and wagon in Grinnell"},
                       ("f5", "991011591182304641.jpg", "front"), ("f6", "991011591182304642.jpg", "back")),
            ]

            result = process_records(records, tmp / "out", field_map=field_map)

            self.assertEqual(6, result.file_count)
            self.assertEqual([], result.renamed_files)
            with result.csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            parents = [row for row in rows if not row["parentid"]]
            children = [row["original_file_name"] for row in rows if row["parentid"]]
            # Every compound's children are one obvious `<stem>-NN` sequence (D12); the MMS-ID-named
            # access image joins its master's stem, so each pair shares one DART base.
            self.assertEqual(["grinnell_21716-01.jpg", "grinnell_21716-02.tiff",
                              "grinnell_109-01.jpg", "grinnell_109-02.tiff",
                              "horses-and-wagon-in-grinnell-01.jpg", "horses-and-wagon-in-grinnell-02.jpg"],
                             children)
            # Parents borrow a meaningful, web-friendly child name (never the TIFF master).
            self.assertEqual(["_grinnell_21716-01.jpg", "_grinnell_109-01.jpg", "_horses-and-wagon-in-grinnell-01.jpg"],
                             [row["original_file_name"] for row in parents])
            # The files on disk carry exactly the names the CSV reports.
            self.assertEqual(set(children), {path.name for path in (tmp / "out" / "objects").iterdir()})
            # Short numeric stems are sequence numbers, not MMS IDs, so they are left alone.
            self.assertFalse(is_meaningless_name("991.jpg"))
            self.assertTrue(is_meaningless_name("991011591179304641.jpg"))

    def test_template_objectids_are_persisted_and_unique_across_batches(self):
        field_map = {"columns": ["objectid", "parentid"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            group = Path(tmpdir) / "collection-social-justice-1"
            manifests = []
            for run in ("run-1", "run-2"):
                (group / run).mkdir(parents=True)
                files = []
                for number in (1, 2):
                    path = group / run / f"{run}-{number}.jpg"
                    path.write_text("x", encoding="utf-8")
                    files.append({"source": str(path), "filename": path.name})
                manifest = group / run / f"gems_social-justice_{run}.json"
                manifest.write_text(json.dumps({
                    "collection_title": "Social Justice at Grinnell",
                    "records": [{"mms_id": "991", "files": files}, {"mms_id": "992"}],
                }), encoding="utf-8")
                manifests.append(manifest)

            def objectids(manifest: Path) -> list[str]:
                result = process_export(manifest, manifest.parent, field_map=field_map)
                with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                    return [row["objectid"] for row in csv.DictReader(handle)]

            first = objectids(manifests[0])
            second = objectids(manifests[1])

            self.assertEqual(4, len(first))
            for value in first + second:
                self.assertRegex(value, r"^social-justice-at-grinnell_dg_\d+$")
            self.assertFalse(set(first) & set(second))
            self.assertEqual(first, objectids(manifests[0]))
            saved = json.loads(manifests[0].read_text(encoding="utf-8"))["records"][0]
            self.assertEqual(first[0], saved["objectid"])
            self.assertEqual(first[1:3], list(saved["child_objectids"].values()))

    def test_explicit_objectid_prefix_overrides_and_is_saved(self):
        field_map = {"columns": ["objectid", "parentid"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            group = Path(tmpdir) / "collection-ghm-1" / "run"
            group.mkdir(parents=True)
            for name, mms_id in (("a.jpg", "991"), ("b.jpg", "992")):
                path = group / name
                path.write_text("x", encoding="utf-8")
            manifest = group / "gems_ghm_run.json"
            manifest.write_text(json.dumps({
                "collection_title": "Grinnell Historical Museum",
                "records": [
                    {"mms_id": "991", "files": [{"source": str(group / "a.jpg"), "filename": "a.jpg"}]},
                    {"mms_id": "992", "files": [{"source": str(group / "b.jpg"), "filename": "b.jpg"}]},
                ],
            }), encoding="utf-8")

            result = process_export(manifest, group, field_map=field_map, objectid_prefix="  GHM Site! ")
            with result.csv_path.open(encoding="utf-8", newline="") as handle:
                ids = [row["objectid"] for row in csv.DictReader(handle)]
            # The typed value is slugified and used for new objectids instead of the collection title.
            self.assertTrue(all(value.startswith("ghm-site_dg_") for value in ids))
            # It is saved on the manifest, so later runs reuse it even with the field left blank.
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual("ghm-site", saved["objectid_prefix"])

            again = process_export(manifest, group, field_map=field_map)
            with again.csv_path.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(ids, [row["objectid"] for row in csv.DictReader(handle)])

    def test_legacy_mods_only_fills_columns_whose_alma_sources_are_empty(self):
        field_map = json.loads((Path(__file__).parent.parent / "maps" / "alma-dc-to-grinnell.json").read_text(encoding="utf-8"))
        mods_xml = """<mods xmlns="http://www.loc.gov/mods/v3">
          <name type="personal"><namePart>Sagin, Hannah</namePart><role><roleTerm type="text">creator</roleTerm></role></name>
          <name type="corporate"><namePart>Grinnell Prize Office</namePart><role><roleTerm type="text">supporting host</roleTerm></role></name>
          <genre>Conference papers and proceedings</genre>
          <physicalDescription><extent>1 sheet</extent><form>paper</form></physicalDescription>
        </mods>"""
        dginfo = '{/"directory/": /"smb://storage/mediadb/DGingest/Migration-to-Alma/exports/social-justice//"}'
        with tempfile.TemporaryDirectory() as tmpdir:
            legacy = Path(tmpdir) / "legacy"
            (legacy / "social-justice").mkdir(parents=True)
            (legacy / "social-justice" / "grinnell_7_MODS.xml").write_text(mods_xml, encoding="utf-8")
            records = [{"mms_id": "991", "metadata": {
                "dc:identifier": "grinnell:7", "dginfo": dginfo,
                "dc:creator": "Des Moines Register", "dc:contributor": "", "dcterms:medium": "glass plate",
            }}]

            with patch("gems.pipeline.read_legacy_mods", wraps=read_legacy_mods) as reader:
                result = process_records(records, Path(tmpdir) / "out", field_map=field_map, legacy_mods_dir=legacy)
                self.assertEqual(1, reader.call_count)
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                row = next(csv.DictReader(handle))

            # Alma has a creator, so MODS names never displace or supplement it, even in the empty personal column.
            self.assertEqual(("Des Moines Register", ""), (row["creator_org"], row["creator_personal"]))
            self.assertEqual("glass plate", row["medium"])
            self.assertEqual(("", "Grinnell Prize Office"), (row["contributor_personal"], row["contributor_org"]))
            self.assertEqual(("1 sheet", "Conference papers and proceedings"), (row["extent"], row["genre"]))

            with patch("gems.pipeline.read_legacy_mods") as reader:
                process_records(records, Path(tmpdir) / "out2", field_map=field_map)
                reader.assert_not_called()

    def test_template_batches_merge_into_one_csv_in_manifest_order(self):
        field_map = {"columns": ["objectid", "parentid", "title"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "title": {"from": "metadata.dc:title", "child": {"from": "gems.filename"}},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            files = []
            for name in ("p-1.jpg", "p-2.jpg"):
                (tmp / name).write_text(name, encoding="utf-8")
                files.append({"source": str(tmp / name), "filename": name})
            records = [{"mms_id": str(n), "metadata": {"dc:title": f"Title {n}"}} for n in range(1, 5)]
            records[1]["files"] = files
            out = tmp / "run"

            def titles() -> list[str]:
                with (out / "collection_metadata.csv").open(encoding="utf-8", newline="") as handle:
                    return [row["title"] for row in csv.DictReader(handle)]

            result = process_records(records, out, field_map=field_map, start=3, limit=2)
            self.assertEqual((3, 4, 4), (result.first_record, result.last_record, result.total_records))
            self.assertEqual(["Title 3", "Title 4"], titles())

            process_records(records, out, field_map=field_map, start=1, limit=2)
            self.assertEqual(["Title 1", "Title 2", "p-1-01.jpg", "p-1-02.jpg", "Title 3", "Title 4"], titles())

            records[0]["metadata"]["dc:title"] = "Title 1 revised"
            process_records(records, out, field_map=field_map, start=1, limit=1)
            self.assertEqual(["Title 1 revised", "Title 2", "p-1-01.jpg", "p-1-02.jpg", "Title 3", "Title 4"], titles())

            with self.assertRaisesRegex(ValueError, "Start record 5 exceeds 4 available record"):
                process_records(records, out, field_map=field_map, start=5)

    def test_expired_alma_links_are_refreshed_before_download(self):
        field_map = {"columns": ["objectid"], "rules": {"objectid": {"from": "gems.objectid"}}}
        record = {
            "mms_id": "991",
            "representations": [{"id": "rep1", "files": {"representation_file": [{"pid": "f1", "label": "scan.jpg"}]}}],
            "files": [{"source": "https://example.org/scan.jpg?Expires=1000&Signature=x", "filename": "scan.jpg"}],
        }
        refreshed = []

        def refresh(rec, item):
            refreshed.append((rec["mms_id"], item["representation_id"], item["file_pid"]))
            return "https://example.org/scan.jpg?Expires=9999999999&Signature=fresh"

        with tempfile.TemporaryDirectory() as tmpdir, patch("gems.pipeline.urlretrieve") as download:
            download.side_effect = lambda url, path: Path(path).write_text(url, encoding="utf-8")
            process_records([record], Path(tmpdir), field_map=field_map, refresh_source=refresh)
            self.assertEqual([("991", "rep1", "f1")], refreshed)
            self.assertIn("Signature=fresh", download.call_args.args[0])

    def test_files_with_repeated_alma_labels_get_unique_stored_names(self):
        field_map = {"columns": ["objectid", "parentid", "original_file_name"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "original_file_name": {"from": "gems.filename", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            records = []
            for number in (1, 2):
                audio, captions = tmp / f"a{number}.mp3", tmp / f"c{number}.vtt"
                audio.write_text(f"audio {number}", encoding="utf-8")
                captions.write_text(f"captions {number}", encoding="utf-8")
                records.append({
                    "mms_id": f"99{number}",
                    "representations": [{"id": f"rep{number}", "files": {"representation_file": [
                        {"pid": f"v{number}", "label": "MediaTrack VTT", "url": str(captions),
                         "path": f"store/x/grinnell_{number}_MEDIATRACK.vtt"},
                        {"pid": f"m{number}", "label": f"grinnell_{number}_OBJ.mp3", "url": str(audio),
                         "path": f"store/y/grinnell_{number}_OBJ.mp3"},
                    ]}}],
                    "files": [{"source": str(captions), "filename": "MediaTrack VTT"},
                              {"source": str(audio), "filename": f"grinnell_{number}_OBJ.mp3"}],
                })

            result = process_records(records, tmp / "out", field_map=field_map)

            self.assertEqual(4, result.file_count)
            self.assertEqual(
                ["grinnell_1-01.vtt", "grinnell_1-02.mp3", "grinnell_2-01.vtt", "grinnell_2-02.mp3"],
                sorted(path.name for path in (tmp / "out" / "objects").iterdir()),
            )
            self.assertEqual("captions 2", (tmp / "out" / "objects" / "grinnell_2-01.vtt").read_text(encoding="utf-8"))
            self.assertEqual("v2", representation_items(records[1])[0]["file_pid"])

            records[1]["representations"][0]["files"]["representation_file"][0]["path"] = "store/z/grinnell_1_MEDIATRACK.vtt"
            result = process_records(records, tmp / "out2", field_map=field_map)
            self.assertEqual(["grinnell_1-01_v2.vtt", "grinnell_1-02_m2.mp3"], result.renamed_files)
            self.assertEqual("captions 2", (tmp / "out2" / "objects" / "grinnell_1-01_v2.vtt").read_text(encoding="utf-8"))
            self.assertEqual("captions 1", (tmp / "out2" / "objects" / "grinnell_1-01.vtt").read_text(encoding="utf-8"))

    def test_same_named_files_are_renamed_once_and_kept_stable_in_the_manifest(self):
        field_map = {"columns": ["objectid", "parentid", "original_file_name"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "original_file_name": {"from": "gems.filename", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            def file_entry(record_id, pid, name, content):
                path = tmp / f"{pid}.bin"
                path.write_text(content, encoding="utf-8")
                return ({"id": f"rep-{pid}", "files": {"representation_file": [
                    {"pid": pid, "label": name, "url": str(path), "path": f"store/{pid}/{name}"}]}},
                    {"source": str(path), "filename": name})

            def record(mms_id, *files):
                return {"mms_id": mms_id, "representations": [rep for rep, _ in files], "files": [entry for _, entry in files]}

            records = [
                # Two different scans with the same name in one record.
                record("991", file_entry("991", "p1", "991.jpg", "front"), file_entry("991", "p2", "991.jpg", "back")),
                # The same image in a compound record and in its own record.
                record("992", file_entry("992", "p3", "grinnell_7_high.jpg", "photo"), file_entry("992", "p4", "grinnell_7_low.jpg", "other")),
                record("993", file_entry("993", "p5", "grinnell_7_high.jpg", "photo")),
            ]
            group = tmp / "collection-x" / "run"
            group.mkdir(parents=True)
            manifest = group / "gems_x_run.json"
            manifest.write_text(json.dumps({"collection_title": "X", "records": records}), encoding="utf-8")

            result = process_export(manifest, group, field_map=field_map)

            # No clash: 992's children are sequenced to grinnell_7-01/02, leaving grinnell_7_high.jpg free.
            self.assertEqual([], result.renamed_files)
            objects = group / "objects"
            self.assertEqual(("front", "back"), ((objects / "991-01.jpg").read_text(), (objects / "991-02.jpg").read_text()))
            self.assertEqual("photo", (objects / "grinnell_7_high.jpg").read_text())
            self.assertEqual("photo", (objects / "grinnell_7-01.jpg").read_text())
            saved = json.loads(manifest.read_text(encoding="utf-8"))["records"]
            self.assertNotIn("gems_filenames", saved[2])
            with result.csv_path.open(encoding="utf-8", newline="") as handle:
                names = [row["original_file_name"] for row in csv.DictReader(handle)]
            self.assertIn("991-01.jpg", names)
            self.assertIn("grinnell_7-01.jpg", names)
            self.assertIn("grinnell_7_high.jpg", names)

            again = process_export(manifest, group, field_map=field_map)
            self.assertEqual([], again.renamed_files)
            self.assertEqual(saved, json.loads(manifest.read_text(encoding="utf-8"))["records"])

    def test_audio_with_captions_becomes_one_transcript_item(self):
        field_map = json.loads((Path(__file__).parent.parent / "maps" / "alma-dc-to-grinnell.json").read_text(encoding="utf-8"))
        vtt = (
            "WEBVTT\n\n00:00.000 --> 00:26.260\n<v Judy Hunter><span class='oh_speaker_1'>Judy: "
            "<span class='oh_speaker_text'> Let me see if it&#8217;s on.</span></span>\n\n"
            "01:00:41.020 --> 01:01:11.129\n<v Judy Hunter & Geoff Peak><span class='oh_speaker_1'>Judy: "
            "<span class='oh_speaker_text'> Oh.</span></span><span class='oh_speaker_2'>Geoff: "
            "<span class='oh_speaker_text'> That's a mile west.</span></span>\n"
        )
        cue_xml = (
            "<cues><cue cuenum=\"0\"><speaker>Interviewer - Jim Gordon</speaker><start>13.05</start><end>18.17</end>"
            "<transcript>&lt;span class='oh_speaker_1'&gt;Interviewer: &lt;span class='oh_speaker_text'&gt; "
            "State your name?&lt;/span&gt;&lt;/span&gt;</transcript></cue></cues>"
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            records = []
            for number, caption_name, caption_text in ((1, "grinnell_1_MEDIATRACK.vtt", vtt), (2, "grinnell_2_TRANSCRIPT.xml", cue_xml)):
                (tmp / f"grinnell_{number}_OBJ.mp3").write_text("audio", encoding="utf-8")
                (tmp / caption_name).write_text(caption_text, encoding="utf-8")
                records.append({"mms_id": f"99{number}", "metadata": {"dc:title": f"Interview {number}"}, "files": [
                    {"source": str(tmp / caption_name), "filename": caption_name},
                    {"source": str(tmp / f"grinnell_{number}_OBJ.mp3"), "filename": f"grinnell_{number}_OBJ.mp3"},
                ]})
            out = tmp / "out"

            result = process_records(records, out, field_map=field_map)

            self.assertEqual(4, result.file_count)
            with result.csv_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(2, len(rows))
            first = rows[0]
            self.assertEqual(("transcript", "", "Sound", "audio/mpeg"), (first["display_template"], first["parentid"], first["type"], first["format"]))
            # Files are renamed as a `<stem>-NN` sequence (D12); captions are still recognized (D8).
            self.assertEqual("grinnell_1-02.mp3", first["original_file_name"])
            self.assertEqual("grinnell_1-02.mp3; grinnell_1-01.vtt", first["Filename"])
            # The timed-text CSV is named for the media file, per the site's transcript layout.
            with (out / "transcripts" / "grinnell_1-02.csv").open(encoding="utf-8", newline="") as handle:
                self.assertEqual([
                    {"timestamp": "00:00:00", "speaker": "Judy Hunter", "words": "Let me see if it\u2019s on."},
                    {"timestamp": "01:00:41", "speaker": "Judy Hunter", "words": "Oh."},
                    {"timestamp": "01:00:41", "speaker": "Geoff", "words": "That's a mile west."},
                ], list(csv.DictReader(handle)))
            with (out / "transcripts" / "grinnell_2-01.csv").open(encoding="utf-8", newline="") as handle:
                self.assertEqual([{"timestamp": "00:00:13", "speaker": "Interviewer - Jim Gordon", "words": "State your name?"}],
                                 list(csv.DictReader(handle)))

    def test_mods_sources_are_rejected_outside_fallback(self):
        field_map = {"columns": ["extent"], "rules": {"extent": {"from": "mods.extent"}}}
        with tempfile.TemporaryDirectory() as tmpdir, self.assertRaisesRegex(ValueError, "only be used inside a \"fallback\""):
            process_records([{"mms_id": "1", "metadata": {}}], Path(tmpdir), field_map=field_map)

    def test_template_mapping_reuses_downloaded_objects_and_explains_expired_links(self):
        field_map = {"columns": ["objectid"], "rules": {"objectid": {"from": "gems.objectid"}}}
        url = "https://example.org/scan.jpg?Expires=1000&Signature=x"
        records = [{"mms_id": "991", "files": [{"source": url, "filename": "scan.jpg"}]}]
        expired = HTTPError(url, 403, "Forbidden", None, None)
        with tempfile.TemporaryDirectory() as tmpdir, patch("gems.pipeline.urlretrieve", side_effect=expired) as download:
            out = Path(tmpdir) / "out"
            with self.assertRaisesRegex(ValueError, "scan.jpg expired .* Retrieve the records again"):
                process_records(records, out, field_map=field_map)
            self.assertFalse((out / "objects" / "scan.jpg.part").exists())

            (out / "objects" / "scan.jpg").write_text("already here", encoding="utf-8")
            download.reset_mock()
            result = process_records(records, out, field_map=field_map)
            download.assert_not_called()
            self.assertEqual(1, result.file_count)

    def test_default_export_adds_a_maintained_key_column(self):
        records = [{"identifier": "a1", "metadata": {"title": "One"}}, {"identifier": "b2", "metadata": {"title": "Two"}}]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = process_records(records, Path(tmpdir))
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual("key", reader.fieldnames[0])
            self.assertEqual(2, len({row["key"] for row in rows}))
            for row in rows:
                self.assertRegex(row["key"], r"^dg_\d+$")

    def test_existing_keys_and_embedded_fragments_are_maintained(self):
        records = [
            {"identifier": "x", "key": "tdps_dg_1729123456"},
            {"identifier": "photo dg_1729123457 detail"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = process_records(records, Path(tmpdir))
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("tdps_dg_1729123456", rows[0]["key"])
            self.assertEqual("dg_1729123457", rows[1]["key"])

    def test_multi_file_record_does_not_duplicate_its_key(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            files = []
            for name in ("one.tif", "two.tif"):
                path = tmp / name
                path.write_text(name, encoding="utf-8")
                files.append({"path": str(path), "filename": name})
            record = {"identifier": "obj-1", "key": "dg_1729123456", "files": files}
            result = process_records([record], tmp / "out")
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual("dg_1729123456", rows[0]["key"])
            self.assertRegex(rows[1]["key"], r"^dg_\d+$")
            self.assertNotEqual(rows[0]["key"], rows[1]["key"])

    def test_template_rows_use_objectid_as_key(self):
        field_map = {"columns": ["key", "objectid", "parentid"], "rules": {
            "key": {"from": "gems.key", "child": "inherit"},
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
        }}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            files = []
            for name in ("p-1.jpg", "p-2.jpg"):
                path = tmp / name
                path.write_text(name, encoding="utf-8")
                files.append({"source": str(path), "filename": name})
            result = process_records([{"mms_id": "991", "files": files}], tmp / "out", field_map=field_map)
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(["key", "objectid", "parentid"], reader.fieldnames)
            self.assertEqual(3, len(rows))
            self.assertEqual(3, len({row["key"] for row in rows}))
            for row in rows:
                self.assertEqual(row["objectid"], row["key"])
                self.assertRegex(row["key"], r"^dg_\d+$")

    def test_csv_written_before_keys_merges_and_gains_keys(self):
        field_map = {"columns": ["objectid", "parentid", "title"], "rules": {
            "objectid": {"from": "gems.objectid", "child": "inherit"},
            "parentid": {"from": "gems.parentid", "child": "inherit"},
            "title": {"from": "metadata.dc:title"},
        }}
        records = [
            {"mms_id": "1", "objectid": "dg_111", "metadata": {"dc:title": "Old"}},
            {"mms_id": "2", "metadata": {"dc:title": "New"}},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out"
            out.mkdir()
            with (out / "collection_metadata.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["objectid", "parentid", "title"])
                writer.writeheader()
                writer.writerow({"objectid": "dg_111", "parentid": "", "title": "Old"})

            result = process_records(records, out, field_map=field_map, start=2, limit=1)

            self.assertEqual(2, result.row_count)
            with result.csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(["key", "objectid", "parentid", "title"], reader.fieldnames)
            self.assertEqual(("Old", "dg_111", "dg_111"), (rows[0]["title"], rows[0]["objectid"], rows[0]["key"]))
            self.assertEqual("New", rows[1]["title"])
            self.assertEqual(rows[1]["objectid"], rows[1]["key"])
            self.assertRegex(rows[1]["key"], r"^dg_\d+$")


if __name__ == "__main__":
    unittest.main()
