"""Regression cover for two agent-wiring defects that had none.

Neither is arithmetic and neither needs a model, so both are cheap to pin. Both
were silent in the worst way: the system kept producing fluent, confident output
while one of them made every tool unavailable and the other made every failure
invisible.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from agent import sourcing_agent
from agent.sourcing_agent import CUSTOM_SERVER, CUSTOM_TOOLS, build_options, run_sourcing_query


# --------------------------------------------------------------------------- #
# The capability server must be spawned under the interpreter that is running
# --------------------------------------------------------------------------- #


def test_the_custom_server_is_spawned_under_the_running_interpreter() -> None:
    """The defect: the server was spawned as a bare "python".

    That name resolves to the system interpreter, which does not have this
    project's dependencies, so the process died on import. The agent then saw
    only the browser provider and correctly refused to invent an answer --
    producing a fluent, well-reasoned, entirely useless response. A total
    failure presented as a competent answer.
    """
    command = build_options().mcp_servers[CUSTOM_SERVER]["command"]

    assert command == sys.executable
    assert command not in ("python", "python3"), (
        "a bare interpreter name resolves to the system Python, which cannot import this project"
    )


def test_the_agent_has_no_built_in_tools_and_inherits_no_local_configuration() -> None:
    """The capability boundary is only the whole surface if nothing bypasses it.

    Pinned because each of these is one keyword away from silently reopening:
    a built-in tool would put capability outside any declared contract, and
    inherited local settings made a developer's own plugin appear inside the
    agent's context during testing, which would not reproduce elsewhere.
    """
    options = build_options()

    assert options.tools == [], "the two providers must be the entire capability surface"
    assert options.setting_sources == []
    assert options.plugins == []

    qualified = {f"mcp__{CUSTOM_SERVER}__{name}" for name in CUSTOM_TOOLS}
    assert qualified <= set(options.allowed_tools), "every custom tool must be allow-listed"


def test_the_chat_profile_is_narrower_than_the_analysis_profile() -> None:
    """The cheap tier answers questions; it does not drive a browser or re-rank."""
    chat = build_options(profile="chat")
    analysis = build_options(profile="analysis")

    assert "playwright" not in chat.mcp_servers
    assert "playwright" in analysis.mcp_servers
    assert len(chat.allowed_tools) < len(analysis.allowed_tools)
    assert chat.model != analysis.model


def test_the_failure_demo_removes_the_fallback_chain() -> None:
    """A failure demo rescued by a fallback demonstrates nothing.

    The ordinary path tries several recency sources in order. The demo must
    offer exactly one, and it must be unreachable.
    """
    demo = build_options(break_playwright=True).system_prompt
    ordinary = build_options().system_prompt

    assert "customs.gov.ua.invalid" in demo
    assert "bank.gov.ua" not in demo, "a fallback would quietly rescue the failure"
    assert "bank.gov.ua" in ordinary, "the ordinary path must still have its fallback"


# --------------------------------------------------------------------------- #
# Tool results arrive on a different message than the turn that asked for them
# --------------------------------------------------------------------------- #


class _FakeClient:
    """Replays a fixed message sequence in place of a real session.

    Deliberately mirrors the real shape: the tool *call* is on an assistant
    turn, and its *result* arrives on a separate user message. Watching only the
    assistant turn is the defect this fixture exists to catch.
    """

    def __init__(self, options: Any = None) -> None:
        self.options = options

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def query(self, _prompt: str) -> None:
        return None

    async def receive_response(self):
        yield SystemMessage(
            subtype="init",
            data={"tools": [f"mcp__{CUSTOM_SERVER}__get_import_flows", "mcp__playwright__browser_navigate"]},
        )
        yield AssistantMessage(
            content=[
                TextBlock(text="Fetching the flows."),
                ToolUseBlock(id="call_1", name=f"mcp__{CUSTOM_SERVER}__get_import_flows", input={"hs_code": "080610"}),
                ToolUseBlock(id="call_2", name="mcp__playwright__browser_navigate", input={"url": "https://x.invalid"}),
            ],
            model="fake",
        )
        yield UserMessage(
            content=[
                ToolResultBlock(tool_use_id="call_1", content='{"status": "ok"}', is_error=False),
                ToolResultBlock(tool_use_id="call_2", content="ERR_NAME_NOT_RESOLVED", is_error=True),
            ]
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=10,
            duration_api_ms=8,
            is_error=False,
            num_turns=2,
            session_id="s",
            result="done",
        )


def _collect(monkeypatch: pytest.MonkeyPatch) -> list:
    """Drive the trace generator to completion.

    Synchronous on purpose: driving the generator with ``asyncio.run`` keeps the
    suite free of an async test plugin for the sake of four tests.
    """
    monkeypatch.setattr(sourcing_agent, "ClaudeSDKClient", _FakeClient)

    async def drain() -> list:
        return [event async for event in run_sourcing_query("q", include_playwright=False)]

    return asyncio.run(drain())


def test_every_tool_call_produces_a_matching_result_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect: results were never captured, so every call looked successful.

    Results arrive on a user message, not on the assistant turn that requested
    them. Watching only the assistant turn yields a trace of calls with no
    outcomes -- and the end-to-end check that read that trace reported "no
    errors" on a run that contained a failure.
    """
    events = _collect(monkeypatch)

    calls = [e for e in events if e.kind == "tool_call"]
    results = [e for e in events if e.kind == "tool_result"]

    assert len(calls) == 2
    assert len(results) == 2, "a trace of calls with no outcomes hides every failure"


def test_a_failed_tool_result_is_reported_as_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capturing results is only useful if the error flag survives the trip."""
    events = _collect(monkeypatch)
    results = {e.tool: e for e in events if e.kind == "tool_result"}

    assert results["get_import_flows"].data["is_error"] is False
    assert results["browser_navigate"].data["is_error"] is True


def test_a_result_is_attributed_to_the_server_that_produced_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Correlation is by call id, so a result must carry its own provider.

    Without this the trace cannot show which provider failed, which is the one
    thing the trace panel exists to show.
    """
    events = _collect(monkeypatch)
    results = {e.tool: e.server for e in events if e.kind == "tool_result"}

    assert results["get_import_flows"] == CUSTOM_SERVER
    assert results["browser_navigate"] == "playwright"


def test_both_providers_are_reported_from_the_session_not_the_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery has to read the live session, or it only restates our own config."""
    events = _collect(monkeypatch)
    discovered = next(e for e in events if e.kind == "status" and e.data.get("servers"))

    assert set(discovered.data["servers"]) == {CUSTOM_SERVER, "playwright"}
