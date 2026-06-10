from __future__ import annotations

import unittest

from app.catalog_grounder import catalog_summary_cache_stats, clear_catalog_summary_cache, default_catalog_summary


class CatalogSummaryCacheTest(unittest.TestCase):
    def test_catalog_summary_cache_reports_hits_and_can_clear(self) -> None:
        clear_catalog_summary_cache()
        first = default_catalog_summary()
        after_first = catalog_summary_cache_stats()
        second = default_catalog_summary()
        after_second = catalog_summary_cache_stats()

        self.assertTrue(first["terms"])
        self.assertEqual(first, second)
        self.assertGreaterEqual(after_first["misses"], 1)
        self.assertGreater(after_second["hits"], after_first["hits"])
        self.assertGreater(after_second["matches"], 0)


if __name__ == "__main__":
    unittest.main()
