from alchemy.llm import CountingLlm
from research_agent.types import AssistantTurn


class ScriptedInner:
    def __init__(self, turns):
        self.turns = list(turns)

    def complete(self, messages, tools):
        return self.turns.pop(0)


def test_counts_calls_and_sums_tokens():
    inner = ScriptedInner([
        AssistantTurn(text="a", usage={"prompt_tokens": 10,
                                       "completion_tokens": 2,
                                       "total_tokens": 12}),
        AssistantTurn(text="b", usage={"prompt_tokens": 20,
                                       "completion_tokens": 3,
                                       "total_tokens": 23}),
    ])
    llm = CountingLlm(inner)
    t1 = llm.complete([], [])
    t2 = llm.complete([], [])
    assert (t1.text, t2.text) == ("a", "b")   # passthrough untouched
    assert llm.usage.llm_calls == 2
    assert llm.usage.prompt_tokens == 30
    assert llm.usage.completion_tokens == 5
    assert llm.usage.total_tokens == 35


def test_missing_usage_counts_call_only():
    inner = ScriptedInner([AssistantTurn(text="a", usage=None),
                           AssistantTurn(text="b",
                                         usage={"prompt_tokens": None,
                                                "completion_tokens": None,
                                                "total_tokens": None})])
    llm = CountingLlm(inner)
    llm.complete([], [])
    llm.complete([], [])
    assert llm.usage.llm_calls == 2
    assert llm.usage.total_tokens == 0   # lower bound, never invented


def test_call_cap_backstop_raises():
    import pytest
    from alchemy.llm import CallCapExceeded
    inner = ScriptedInner([AssistantTurn(text="a", usage=None),
                           AssistantTurn(text="b", usage=None)])
    llm = CountingLlm(inner, max_calls=1)
    llm.complete([], [])
    with pytest.raises(CallCapExceeded):
        llm.complete([], [])
    assert llm.usage.llm_calls == 1   # the refused call is never made or counted
