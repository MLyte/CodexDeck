"""Pure rendering helpers for the CodexDeck terminal UI."""

from __future__ import annotations

import re
from dataclasses import dataclass
from textwrap import wrap
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
    version: str = ""
    permission: str = "default"
    fast_mode: bool = False
    auto_mode: bool = False
    uptime_seconds: float | None = None
    duration_seconds: float | None = None
    message: str = ""
    prompt: str = ""
    prompt_can_answer: bool = False


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

CODEXDECK_ART = (
    "▄█████  ▄▄▄  ▄▄▄▄  ▄▄▄▄▄ ▄▄ ▄▄ ████▄  ▄▄▄▄▄  ▄▄▄▄ ▄▄ ▄▄ ",
    "██     ██▀██ ██▀██ ██▄▄  ▀█▄█▀ ██  ██ ██▄▄  ██▀▀▀ ██▄█▀ ",
    "▀█████ ▀███▀ ████▀ ██▄▄▄ ██ ██ ████▀  ██▄▄▄ ▀████ ██ ██",
)

CODEXDECK_COMPACT_ART = (
    "⡎⠑ ⢀⡀ ⢀⣸ ⢀⡀ ⡀⢀ ⡏⢱ ⢀⡀ ⢀⣀ ⡇⡠",
    "⠣⠔ ⠣⠜ ⠣⠼ ⠣⠭ ⠜⠣ ⠧⠜ ⠣⠭ ⠣⠤ ⠏⠢",
)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_terminal_text(text: str) -> str:
    text = ANSI_ESCAPE_RE.sub("", text)
    text = text.replace("\r", " ")
    text = CONTROL_RE.sub("", text)
    return text


def truncate(text: str, width: int) -> str:
    text = clean_terminal_text(text)
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


