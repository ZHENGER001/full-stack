from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import concurrency
from app.database import get_connection


class ConcurrencyControlsTest(unittest.TestCase):
    def test_sqlite_connection_uses_busy_timeout_and_wal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "smartshop.db"
            settings = SimpleNamespace(database_path=db_path)

            with patch("app.database.get_settings", return_value=settings):
                connection = get_connection()
                try:
                    busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()["timeout"]
                    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()["journal_mode"]
                finally:
                    connection.close()

        self.assertEqual(int(busy_timeout), 5000)
        self.assertEqual(str(journal_mode).lower(), "wal")

    def test_concurrency_limit_clamps_invalid_values(self) -> None:
        with patch("app.concurrency.env_value", return_value="0"):
            self.assertEqual(concurrency.concurrency_limit("LLM_MAX_CONCURRENCY", 4), 1)
        with patch("app.concurrency.env_value", return_value="999"):
            self.assertEqual(concurrency.concurrency_limit("LLM_MAX_CONCURRENCY", 4), 64)
        with patch("app.concurrency.env_value", return_value="bad"):
            self.assertEqual(concurrency.concurrency_limit("LLM_MAX_CONCURRENCY", 4), 4)

    def test_sync_slots_are_usable(self) -> None:
        with concurrency.embedding_slot():
            acquired_embedding = True
        with concurrency.milvus_slot():
            acquired_milvus = True
        with concurrency.sync_llm_slot():
            acquired_llm = True

        self.assertTrue(acquired_embedding)
        self.assertTrue(acquired_milvus)
        self.assertTrue(acquired_llm)


if __name__ == "__main__":
    unittest.main()
