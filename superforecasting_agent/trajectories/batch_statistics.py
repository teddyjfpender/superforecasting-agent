"""Tool and reasoning statistics for generated trajectories."""

import json
from typing import Any, Dict, List

from superforecasting_agent.tooling.runtime import TOOL_TO_TOOLSET_MAP


# All possible tools - auto-derived from the master mapping in superforecasting_agent/tooling/runtime.py.
# This stays in sync automatically when new tools are added to TOOL_TO_TOOLSET_MAP.
# Used for consistent schema in Arrow/Parquet (HuggingFace datasets) and for
# filtering corrupted entries during trajectory combination.
ALL_POSSIBLE_TOOLS = set(TOOL_TO_TOOLSET_MAP.keys())

# Default stats for tools that weren't used
DEFAULT_TOOL_STATS = {'count': 0, 'success': 0, 'failure': 0}


def _normalize_tool_stats(tool_stats: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    """
    Normalize tool_stats to include all possible tools with consistent schema.
    
    This ensures HuggingFace datasets can load the JSONL without schema mismatch errors.
    Tools that weren't used get zero counts.
    
    Args:
        tool_stats (Dict): Raw tool statistics from extraction
        
    Returns:
        Dict: Normalized tool statistics with all tools present
    """
    normalized = {}

    # Add all possible tools with defaults
    for tool in ALL_POSSIBLE_TOOLS:
        if tool in tool_stats:
            normalized[tool] = tool_stats[tool].copy()
        else:
            normalized[tool] = DEFAULT_TOOL_STATS.copy()

    # Also include any unexpected tools (in case new tools are added)
    for tool, stats in tool_stats.items():
        if tool not in normalized:
            normalized[tool] = stats.copy()

    return normalized


def _normalize_tool_error_counts(tool_error_counts: Dict[str, int]) -> Dict[str, int]:
    """
    Normalize tool_error_counts to include all possible tools.
    
    Args:
        tool_error_counts (Dict): Raw error counts mapping
        
    Returns:
        Dict: Normalized error counts with all tools present
    """
    normalized = {}

    # Add all possible tools with zero defaults
    for tool in ALL_POSSIBLE_TOOLS:
        normalized[tool] = tool_error_counts.get(tool, 0)

    # Also include any unexpected tools
    for tool, count in tool_error_counts.items():
        if tool not in normalized:
            normalized[tool] = count

    return normalized


def _extract_tool_stats(messages: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """
    Extract tool usage statistics from message history.
    
    Args:
        messages (List[Dict]): Message history
        
    Returns:
        Dict: Tool statistics with counts and success/failure rates
    """
    tool_stats = {}

    # Track tool calls and their results
    tool_calls_map = {}  # Map tool_call_id to tool name

    for msg in messages:
        # Track tool calls from assistant messages
        if msg["role"] == "assistant" and "tool_calls" in msg and msg["tool_calls"]:
            for tool_call in msg["tool_calls"]:
                if not tool_call or not isinstance(tool_call, dict): continue
                tool_name = tool_call["function"]["name"]
                tool_call_id = tool_call["id"]

                # Initialize stats for this tool if not exists
                if tool_name not in tool_stats:
                    tool_stats[tool_name] = {
                        "count": 0,
                        "success": 0,
                        "failure": 0
                    }

                tool_stats[tool_name]["count"] += 1
                tool_calls_map[tool_call_id] = tool_name

        # Track tool responses
        elif msg["role"] == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content = msg.get("content", "")

            # Determine if tool call was successful
            is_success = True
            try:
                # Try to parse as JSON and check for actual error values
                content_json = json.loads(content) if isinstance(content, str) else content

                if isinstance(content_json, dict):
                    # Check if error field exists AND has a non-null value
                    if "error" in content_json and content_json["error"] is not None:
                        is_success = False

                    # Special handling for terminal tool responses
                    # Terminal wraps its response in a "content" field
                    if "content" in content_json and isinstance(content_json["content"], dict):
                        inner_content = content_json["content"]
                        # Check for actual error (non-null error field)
                        # Note: non-zero exit codes are not failures - the model can self-correct
                        if inner_content.get("error") is not None:
                            is_success = False

                    # Check for "success": false pattern used by some tools
                    if content_json.get("success") is False:
                        is_success = False

            except (json.JSONDecodeError, ValueError, TypeError):
                # If not JSON, check if content is empty or explicitly states an error
                # Note: We avoid simple substring matching to prevent false positives
                if not content:
                    is_success = False
                # Only mark as failure if it explicitly starts with "Error:" or "ERROR:"
                elif content.strip().lower().startswith("error:"):
                    is_success = False

            # Update success/failure count
            if tool_call_id in tool_calls_map:
                tool_name = tool_calls_map[tool_call_id]
                if is_success:
                    tool_stats[tool_name]["success"] += 1
                else:
                    tool_stats[tool_name]["failure"] += 1

    return tool_stats


def _extract_reasoning_stats(messages: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count how many assistant turns have reasoning vs no reasoning.
    
    Checks for <REASONING_SCRATCHPAD> in content or a non-empty 'reasoning' field
    (native thinking tokens). Returns counts for tracking reasoning coverage.
    
    Args:
        messages: Message history
        
    Returns:
        Dict with 'total_assistant_turns', 'turns_with_reasoning', 'turns_without_reasoning'
    """
    total = 0
    with_reasoning = 0

    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        total += 1

        content = msg.get("content", "") or ""
        has_scratchpad = "<REASONING_SCRATCHPAD>" in content
        has_native_reasoning = bool(msg.get("reasoning", "").strip()) if msg.get("reasoning") else False

        if has_scratchpad or has_native_reasoning:
            with_reasoning += 1

    return {
        "total_assistant_turns": total,
        "turns_with_reasoning": with_reasoning,
        "turns_without_reasoning": total - with_reasoning,
        "has_any_reasoning": with_reasoning > 0,
    }
