"""Pure rendering helpers for the CodexDeck terminal UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol


class RenderTask(Protocol):
    id: str
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
    message: str = ""


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


def clamp_task_offset(task_count: int, visible_count: int, offset: int) -> int:
    if task_count <= 0 or visible_count <= 0:
        return 0
    return min(max(0, offset), max(0, task_count - visible_count))


def task_range_label(task_count: int, visible_count: int, offset: int) -> str:
    if task_count <= 0:
        return "AI_TODO.md 0/0"
    offset = clamp_task_offset(task_count, visible_count, offset)
    first = offset + 1
    last = min(task_count, offset + max(visible_count, 0))
    return f"AI_TODO.md {first}-{last}/{task_count}"


def _compact_frame(*, status: RenderStatus, width: int, height: int, show_help: bool) -> str:
    width = max(1, width)
    height = max(1, height)
    lines = [
        "CodexDeck compact mode",
        f"Status: {status.state} | Model: {status.model} | Up: {format_duration(status.uptime_seconds)} | Errors: {status.errors}",
        f"Last run: {status.last_run} | Dur: {format_duration(status.duration_seconds)}",
        "Commands: r run | s stop | l reload | n new TODO | h/? help | q quit",
    ]
    if status.message:
        lines.insert(2, status.message)
    if show_help:
        lines.extend(
            [
                "",
                "Help",
                "r start Codex, s stop current run, l reload AI_TODO.md",
                "n create AI_TODO.md skeleton, h/? toggle help, q quit",
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
    task_offset: int = 0,
    active_task_id: str | None = None,
    task_panel_hint: Iterable[str] = (),
    summary_lines: Iterable[str] = (),
) -> str:
    if width < 80 or height < 20:
        return _compact_frame(status=status, width=width, height=height, show_help=show_help)

    width = max(40, width)
    height = max(8, height)
    borders = ASCII_BORDERS if ascii_borders else UNICODE_BORDERS
    content_width = width - 2
    available_h = max(6, height - 9)
    task_h = max(3, min(8, available_h // 3 + 1))
    summary_h = min(3, max(2, available_h - task_h - 2))
    log_h = max(2, available_h - task_h - summary_h)

    rendered: list[str] = []
    rendered.append(borders["tl"] + borders["h"] * content_width + borders["tr"])
    task_list = list(tasks)
    task_offset = clamp_task_offset(len(task_list), task_h, task_offset)

    rendered.append(
        borders["v"]
        + truncate(task_range_label(len(task_list), task_h, task_offset), content_width).center(content_width)
        + borders["v"]
    )

    visible_tasks = task_list[task_offset : task_offset + task_h]
    task_texts = []
    for task in visible_tasks:
        marker = ">" if active_task_id is not None and getattr(task, "id", None) == active_task_id else " "
        checkbox = "[x]" if task.done else "[ ]"
        task_texts.append(truncate(f"{marker}{checkbox} {task.text}", content_width - 2))
    if not task_texts:
        task_texts = [truncate(line, content_width - 2) for line in task_panel_hint]
    while len(task_texts) < task_h:
        task_texts.append("")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in task_texts[:task_h])

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    output_title = "Help: h/? | Run: r | Stop: s | Reload: l | New: n | Quit: q" if show_help else "Codex Output"
    rendered.append(borders["v"] + truncate(output_title, content_width).center(content_width) + borders["v"])
    log_texts = [truncate(line, content_width - 2) for line in list(logs)[-log_h:]]
    while len(log_texts) < log_h:
        log_texts.insert(0, "")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in log_texts)

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    rendered.append(borders["v"] + "Task Summary".center(content_width) + borders["v"])
    summary_texts = [truncate(line, content_width - 2) for line in summary_lines]
    while len(summary_texts) < summary_h:
        summary_texts.append("")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in summary_texts[:summary_h])

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    if status.message:
        status_text = (
            f"Status: {status.state:<8} | {status.message} | "
            f"Last run: {status.last_run:<5} | Dur: {format_duration(status.duration_seconds):<6} | "
            f"Errors: {status.errors:<3}"
        )
    else:
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
