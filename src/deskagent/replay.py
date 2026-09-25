"""Replay scripted Claude turns through the real anthropic SDK, without network or cost.

An httpx2 MockTransport answers each request the SDK sends with the next
scripted assistant turn, encoded as the documented Messages streaming events.
Tests and the offline eval baselines (oracle, null) use it, so they exercise
the same SDK request/stream code as a live run.
"""

from __future__ import annotations

import json

import anthropic
import httpx2

USAGE = {"input_tokens": 1000, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def sse(blocks, stop_reason, output_tokens=200, stop_details=None):
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "msg",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": USAGE,
            },
        }
    ]
    for index, block in enumerate(blocks):
        if block["type"] == "text":
            events += [
                {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": index, "delta": {"type": "text_delta", "text": block["text"]}},
            ]
        else:
            events += [
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
                },
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
                },
            ]
        events.append({"type": "content_block_stop", "index": index})
    delta = {"stop_reason": stop_reason, "stop_sequence": None}
    if stop_details:
        delta["stop_details"] = stop_details
    events += [
        {"type": "message_delta", "delta": delta, "usage": {"output_tokens": output_tokens}},
        {"type": "message_stop"},
    ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class Script:
    """Replays one scripted assistant turn per request; each step may read the request so far."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []

    def __call__(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        blocks, stop, *rest = self.steps.pop(0)(body)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse(blocks, stop, stop_details=rest[0] if rest else None),
        )


def client(script) -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="test", max_retries=0, http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(script))
    )
