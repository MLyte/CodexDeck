"""Pure rendering helpers for the CodexDeck terminal UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class RenderTask(Protocol):
    text: str
    done: bool


@dataclass(frozen=True)
class RenderStatus:
    state: str
    model: str
    last_run: str
    errors: int


UNICODE_BORDERS = {
    "tl": "\u250c",
    "tr": "\u2510",
    "bl": "\u2514",
    "br": "\u2518",
    "h": "\u2500",
    "v": "\u2502",
    "tm": "\u252c",
    "lm": "\u251c",
    "bm": "\u2534",
    "rm": "\u2524",
}

ASCII_BORDERS = {
    "tl": "+",
    "tr": "+",
    "bl": "+",
    "br": "+",
    "h": "-",
    "v": "|",
    "tm": "+",
    "lm": "+",
    "bm": "+",
    "rm": "+",
}


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def render_frame(
    *,
    tasks: Iterable[RenderTask],
    logs: Iterable[str],
    status: RenderStatus,
    width: int,
    height: int,
    ascii_borders: bool = False,
) -> str:
    width = max(40, width)
    height = max(8, height)
    borders = ASCII_BORDERS if ascii_borders else UNICODE_BORDERS
    left_width = max(18, min(width // 3, width - 24))
    right_width = width - left_width - 3
    body_h = max(2, height - 5)

    rendered: list[str] = []
    rendered.append(
        borders["tl"]
        + borders["h"] * left_width
        + borders["tm"]
        + borders["h"] * right_width
        + borders["tr"]
    )
    rendered.append(
        borders["v"]
        + truncate("AI_TODO.md", left_width).center(left_width)
        + borders["v"]
        + truncate("Codex Output", right_width).center(right_width)
        + borders["v"]
    )

    task_texts = [truncate(("[x] " if task.done else "[ ] ") + task.text, left_width - 2) for task in tasks]
    log_texts = [truncate(line, right_width - 2) for line in list(logs)[-body_h:]]
    while len(task_texts) < body_h:
        task_texts.append("")
    while len(log_texts) < body_h:
        log_texts.insert(0, "")

    for index in range(body_h):
        rendered.append(
            borders["v"]
            + task_texts[index].ljust(left_width)
            + borders["v"]
            + log_texts[index].ljust(right_width)
            + borders["v"]
        )

    rendered.append(
        borders["lm"]
        + borders["h"] * left_width
        + borders["bm"]
        + borders["h"] * right_width
        + borders["rm"]
    )
    status_text = (
        f"Status: {status.state:<8} | Model: {status.model:<7} | "
        f"Last run: {status.last_run:<5} | Errors: {status.errors:<3}"
    )
    rendered.append(
        borders["v"]
        + truncate(status_text, width - 2).ljust(width - 2)
        + borders["v"]
    )
    rendered.append(borders["bl"] + borders["h"] * (width - 2) + borders["br"])
    return "\n".join(truncate(line, width) for line in rendered)
