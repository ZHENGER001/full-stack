import json
import unittest
from unittest.mock import patch

from app.agent import stream_grounded_answer_events
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
        self.assertEqual(parsed[1], ("delta", {"text": "找到"}))
        self.assertEqual(parsed[2], ("delta", {"text": "手机"}))
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
        self.assertEqual(parsed[1][0], "delta")
        self.assertIn("测试手机", parsed[1][1]["text"])
        self.assertEqual(result[1]["mode"], "fallback")
        self.assertEqual(result[1]["reason"], "boom")


if __name__ == "__main__":
    unittest.main()
