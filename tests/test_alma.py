from __future__ import annotations

import unittest

from gems.alma import AlmaClient


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
    def test_fetches_set_bib_metadata_and_linked_representation_files(self) -> None:
        session = FakeSession()
        client = AlmaClient(api_key="test-key", session=session)

        self.assertEqual(["991", "992"], client.fetch_set_members("123"))
        records = client.fetch_records(["991"])

        self.assertEqual("API title", records[0]["metadata"]["title"])
        self.assertEqual("Archivist", records[0]["metadata"]["creator"])
        self.assertEqual(
            [{"source": "https://download.example/scan.tif", "filename": "scan.tif"}],
            records[0]["files"],
        )
        self.assertIn("https://files.example/991", session.urls)


if __name__ == "__main__":
    unittest.main()