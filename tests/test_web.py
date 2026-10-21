from __future__ import annotations

import importlib.util
import unittest


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
