import json
import unittest
from unittest.mock import patch

from app.agent import build_waiting_deltas, stream_grounded_answer_events
from app.llm_client import LLMGenerationError


def collect_generator(generator):
    events = []
    while True:
        try:
            events.append(next(generator))
        except StopIteration as exc:
            return events, exc.value


def event_payload(raw_event: str) -> tuple[str, dict]:
    lines = [line for line in raw_event.splitlines() if line]
    event = lines[0].removeprefix("event:").strip()
    data = json.loads(lines[1].removeprefix("data:").strip())
    return event, data


class LlmStreamingTest(unittest.TestCase):
    def test_waiting_deltas_reflect_exclusion_query(self) -> None:
        deltas = build_waiting_deltas(
            message="除了耐克还有什么球鞋",
            parsed_filters={"excluded_brands": ["Nike"]},
            image_id=None,
            has_chat_history=False,
        )

        self.assertGreaterEqual(len(deltas), 2)
        self.assertIn("排除", deltas[0])

    def test_waiting_deltas_skip_generic_after_early_delta(self) -> None:
        deltas = build_waiting_deltas(
            message="除了耐克还有什么球鞋",
            parsed_filters={"excluded_brands": ["Nike"]},
            image_id=None,
            has_chat_history=False,
            skip_generic_intro=True,
        )

        combined = "\n".join(deltas)
        self.assertNotIn("收到", combined)
        self.assertNotIn("好的", combined)
        self.assertNotIn("正在匹配", combined)
        self.assertTrue(any("排除" in item for item in deltas))

    def test_streams_llm_chunks_as_delta_events(self) -> None:
        async def fake_stream(*_args, **_kwargs):
            yield "找到"
            yield "手机"

        products = [{"title": "测试手机"}]
        with (
            patch("app.agent.stream_agent_reply_chunks_with_status", fake_stream),
            patch("app.agent.llm_model_name", return_value="test-model"),
        ):
            events, result = collect_generator(stream_grounded_answer_events("推荐手机", products, [], []))

        parsed = [event_payload(event) for event in events]
        self.assertEqual(parsed[0][0], "llm_status")
        self.assertEqual(parsed[0][1]["mode"], "calling")
        non_empty_deltas = [item for item in parsed if item[0] == "delta" and item[1]["text"].strip()]
        self.assertEqual(non_empty_deltas[0], ("delta", {"text": "找到"}))
        self.assertEqual(non_empty_deltas[1], ("delta", {"text": "手机"}))
        self.assertEqual(result[0], "找到手机")
        self.assertEqual(result[1]["mode"], "llm_stream")
        self.assertEqual(result[1]["model"], "test-model")

    def test_streaming_failure_falls_back_before_any_delta(self) -> None:
        async def failing_stream(*_args, **_kwargs):
            raise LLMGenerationError("boom")
            yield ""

        products = [{"title": "测试手机"}]
        with patch("app.agent.stream_agent_reply_chunks_with_status", failing_stream):
            events, result = collect_generator(stream_grounded_answer_events("推荐手机", products, [], []))

        parsed = [event_payload(event) for event in events]
        self.assertEqual(parsed[0][0], "llm_status")
        self.assertEqual(parsed[0][1]["mode"], "calling")
        non_empty_deltas = [item for item in parsed if item[0] == "delta" and item[1]["text"].strip()]
        self.assertIn("测试手机", non_empty_deltas[0][1]["text"])
        self.assertEqual(result[1]["mode"], "fallback")
        self.assertEqual(result[1]["reason"], "boom")


if __name__ == "__main__":
    unittest.main()
