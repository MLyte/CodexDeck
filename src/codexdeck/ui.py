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
    prompt_options: tuple[str, ...] = ()
    prompt_freeform: bool = True
    session: str = "batch"


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
YES_NO_RE = re.compile(r"\b(?:y/n|yes/no|yes\s+or\s+no|o/n|oui/non|oui\s+ou\s+non)\b", re.IGNORECASE)
EITHER_OR_RE = re.compile(r"\s+(?:or|ou)\s+", re.IGNORECASE)
CLOSED_QUESTION_RE = re.compile(
    r"^\s*(?:do|does|did|should|can|could|would|will|is|are|est-ce|veux-tu|voulez-vous|tu veux|"
    r"souhaites-tu|souhaitez-vous|faut-il)\b|\best[- ](?:ce|il|elle)\b",
    re.IGNORECASE,
)
FRENCH_CLOSED_QUESTION_RE = re.compile(
    r"\b(?:est-ce|est[- ](?:ce|il|elle)|veux-tu|voulez-vous|tu veux|souhaites-tu|souhaitez-vous|faut-il)\b",
    re.IGNORECASE,
)
LEADING_OPTION_WORDS_RE = re.compile(r"^(?:le|la|les|l'|un|une|the|a|an)\s+", re.IGNORECASE)
TRAILING_LEFT_OPTION_RE = re.compile(
    r"(?:^|\s)(?:le|la|les|l'|un|une|the|a|an)\s+([\wÀ-ÿ'-]+(?:\s+[\wÀ-ÿ'-]+){0,2})$",
    re.IGNORECASE,
)


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


def detect_prompt_options(prompt: str, explicit_options: Iterable[str] = ()) -> tuple[str, ...]:
    options = tuple(truncate(option.strip(), 24) for option in explicit_options if option.strip())
    if options:
        return options[:4]

    question = clean_terminal_text(prompt).strip()
    if not question:
        return ()

    normalized = question.lower()
    if YES_NO_RE.search(normalized):
        if "oui" in normalized or "o/n" in normalized:
            return ("oui", "non")
        return ("yes", "no")

    clean_question = question.strip(" \t\r\n?.!:;")
    if len(EITHER_OR_RE.findall(clean_question)) != 1:
        return _closed_prompt_options(normalized, question)

    left_text, right_text = EITHER_OR_RE.split(clean_question, maxsplit=1)
    left = _left_prompt_option(left_text)
    right = _right_prompt_option(right_text)
    if not left or not right or left.casefold() == right.casefold():
        return _closed_prompt_options(normalized, question)
    options = (left, right)
    if all(option.casefold() not in {"yes", "no", "oui", "non"} for option in options):
        return options

    return _closed_prompt_options(normalized, question)


def _closed_prompt_options(normalized_prompt: str, prompt: str) -> tuple[str, ...]:
    if CLOSED_QUESTION_RE.search(normalized_prompt) and prompt.endswith("?"):
        if FRENCH_CLOSED_QUESTION_RE.search(normalized_prompt):
            return ("oui", "non")
        return ("yes", "no")
    return ()


def _left_prompt_option(text: str) -> str:
    text = text.strip(" \t\r\n\"'`.,:;")
    article_match = TRAILING_LEFT_OPTION_RE.search(text)
    if article_match:
        return _clean_prompt_option(article_match.group(1))
    words = text.split()
    return _clean_prompt_option(words[-1]) if words else ""


def _right_prompt_option(text: str) -> str:
    text = LEADING_OPTION_WORDS_RE.sub("", text.strip(" \t\r\n\"'`.,:;"))
    words = text.split()
    return _clean_prompt_option(" ".join(words[:3])) if words else ""


def _clean_prompt_option(text: str) -> str:
    return truncate(LEADING_OPTION_WORDS_RE.sub("", text.strip(" \t\r\n\"'`.,:;")), 24)


def _prompt_help_line(status: RenderStatus, *, compact: bool = False) -> str:
    options = detect_prompt_options(status.prompt, status.prompt_options)
    if options:
        option_hint = " | ".join(f"{index + 1} {option}" for index, option in enumerate(options))
        if status.prompt_freeform:
            suffix = "type free answer" if compact else "free answer"
            return f"Reply: {option_hint} | {suffix} | Enter send | Esc cancel"
        return f"Reply: {option_hint} | Enter send | Esc cancel"
    if status.prompt_freeform:
        return "Reply: type a free answer | Enter send | Esc cancel"
    return "Reply required: edit TODO or rerun with an answer"


def _shortcut_toolbar_lines(version_text: str, width: int, *, max_lines: int = 1) -> list[str]:
    keycap_line = (
        f"[r]run [o]auto [s]stop [k]skip [q]quit [e]edit [l]reload [n]new "
        f"[\u2191\u2193]scroll [h]help {version_text}"
    )
    compact_tokens = (
        "r:run",
        "o:auto",
        "s:stop",
        "k:skip",
        "q:quit",
        "e:edit",
        "l:reload",
        "n:new",
        "scroll",
        "h:help",
        version_text,
    )
    compact_line = " ".join(compact_tokens)

    if max_lines <= 1:
        if len(keycap_line) <= width:
            return [keycap_line]
        return [truncate(compact_line, width)]

    lines: list[str] = []
    current = ""
    for token in compact_tokens:
        candidate = token if not current else f"{current} {token}"
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = token
        if len(lines) == max_lines - 1:
            break
    remaining_tokens = compact_tokens[compact_tokens.index(token) :]
    if len(lines) == max_lines - 1 and remaining_tokens:
        current = " ".join(remaining_tokens)
    if current:
        lines.append(truncate(current, width))
    return lines[:max_lines]


