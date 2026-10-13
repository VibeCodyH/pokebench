"""GoogleProvider `region`: a Vertex Express key sent to a project's regional/global endpoint.

Oracle (2026-10-13, real calls): gemini-4-argon 404s on the Express default
(aiplatform.googleapis.com/v1/publishers/google/models) and answers 200 on
/v1/projects/<project>/locations/global/publishers/google/models with the same key.
"""
import os
import unittest
from unittest.mock import patch

import providers
import run_benchmark


class GoogleRegionTests(unittest.TestCase):
    def test_express_key_without_region_keeps_the_default_endpoint(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True):
            p = providers.GoogleProvider("gemini-3.8-flash")
        self.assertEqual(p.base_url, providers.GoogleProvider.VERTEX_EXPRESS)
        self.assertEqual(p.route, "vertex-express")

    def test_region_moves_the_key_to_the_project_endpoint(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k", "GOOGLE_CLOUD_PROJECT": "123"}, clear=True):
            p = providers.GoogleProvider("gemini-4-argon", region="global")
        self.assertEqual(p.base_url,
                         "https://aiplatform.googleapis.com/v1/projects/123/locations/global/publishers/google/models")
        self.assertEqual(p.route, "vertex-express")

    def test_region_without_a_project_fails_before_the_run(self):
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True):
            with self.assertRaises(ValueError):
                providers.GoogleProvider("gemini-4-argon", region="global")

    def test_the_argon_row_reaches_the_adapter_with_its_region(self):
        row = run_benchmark.load_model("gemini-4-argon")
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "k", "GOOGLE_CLOUD_PROJECT": "123"}, clear=True):
            p = run_benchmark.make_provider(row)
        self.assertIn("/projects/123/locations/global/", p.base_url)


if __name__ == "__main__":
    unittest.main()
