from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import flet as ft

from gems.web import main


class WebInputTests(unittest.TestCase):
    def page(self, preferences):
        service = MagicMock()
        service.preferences.return_value = preferences
        service.jobs.return_value = []
        service.claim.return_value = True
        service.storage_error = ""
        service.storage.config = Path("/config")
        service.storage.data = Path("/data")
        page = MagicMock()
        page.session_id = "operator"
        page.route = "/"
        main(page, service)
        controls = page.add.call_args.args[0].controls
        return page, service, controls

    def test_omeka_selection_is_submitted_and_alma_only_fields_are_disabled(self):
        page, service, controls = self.page({
            "source_type": "omeka", "source": "/data/input.json", "omeka_output": "/data/output",
        })
        selector = next(c for c in controls if isinstance(c, ft.Dropdown) and c.label == "Input source")
        output = next(c for c in controls if isinstance(c, ft.TextField) and c.label.startswith("Omeka output"))
        legacy = next(c for c in controls if isinstance(c, ft.TextField) and c.label.startswith("Legacy MODS"))
        prefix = next(c for c in controls if isinstance(c, ft.Row)).controls[2]
        self.assertTrue(output.visible)
        self.assertTrue(legacy.disabled)
        self.assertTrue(prefix.disabled)
        export = next(c for c in controls if isinstance(c, ft.FilledButton) and c.text.startswith("2)"))
        export.on_click(None)
        values = service.submit.call_args.args[2]
        self.assertEqual("omeka", values["source_type"])
        self.assertEqual("/data/output", values["omeka_output"])
        self.assertEqual("/data/input.json", values["source"])
        selector.value = "alma"
        selector.on_change(None)
        self.assertFalse(output.visible)
        self.assertFalse(legacy.disabled)
        self.assertFalse(prefix.disabled)

    def test_using_retrieved_manifest_switches_omeka_back_to_alma(self):
        page, service, controls = self.page({"source_type": "omeka"})
        service.jobs.return_value = [{
            "id": "retrieval", "kind": "retrieve", "state": "succeeded", "created_at": "today",
            "result": {"manifest": "/data/retrieved.json"}, "message": "Completed", "progress": 1,
        }]
        page.route = "/jobs/retrieval"
        page.on_route_change(None)
        use_button = next(c for c in controls if isinstance(c, ft.TextButton) and c.text.startswith("Use this"))
        use_button.on_click(None)
        selector = next(c for c in controls if isinstance(c, ft.Dropdown) and c.label == "Input source")
        self.assertEqual("alma", selector.value)
        self.assertTrue(any(isinstance(c, ft.TextField) and c.value == "/data/retrieved.json" for c in controls))



@unittest.skipUnless(importlib.util.find_spec("flet_web"), "Web runtime is not installed")
class WebRuntimeTests(unittest.TestCase):
    def test_flet_fastapi_serves_browser_client(self):
        import flet_web.fastapi
        from fastapi.testclient import TestClient

        app = flet_web.fastapi.FastAPI()
        app.mount("/", flet_web.fastapi.app(lambda page: None))
        with TestClient(app) as client:
            response = client.get("/")
        self.assertEqual(200, response.status_code)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("flutter", response.text)


if __name__ == "__main__":
    unittest.main()
