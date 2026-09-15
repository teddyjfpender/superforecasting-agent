"""Setup adapter for the same news selection used by the terminal."""

from pathlib import Path

from protocol.rpc.news import NewsConfigureRequest
from superforecasting_agent.application.news_desk import NewsDesk


def setup_news_desk(home: Path) -> None:
    from superforecasting_agent.runtime.setup import print_info, prompt_choice

    desk = NewsDesk(home)
    current = desk.selection()
    if current.state != "unconfigured":
        return
    print_info(
        f"News: {len(current.starter)} public feeds covering markets, policy, world regions, technology and weather."
    )
    print_info(
        "Publisher terms apply; some feeds provide excerpts. No paid wire subscription is included."
    )
    choice = prompt_choice(
        "Start your news desk",
        [
            "Global news starter — recommended",
            "Start empty — add feeds or load the starter later",
        ],
        0,
    )
    desk.configure(NewsConfigureRequest(action="starter" if choice == 0 else "empty"))