def _deck_title(label: str, width: int, *, lamp: str = "") -> str:
    title = f" {label} " if not lamp else f" {lamp} {label} "
    return truncate(title, width).center(width, "━")


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


def _wrap_output_lines(lines: Iterable[str], width: int, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    wrapped: list[str] = []
    for line in lines:
        clean = clean_terminal_text(line)
        line_parts = wrap(
            clean,
            width=max(1, width),
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        wrapped.extend(truncate(part, width) for part in line_parts)
    return wrapped[-max_lines:]


def _task_content_height(tasks: list[RenderTask], width: int, fallback_hint: Iterable[str]) -> int:
    if width <= 0:
        return 1
    if not tasks:
        return max(1, len(list(fallback_hint)))
    total = 0
    for task in tasks:
        checkbox = "[x]" if task.done else "[ ]"
        total += len(_wrap_task_text(f" {checkbox} ", task.text, width))
    return max(1, total)


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
    toolbar_lines = _shortcut_toolbar_lines(version_text, width, max_lines=2)
    if show_help:
        lines = [
            *[line.center(width) for line in CODEXDECK_COMPACT_ART],
            "compact mode",
            "Help",
            "CodexDeck keeps AI_TODO.md visible.",
            "Runtime: M model | F fast | Pe perm",
            *toolbar_lines,
            "made by lyte | https://github.com/MLyte/CodexDeck",
        ]
        if status.prompt:
            lines.insert(3, f"Action required: {status.prompt}")
            lines.insert(4, _prompt_help_line(status, compact=True))
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
        f"Session: {status.session}",
        f"Last run: {status.last_run}",
        *toolbar_lines,
    ]
    if status.message:
        lines.insert(2, status.message)
    if status.prompt:
        label = "Action required"
        lines.insert(3, f"{label}: {status.prompt}")
        lines.insert(4, _prompt_help_line(status, compact=True))
        lines = [line for line in lines if not line.startswith("Last run:")]
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
    prompt_h = 4 if status.prompt else 0
    available_h = max(4, height - 11 - header_h - (prompt_h + 2 if prompt_h else 0))
    task_list = list(tasks)
    task_hint = list(task_panel_hint)
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
    if not show_help:
        desired_task_h = _task_content_height(task_list, content_width - 2, task_hint)
        resized_task_h = max(1, min(task_h, desired_task_h))
        log_h += task_h - resized_task_h
        task_h = resized_task_h

    rendered: list[str] = []
    rendered.append(borders["tl"] + borders["h"] * content_width + borders["tr"])
    if header_lines:
        rendered.extend(borders["v"] + line.center(content_width) + borders["v"] for line in header_lines)
        rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    task_offset = clamp_task_offset(len(task_list), task_h, task_offset)

    task_label = task_range_label(len(task_list), task_h, task_offset)
    rendered.append(borders["v"] + _deck_title(f"TODO PAD · {task_label}", content_width, lamp="▣") + borders["v"])

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
        task_texts = [truncate(line, content_width - 2) for line in task_hint]
    while len(task_texts) < task_h:
        task_texts.append("")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in task_texts[:task_h])

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    output_title = "◉ Codex Output CRT"
    rendered.append(borders["v"] + truncate(output_title, content_width).center(content_width) + borders["v"])
    output_width = content_width - 2
    output_source = list(logs)
    log_texts = (
        [truncate(line, output_width) for line in output_source[:log_h]]
        if show_help
        else _wrap_output_lines(output_source, output_width, log_h)
    )
    while len(log_texts) < log_h:
        if show_help:
            log_texts.append("")
        else:
            log_texts.insert(0, "")
    rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in log_texts)

    rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])
    if prompt_h:
        prompt_title = "Action Required"
        rendered.append(borders["v"] + prompt_title.center(content_width) + borders["v"])
        prompt_width = content_width - 2
        prompt_lines = wrap(
            status.prompt,
            width=max(1, prompt_width),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [""]
        prompt_texts = [truncate(line, prompt_width) for line in prompt_lines[:3]]
        prompt_texts.append(_prompt_help_line(status))
        while len(prompt_texts) < prompt_h:
            prompt_texts.append("")
        rendered.extend(borders["v"] + text.ljust(content_width) + borders["v"] for text in prompt_texts[:prompt_h])
        rendered.append(borders["lm"] + borders["h"] * content_width + borders["rm"])

    rendered.append(borders["v"] + _deck_title("Task Summary Ticket", content_width, lamp="▤") + borders["v"])
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
        f"(Pe)rm: {status.permission} | Aut(o): {_on_off(status.auto_mode)} | Session: {status.session}"
    )
    prefixed_width = max(1, content_width - 7)
    shortcuts_body = _shortcut_toolbar_lines(f"v{status.version or '0.0.0'}", prefixed_width, max_lines=1)[0]
    if len(shortcuts_body) >= prefixed_width and shortcuts_body.endswith("..."):
        shortcuts_line = _shortcut_toolbar_lines(f"v{status.version or '0.0.0'}", content_width, max_lines=1)[0]
    else:
        shortcuts_line = "[KEYS] " + shortcuts_body
    rendered.append(borders["v"] + truncate(status_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["v"] + truncate(runtime_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["v"] + truncate(shortcuts_line, content_width).ljust(content_width) + borders["v"])
    rendered.append(borders["bl"] + borders["h"] * (width - 2) + borders["br"])
    return "\n".join(truncate(line, width) for line in rendered)


def _on_off(value: bool) -> str:
    return "on" if value else "off"
