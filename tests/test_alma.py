from __future__ import annotations

import unittest
from unittest.mock import patch

from gems.alma import AlmaClient, AlmaServerError, _extract_dc_metadata


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(self, url: str, **_: object) -> FakeResponse:
        self.urls.append(url)
        if url.endswith("/sets/123"):
            return FakeResponse({"name": "Campus Photo Archive"})
        if url.endswith("/members"):
            return FakeResponse({"total_record_count": 2, "member": [{"id": "991"}, {"id": "992"}]})
        if url.endswith("/bibs/991"):
            return FakeResponse(
                {
                    "title": "Fallback title",
                    "anies": [
                        '<record xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>API title</dc:title><dc:creator>Archivist</dc:creator></record>'
                    ],
                }
            )
        if url.endswith("/representations"):
            return FakeResponse({"representation": [{"files": {"link": "https://files.example/991"}}]})
        if url == "https://files.example/991":
            return FakeResponse(
                {"representation_file": [{"label": "scan.tif", "download_url": "https://download.example/scan.tif"}]}
            )
        raise AssertionError(f"Unexpected request: {url}")


class AlmaClientTests(unittest.TestCase):
    def test_collection_listing_skips_only_entries_that_alma_cannot_serve(self) -> None:
        client = AlmaClient(api_key="test-key")
        bad_positions = {1571, 1572}

        def get(path, *, params=None):
            offset, limit = params["offset"], params["limit"]
            if any(offset < position <= offset + limit for position in bad_positions):
                raise AlmaServerError(f"HTTP 500 at offset {offset} (Alma tracking ID T{offset})")
            last = min(offset + limit, 1910)
            return {"total_record_count": 1910, "bib": [{"mms_id": str(n)} for n in range(offset + 1, last + 1)]}

        with patch.object(client, "_get", side_effect=get):
            mms_ids = client.fetch_collection_bibs("81310652980004641")

        self.assertEqual(1908, len(mms_ids))
        self.assertNotIn("1571", mms_ids)
        self.assertEqual(["1570", "1573"], mms_ids[1569:1571])
        self.assertEqual([1571, 1572], client.skipped_positions)
        self.assertIn("tracking ID T1570", client.skipped_errors[0])

    def test_fetches_signed_url_for_representation_file_without_url(self) -> None:
        client = AlmaClient(api_key="test-key")

        def get(path, *, params=None):
            if path.endswith("/representations/r1/files/f1"):
                self.assertEqual({"expand": "url"}, params)
                return {"pid": "f1", "label": "scan.tif", "url": "https://download.example/scan.tif"}
            if path.endswith("/representations"):
                return {"representation": [{"id": "r1", "files": {"representation_file": [
                    {"pid": "f1", "label": "scan.tif", "path": "private/storage/path"},
                ]}}]}
            return {"title": "Test"}

        with patch.object(client, "_get", side_effect=get):
            record = client.fetch_records(["991"])[0]

        self.assertEqual(
            [{"source": "https://download.example/scan.tif", "filename": "scan.tif"}], record["files"]
        )
        file_info = record["representations"][0]["files"]["representation_file"][0]
        self.assertEqual("private/storage/path", file_info["path"])
        self.assertEqual("https://download.example/scan.tif", file_info["url"])

    def test_fetch_records_reports_progress_for_unique_ids(self) -> None:
        client = AlmaClient(api_key="test-key")
        updates: list[tuple[int, int]] = []
        with (
            patch.object(client, "_get", return_value={}),
            patch.object(client, "_to_gems_record", side_effect=lambda mms_id, bib: {"identifier": mms_id}),
        ):
            records = client.fetch_records(
                ["991", "992", "991", "  "],
                on_progress=lambda completed, total: updates.append((completed, total)),
            )
        self.assertEqual([{"identifier": "991"}, {"identifier": "992"}], records)
        self.assertEqual([(1, 2), (2, 2)], updates)

    def test_collection_title_resolves_to_pid_and_paginates_bibs(self) -> None:
        client = AlmaClient(api_key="test-key")
        title = "Social Justice at Grinnell"
        with patch.object(client, "_get", return_value={"collection": [
            {"name": title, "pid": {"value": "8123"}},
            {"name": "Other", "pid": {"value": "9999"}},
        ]}) as get:
            self.assertEqual(("8123", title), client.resolve_collection(title))
            get.assert_called_once_with("/almaws/v1/bibs/collections", params={"q": f"collection_name~{title}"})

        pages = [
            {"total_record_count": 2, "bib": [{"mms_id": "991"}]},
            {"total_record_count": 2, "bib": [{"mms_id": "992"}]},
        ]
        with patch.object(client, "_get", side_effect=pages) as get:
            self.assertEqual(["991", "992"], client.fetch_collection_bibs("8123"))
            self.assertEqual(1, get.call_args.kwargs["params"]["offset"])

        with patch.object(client, "_get", return_value={"collection": [
            {"pid": {"value": "2"}, "name": title},
            {"pid": {"value": "3"}, "name": title},
        ]}):
            with self.assertRaisesRegex(ValueError, "Found 2 Alma collections"):
                client.resolve_collection(title)
        with patch.object(client, "_get", return_value={"collection": []}):
            with self.assertRaisesRegex(ValueError, "Found 0 Alma collections"):
                client.resolve_collection(title)

    def test_fetches_set_bib_metadata_and_linked_representation_files(self) -> None:
        session = FakeSession()
        client = AlmaClient(api_key="test-key", session=session)

        self.assertEqual("Campus Photo Archive", client.fetch_set_title("123"))
        self.assertEqual(["991", "992"], client.fetch_set_members("123"))
        records = client.fetch_records(["991"])

        self.assertEqual("API title", records[0]["metadata"]["dc:title"])
        self.assertEqual("Archivist", records[0]["metadata"]["dc:creator"])
        self.assertNotIn("title", records[0]["metadata"])
        self.assertEqual(
            [{"source": "https://download.example/scan.tif", "filename": "scan.tif"}],
            records[0]["files"],
        )
        self.assertIn("https://files.example/991", session.urls)

    def test_dc_metadata_keeps_namespace_and_xsi_type(self) -> None:
        metadata = _extract_dc_metadata(
            '<record xmlns="http://alma.exlibrisgroup.com/dc/01GCL_INST" xmlns:dc="http://purl.org/dc/elements/1.1/"'
            ' xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            '<dginfo>local</dginfo><dc:type>image</dc:type>'
            '<dcterms:type xsi:type="dcterms:DCMIType">Still Image</dcterms:type>'
            '<dcterms:subject xsi:type="dcterms:LCSH">Portraits</dcterms:subject>'
            '<dcterms:subject xsi:type="dcterms:LCSH">Slavery</dcterms:subject></record>'
        )
        self.assertEqual({
            "dginfo": "local",
            "dc:type": "image",
            "dcterms:type (dcterms:DCMIType)": "Still Image",
            "dcterms:subject (dcterms:LCSH)": "Portraits; Slavery",
        }, metadata)


if __name__ == "__main__":
    unittest.main()