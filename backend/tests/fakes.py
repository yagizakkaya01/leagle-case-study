"""A scripted chat model: returns prepared AIMessages in order, records what it saw."""
from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedChatModel(BaseChatModel):
    replies: list[AIMessage]
    seen: list[list[BaseMessage]] = []
    tool_choices: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, tool_choice=None, **kwargs):
        # Same object; remember forced tool choices for assertions.
        return _Bound(self, tool_choice)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.replies.pop(0))])


class _Bound:
    def __init__(self, model: ScriptedChatModel, tool_choice):
        self._model, self._tool_choice = model, tool_choice

    def invoke(self, messages, config=None):
        self._model.tool_choices.append(self._tool_choice)
        return self._model.invoke(messages, config)


def tool_call(name: str, args: dict, call_id: str = "c1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])
