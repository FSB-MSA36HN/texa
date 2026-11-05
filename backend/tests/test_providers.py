"""Provider layer with fake SDK clients: request shape, base_url, finish/refusal mapping, OpenAI json_object fallback. No database."""
import json
import sys
import types
from types import SimpleNamespace as NS

import pytest

from texa import llm
from texa.prompts import INSIGHT_SCHEMA

GOOD = json.dumps({"assumptions": [], "calculations": [], "headline": "h", "body": [], "caveats": [], "follow_ups": []})


@pytest.fixture
def fake(monkeypatch):
    state = {"stop": "end_turn", "finish": "stop", "reject_schema": False, "calls": []}

    class AnthropicClient:
        def __init__(self, **kw):
            state["init"] = kw
            self.messages = self
            self.models = NS(list=lambda: [NS(id="claude-opus-5-5", display_name="Claude Opus 5.5")])

        def create(self, **kw):
            state["calls"].append(kw)
            return NS(usage=NS(input_tokens=10, cache_read_input_tokens=2, output_tokens=5), stop_reason=state["stop"],
                      content=[NS(type="thinking"), NS(type="text", text=GOOD)])

    class BadRequestError(Exception):
        pass

    class OpenAIClient:
        def __init__(self, **kw):
            state["init"] = kw
            self.chat = NS(completions=self)
            self.models = NS(list=lambda: [NS(id="gpt-5"), NS(id="text-embedding-3-small")])

        def create(self, **kw):
            state["calls"].append(kw)
            if kw["response_format"]["type"] == "json_schema" and state["reject_schema"]:
                raise BadRequestError("json_schema not supported")
            return NS(choices=[NS(message=NS(content=GOOD, refusal=None), finish_reason=state["finish"])],
                      usage=NS(prompt_tokens=7, completion_tokens=3, prompt_tokens_details=NS(cached_tokens=0)))

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=AnthropicClient))
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAIClient, BadRequestError=BadRequestError))
    monkeypatch.setattr(llm, "_today_tokens", lambda: 0)

    class NoDB:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def execute(self, *a): return self
    monkeypatch.setattr(llm.db, "app_conn", lambda: NoDB())

    def run(provider, base_url=None):
        monkeypatch.setattr(llm, "get_connection", lambda with_key=False: {
            "provider": provider, "api_key": "k", "base_url": base_url, "default_model": "m", "allowed_models": [],
            "daily_token_limit": 0, "max_output_tokens": 100})
        return llm.generate_structured(model=None, system="s", prompt="p", schema=INSIGHT_SCHEMA, name="insight")

    state["run"] = run
    return state


def test_anthropic_uses_output_config_schema_and_gateway(fake):
    assert fake["run"]("anthropic", "https://gw.example/anthropic")["headline"] == "h"
    assert fake["init"]["base_url"] == "https://gw.example/anthropic"
    call = fake["calls"][0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "maxItems" not in json.dumps(call["output_config"]) and "temperature" not in call


def test_openai_gateway_and_json_object_fallback(fake):
    assert fake["run"]("openai", "https://litellm.example/v1")["headline"] == "h"
    assert fake["init"]["base_url"] == "https://litellm.example/v1"
    fake["reject_schema"], fake["calls"][:] = True, []
    assert fake["run"]("openai")["headline"] == "h"
    assert [c["response_format"]["type"] for c in fake["calls"]] == ["json_schema", "json_object"]


@pytest.mark.parametrize("provider,key,value,code", [
    ("anthropic", "stop", "max_tokens", "MODEL_OUTPUT_TRUNCATED"),
    ("anthropic", "stop", "refusal", "MODEL_REFUSED"),
    ("openai", "finish", "length", "MODEL_OUTPUT_TRUNCATED"),
    ("openai", "finish", "content_filter", "MODEL_REFUSED"),
])
def test_finish_reasons_map_to_errors(fake, provider, key, value, code):
    fake[key] = value
    with pytest.raises(llm.LLMError) as e:
        fake["run"](provider)
    assert e.value.code == code


def test_discover_filters_non_chat_models(fake):
    assert [m["id"] for m in llm.discover_models("openai", "k")] == ["gpt-5"]
    assert llm.discover_models("anthropic", "k")[0]["id"] == "claude-opus-5-5"


def test_provider_request_retries_only_transient_errors(monkeypatch):
    calls = []
    def transient(*_):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("transient")
        return "{}", (1, 0, 1), "ok"
    monkeypatch.setitem(llm._CALLS, "openai", transient)
    monkeypatch.setattr(llm.time, "sleep", lambda _delay: None)
    assert llm._provider_request("openai", {}, "m", "s", "p", {}, "n", 10)[2] == "ok"
    assert len(calls) == 2

    calls.clear()
    def permanent(*_):
        calls.append(1)
        raise ValueError("bad request")
    monkeypatch.setitem(llm._CALLS, "openai", permanent)
    with pytest.raises(ValueError):
        llm._provider_request("openai", {}, "m", "s", "p", {}, "n", 10)
    assert len(calls) == 1


def test_runtime_observer_is_scoped_and_receives_queue_and_provider_events(fake):
    events = []
    with llm.runtime_observer_scope(events.append):
        fake["run"]("openai")
    assert [event["event"] for event in events] == ["llm_queue_wait", "llm_provider_total"]
    assert events[0]["duration_ms"] >= 0
    assert events[1]["outcome"] == "success"


def test_full_admission_queue_fails_closed_without_provider_call(fake, monkeypatch):
    from texa.runtime_guard import AdmissionRejected
    class FullQueue:
        def acquire(self):
            from contextlib import contextmanager
            @contextmanager
            def rejected():
                raise AdmissionRejected('Model request queue is full', wait_ms=5)
                yield
            return rejected()
    events = []
    monkeypatch.setattr(llm, 'ADMISSION', FullQueue())
    with llm.runtime_observer_scope(events.append):
        with pytest.raises(llm.LLMError) as exc:
            fake['run']('openai')
    assert exc.value.code == 'OVERLOADED'
    assert fake['calls'] == []
    assert events == [{'event': 'llm_queue_wait', 'duration_ms': 5, 'call_name': 'insight', 'outcome': 'rejected'}]


def test_provider_error_does_not_expose_raw_credentials_or_payload():
    error = llm._map_error(RuntimeError('Authorization: Bearer private-key; user payload'))
    assert error.code == 'PROVIDER_ERROR'
    assert 'private-key' not in error.message
    assert 'payload' not in error.message
