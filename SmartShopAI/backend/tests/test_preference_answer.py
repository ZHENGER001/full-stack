from __future__ import annotations

import unittest
from unittest.mock import patch

from app.agent import build_preference_answer
from app.llm_client import LLMGenerationError, sanitize_preference_answer


async def fail_preference_writer(*args, **kwargs):
    raise LLMGenerationError("disabled")


class PreferenceAnswerTest(unittest.TestCase):
    def test_preference_writer_falls_back_to_template(self) -> None:
        fallback = "通勤嘈杂优先降噪，长途外出优先续航。你主要是哪种场景？"
        with patch("app.agent.generate_preference_answer_with_status", new=fail_preference_writer):
            answer, status = build_preference_answer("降噪和续航哪个更重要", fallback, {})

        self.assertEqual(answer, fallback)
        self.assertEqual(status["mode"], "fallback")

    def test_sanitize_preference_answer_blocks_technical_or_structured_output(self) -> None:
        self.assertEqual(sanitize_preference_answer('{"answer":"x"}'), "")
        self.assertEqual(sanitize_preference_answer("RRF score says x"), "")
        self.assertEqual(sanitize_preference_answer("通勤嘈杂优先降噪，长途外出优先续航。你主要在哪用？"), "通勤嘈杂优先降噪，长途外出优先续航。你主要在哪用？")


if __name__ == "__main__":
    unittest.main()
