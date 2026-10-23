from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from gems.pipeline import DownloadError, process_export, write_collection_csv, write_structured_records

ROOT = Path(__file__).resolve().parents[1]


class RebuildOmekaTests(unittest.TestCase):
    def test_rebuild_adds_parents_and_original_columns_without_changing_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.csv"
            source.write_text(
                "o:id,o:media[file],dcterms:title,dcterms:type,dcterms:source,wmi:instrumentCategory\n"
                "1,https://example.org/01.mp3 | https://example.org/02.jpg | https://example.org/03.jpg,"
                "Instrument,Formation,Region,chordophone\n",
                encoding="utf-8",
            )
            run = root / "run"

            def download(url, destination):
                if url.endswith("01.mp3"):
                    with HTTPError(url, 403, "Forbidden", {}, None) as error:
                        raise DownloadError("Forbidden") from error
                destination.write_bytes(b"original")

            with patch("gems.pipeline.fetch_object", side_effect=download):
                result = process_export(source, run, source_type="omeka", skip_download_errors=True)
            with result.csv_path.open(newline="") as handle:
                reader = csv.DictReader(handle)
                columns = reader.fieldnames
                old_assets = [row for row in reader if not row["original_file_name"].startswith("_")]
            write_collection_csv(old_assets, result.csv_path, columns)
            write_structured_records(old_assets, result.json_path)
            originals = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in run.rglob("*") if path.is_file()}
            command = [
                sys.executable, str(ROOT / "scripts" / "rebuild_omeka_metadata.py"),
                "--source", str(source), "--run", str(run), "--preserve-source-names",
            ]
            for index, install in enumerate((False, True, True)):
                completed = subprocess.run(
                    command + ["--scratch", str(root / f"scratch-{index}")] + (["--install"] if install else []),
                    capture_output=True, text=True,
                )
                self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
                rebuilt = run if install else root / f"scratch-{index}"
                with (rebuilt / "collection_metadata.csv").open(newline="") as handle:
                    rows = list(csv.DictReader(handle))
                self.assertEqual(3, len(rows))
                self.assertEqual("_" + rows[1]["original_file_name"], rows[0]["original_file_name"])
                self.assertEqual("Instrument", rows[0]["title"])
                for row in rows:
                    self.assertEqual("Formation", row["_dcterms:type"])
                    self.assertEqual("Region", row["_dcterms:source"])
                    self.assertEqual("chordophone", row["_wmi:instrumentCategory"])
                for old in old_assets:
                    new = next(row for row in rows if row["original_file_name"] == old["original_file_name"])
                    self.assertEqual(old, {column: new[column] for column in columns})
                self.assertEqual(rows, json.loads((rebuilt / "normalized_records.json").read_text()))
                for path, (content, modified) in originals.items():
                    if path.parent == result.objects_dir or result.objects_dir in path.parents or path.name == "download_errors.csv":
                        self.assertEqual((content, modified), (path.read_bytes(), path.stat().st_mtime_ns))
                if not install:
                    self.assertEqual(originals[result.csv_path][0], result.csv_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
