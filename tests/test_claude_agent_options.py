from app.claude_agent import (
    MCP_TOOL_NAMES,
    SYSTEM_PROMPT,
    build_prompt,
    is_sdk_startup_error,
)


def test_system_prompt_requires_action_items():
    assert "Action Items" in SYSTEM_PROMPT
    assert "lookup_employee" in SYSTEM_PROMPT


def test_mcp_tool_names_are_fully_qualified():
    assert all(name.startswith("mcp__meetings__") for name in MCP_TOOL_NAMES)
    assert "mcp__meetings__transcribe_audio" in MCP_TOOL_NAMES


def test_prompt_includes_sandbox_paths():
    text = build_prompt(
        audio_path="jobs/abc/meeting.mp3",
        image_paths=["jobs/abc/slide.png"],
        user_query="對照上次 Q2 決議",
    )
    assert "jobs/abc/meeting.mp3" in text
    assert "slide.png" in text
    assert "Q2" in text


def test_sdk_startup_error_detects_initialize_timeout():
    assert is_sdk_startup_error(Exception("Control request timeout: initialize"))
    assert is_sdk_startup_error(Exception("Credit balance is too low"))
    assert not is_sdk_startup_error(Exception("GROQ_API_KEY is missing"))
