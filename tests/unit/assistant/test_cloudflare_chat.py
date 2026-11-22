"""Cloudflare Workers AI rejects an assistant message whose content is null (400 'string not in
null'); OpenAI's format sends exactly that for a message that only carries a tool call."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from pharmavique.assistant.infrastructure.cloudflare_chat import CloudflareChatOpenAI


def model() -> CloudflareChatOpenAI:
    return CloudflareChatOpenAI(
        model="@cf/openai/gpt-oss-120b", base_url="https://cf.test/ai/v1", api_key="k"
    )


def test_an_assistant_message_that_only_calls_a_tool_has_empty_text_not_null() -> None:
    messages = [
        HumanMessage("q"),
        AIMessage("", tool_calls=[{"name": "search_drugs", "args": {"query": "x"}, "id": "c1"}]),
        ToolMessage(content="{}", tool_call_id="c1"),
    ]

    payload = model()._get_request_payload(messages)

    assert [m["role"] for m in payload["messages"]] == ["user", "assistant", "tool"]
    assert all(m.get("content") is not None for m in payload["messages"])
    assert payload["messages"][1]["content"] == ""
    assert payload["messages"][1]["tool_calls"][0]["id"] == "c1"


def test_other_messages_are_left_as_they_are() -> None:
    payload = model()._get_request_payload([HumanMessage("وش هذا الدواء؟"), AIMessage("جواب")])

    assert [m["content"] for m in payload["messages"]] == ["وش هذا الدواء؟", "جواب"]
