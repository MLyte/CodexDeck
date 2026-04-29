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
    uptime_seconds: float | None = None
    duration_seconds: float | None = None


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


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, int(seconds))
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _pad_line(text: str, width: int) -> str:
    return truncate(text, width).ljust(width)


def _compact_frame(*, status: RenderStatus, width: int, height: int, show_help: bool) -> str:
    width = max(1, width)
    height = max(1, height)
    lines = [
        "CodexDeck compact mode",
        f"Status: {status.state} | Model: {status.model} | Up: {format_duration(status.uptime_seconds)} | Errors: {status.errors}",
        f"Last run: {status.last_run} | Dur: {format_duration(status.duration_seconds)}",
        "Commands: r run | s stop | l reload | h/? help | q quit",
    ]
    if show_help:
        lines.extend(
            [
                "",
                "Help",
                "r start Codex, s stop current run, l reload AI_TODO.md",
                "h/? toggle this help, q quit",
            ]
        )
    lines = lines[:height]
    while len(lines) < height:
        lines.append("")
    return "\n".join(_pad_line(line, width) for line in lines)


def render_frame(
    *,
    tasks: Iterable[RenderTask],
    logs: Iterable[str],
    status: RenderStatus,
    width: int,
    height: int,
    ascii_borders: bool = False,
    show_help: bool = False,
) -> str:
    if width < 80 or height < 20:
        return _compact_frame(status=status, width=width, height=height, show_help=show_help)

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
        + truncate(
            "Help: h/? | Run: r | Stop: s | Reload: l | Quit: q" if show_help else "Codex Output",
            right_width,
        ).center(right_width)
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
        f"Last run: {status.last_run:<5} | Up: {format_duration(status.uptime_seconds):<6} | "
        f"Dur: {format_duration(status.duration_seconds):<6} | Errors: {status.errors:<3}"
    )
    rendered.append(
        borders["v"]
        + truncate(status_text, width - 2).ljust(width - 2)
        + borders["v"]
    )
    rendered.append(borders["bl"] + borders["h"] * (width - 2) + borders["br"])
    return "\n".join(truncate(line, width) for line in rendered)