def _wrap_task_text(prefix: str, text: str, width: int) -> list[str]:
    if width <= 0:
        return [""]
    prefix = truncate(prefix, width)
    text_width = max(1, width - len(prefix))
    wrapped = wrap(text, width=text_width, break_long_words=False, break_on_hyphens=False) or [""]
    lines = [truncate(prefix + wrapped[0], width)]
    continuation_prefix = " " * len(prefix)
    lines.extend(truncate(continuation_prefix + line, width) for line in wrapped[1:])
    return lines


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
    version_text = f"v{status.version}" if status.version else "v0.0.0"
    width = max(1, width)
    height = max(1, height)
    compact_keys = (
        f"Keys: (r)un | (s)top | (k)skip | (q)uit | (e)dit | re(l)oad | (n)ew | (h)elp | {version_text}"
    )
    if show_help:
        lines = [
            *[line.center(width) for line in CODEXDECK_COMPACT_ART],
            "compact mode",
            "Help",
            "CodexDeck keeps AI_TODO.md visible.",
            "Options: (M)odel, (F)ast, (Pe)rm, Aut(o)",
            compact_keys,
            "made by lyte | https://github.com/MLyte/CodexDeck",
        ]
        lines = lines[:height]
        while len(lines) < height:
            lines.append("")
        return "\n".join(_pad_line(line, width) for line in lines)
    lines = [
        *[line.center(width) for line in CODEXDECK_COMPACT_ART],
        "compact mode",
        (
            f"Status: {status.state} | Up: {format_duration(status.uptime_seconds)} | "
            f"Dur: {format_duration(status.duration_seconds)} | Err: {status.errors}"
        ),
        (
            f"(M)odel: {status.model} | (F)ast: {_on_off(status.fast_mode)} | "
            f"(Pe)rm: {status.permission} | Aut(o): {_on_off(status.auto_mode)}"
        ),
        f"Last run: {status.last_run}",
        compact_keys,
    ]
    if status.message:
        lines.insert(2, status.message)
    if status.prompt:
        label = "Action required" if status.prompt_can_answer else "Question from Codex"
        lines.insert(3, f"{label}: {status.prompt}")
        hint = "Answer: y yes | n no | s stop" if status.prompt_can_answer else "Next: e edit TODO | r rerun | k skip"
        lines.insert(4, hint)
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
    show_header = (
        not ascii_borders
        and content_width >= max(len(line) for line in CODEXDECK_ART)
        and height >= (30 if show_help else 22)
    )
    show_compact_header = not show_header and content_width >= max(len(line) for line in CODEXDECK_COMPACT_ART)
    header_lines = CODEXDECK_ART if show_header else CODEXDECK_COMPACT_ART if show_compact_header else ()
    header_h = len(header_lines) + 1 if header_lines else 0
    prompt_h = 3 if status.prompt and not show_help else 0
    available_h = max(4, height - 11 - header_h - (prompt_h + 2 if prompt_h else 0))
    if show_help:
        task_h = min(4, max(2, available_h // 3))
        summary_h = 1
        log_h = max(1, available_h - task_h - summary_h)
    elif available_h <= 9:
        task_h = 4 if available_h >= 6 else 3
        summary_h = min(2, max(1, available_h - task_h - 1))
        log_h = max(1, available_h - task_h - summary_h)
    else:
        min_task_h = 4 if available_h >= 6 else 3
        task_h = max(min_task_h, min(8, available_h // 3 + 2))
        summary_h = min(3, max(1, available_h - task_h - 1))
        log_h = max(1, available_h - task_h - summary_h)

    rendered: list[str] = []
    rendered.append(borders["tl"] + borders["h"] * content_width + borders["tr"])
    if header_lines:
        rendered.extend(borders["v"] + line.center(content_width) + borders["v"] for line in header_lines)
        rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    task_list = list(tasks)
    task_offset = clamp_task_offset(len(task_list), task_h, task_offset)

    rendered.append(
        borders["v"]
        + truncate(task_range_label(len(task_list), task_h, task_offset), content_width).center(content_width)
        + borders["v"]
    )

    visible_tasks = task_list[task_offset : task_offset + task_h]
    task_texts = []
    for task_index, task in enumerate(visible_tasks):
        if len(task_texts) >= task_h:
            break
        marker = ">" if active_task_id is not None and getattr(task, "id", None) == active_task_id else " "
        checkbox = "[x]" if task.done else "[ ]"
        wrapped_task = _wrap_task_text(f"{marker}{checkbox} ", task.text, content_width - 2)
        remaining_tasks = len(visible_tasks) - task_index - 1
        remaining_rows = task_h - len(task_texts)
        max_lines_for_task = max(1, remaining_rows - remaining_tasks)
        task_texts.extend(wrapped_task[:max_lines_for_task])
    if not task_texts:
        task_texts = [truncate(line, content_width - 2) for line in task_panel_hint]
    while len(task_texts) < task_h:
        task_texts.append("")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in task_texts[:task_h])

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    output_title = "Codex Output"
    rendered.append(borders["v"] + truncate(output_title, content_width).center(content_width) + borders["v"])
    output_lines = list(logs)[:log_h] if show_help else list(logs)[-log_h:]
    log_texts = [truncate(line, content_width - 2) for line in output_lines]
    while len(log_texts) < log_h:
        if show_help:
            log_texts.append("")
        else:
            log_texts.insert(0, "")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in log_texts)

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    if prompt_h:
        prompt_title = "Action Required" if status.prompt_can_answer else "Question from Codex"
        rendered.append(borders["v"] + prompt_title.center(content_width) + borders["v"])
        prompt_width = content_width - 2
        prompt_lines = wrap(
            status.prompt,
            width=max(1, prompt_width),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        prompt_texts = [truncate(line, prompt_width) for line in prompt_lines[:2]]
        if status.prompt_can_answer:
            prompt_texts.append("Answer: y yes | n no | Esc no | s stop")
        else:
            prompt_texts.append("Next: e edit TODO | r rerun | k skip")
        while len(prompt_texts) < prompt_h:
            prompt_texts.append("")
        rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in prompt_texts[:prompt_h])
        rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])

    rendered.append(borders["v"] + "Task Summary".center(content_width) + borders["v"])
    summary_texts = [truncate(line, content_width - 2) for line in summary_lines]
    while len(summary_texts) < summary_h:
        summary_texts.append("")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in summary_texts[:summary_h])

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    if status.message:
        status_line = (
            f"Status: {status.state:<8} | Up: {format_duration(status.uptime_seconds)} | "
            f"Dur: {format_duration(status.duration_seconds)} | Err: {status.errors} | {status.message}"
        )
    else:
        status_line = (
            f"Status: {status.state:<8} | Ready | Up: {format_duration(status.uptime_seconds)} | "
            f"Dur: {format_duration(status.duration_seconds)} | Err: {status.errors}"
        )
    runtime_line = (
        f"(M)odel: {status.model} | (F)ast: {_on_off(status.fast_mode)} | "
        f"(Pe)rm: {status.permission} | Aut(o): {_on_off(status.auto_mode)}"
    )
    shortcuts_line = (
        f"Keys: (r)un CodexDeck | (s)top | (k)skip | (q)uit | (e)dit | re(l)oad | (n)ew | "
        f"\u2191\u2193 scroll | (h)elp | v{status.version or '0.0.0'} | MIT"
    )
    rendered.append(borders["v"] + truncate(status_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["v"] + truncate(runtime_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["v"] + truncate(shortcuts_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["bl"] + borders["h"] * (width - 2) + borders["br"])
    return "\n".join(truncate(line, width) for line in rendered)


def _on_off(value: bool) -> str:
    return "on" if value else "off"
