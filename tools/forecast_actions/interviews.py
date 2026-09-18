"""Expose structured forecasting interviews through the existing ledger tool."""

from forecasting.interviews.agent import operate
from protocol.interview_agent import InterviewAgentRequest
from tools.registry import tool_result


def interview(args, ledger):
    return tool_result(
        success=True,
        **operate(
            ledger, InterviewAgentRequest.model_validate(args.get("interview_request"))
        ),
    )


HANDLERS = {"interview": interview}
