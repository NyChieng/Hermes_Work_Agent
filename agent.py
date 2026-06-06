"""
Work Progress Agent — SQLite + summary-cache + memory edition.
Hermes-style ReAct loop with dynamic persona and emotional memory.
"""

import json
import os
import re
import sys

from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule

from cache import get_cached_summary
from db import get_mood, save_mood
from memory import build_memory_block, get_memory_context
from prompts import MOOD_LABELS, get_system_prompt
from tools import (
    add_task,
    delete_task,
    get_summary,
    list_tasks,
    query_task,
    update_task,
)

load_dotenv()

console = Console()

_api_key = os.getenv("DEEPSEEK_API_KEY")
if not _api_key:
    console.print("[bold red]错误：未找到 DEEPSEEK_API_KEY，请检查 .env 文件。[/bold red]")
    sys.exit(1)

client    = OpenAI(api_key=_api_key, base_url="https://api.deepseek.com")
MODEL     = "deepseek-chat"
MAX_STEPS = 5


# ── mood management ───────────────────────────────────────────────────────────

def set_mood(mode: str) -> str:
    if mode not in MOOD_LABELS:
        return f"没有这个模式，可选：{' / '.join(MOOD_LABELS.keys())}"
    save_mood(mode)
    return f"切换到{MOOD_LABELS[mode]}"


# ── tool dispatch ─────────────────────────────────────────────────────────────

_TOOL_MAP = {
    "get_summary":  lambda a: get_summary(),
    "query_task":   lambda a: query_task(**a),
    "add_task":     lambda a: add_task(**a),
    "update_task":  lambda a: update_task(**a),
    "list_tasks":   lambda a: list_tasks(**a),
    "delete_task":  lambda a: delete_task(**a),
}


def _call_tool(name: str, args: dict):
    fn = _TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"未知工具：{name}"}
    try:
        return fn(args)
    except TypeError as exc:
        return {"error": f"参数错误 ({name}): {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


# ── response parsing ──────────────────────────────────────────────────────────

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_THOUGHT_RE   = re.compile(
    r"Thought:\s*(.+?)(?=\nAction\b|\nFinal Answer\b|<tool_call|\Z)", re.DOTALL
)
_FINAL_ANS_RE = re.compile(r"Final Answer:\s*(.+)", re.DOTALL)


def _parse_tool_call(text: str) -> dict | None:
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _thought(text: str) -> str:
    m = _THOUGHT_RE.search(text)
    return m.group(1).strip() if m else ""


def _final_answer(text: str) -> str:
    m = _FINAL_ANS_RE.search(text)
    return m.group(1).strip() if m else ""


# ── ReAct loop ────────────────────────────────────────────────────────────────

def run_agent(
    user_input: str,
    history: list[dict],
) -> tuple[str, list[dict]]:
    """
    Execute one user turn.  Returns (answer, updated_history).
    Persona + memory are rebuilt each call so changes take effect immediately.
    """
    mood         = get_mood()
    memory_block = build_memory_block(get_memory_context())
    system       = get_system_prompt(mood, memory_block)

    summary = get_cached_summary()
    context_msg = (
        f"[当前进度摘要]\n{json.dumps(summary, ensure_ascii=False, indent=2)}\n\n"
        f"用户：{user_input}"
    )

    work_msgs: list[dict] = (
        [{"role": "system", "content": system}]
        + history
        + [{"role": "user", "content": context_msg}]
    )

    for _ in range(MAX_STEPS):
        response = client.chat.completions.create(
            model=MODEL,
            messages=work_msgs,
            temperature=0.3,
            max_tokens=1024,
        )
        reply = response.choices[0].message.content

        t = _thought(reply)
        if t:
            console.print(f"[bold yellow]\\[Thought][/bold yellow] {t}")

        fa = _final_answer(reply)
        if fa:
            work_msgs.append({"role": "assistant", "content": reply})
            new_history = history + [
                {"role": "user",      "content": user_input},
                {"role": "assistant", "content": fa},
            ]
            return fa, _trim_history(new_history)

        call = _parse_tool_call(reply)
        if call:
            name = call.get("name", "")
            args = call.get("arguments", {})
            args_display = ", ".join(f"{k}={v!r}" for k, v in args.items())
            console.print(f"[bold blue]\\[Action][/bold blue] {name}({args_display})")

            result     = _call_tool(name, args)
            result_str = json.dumps(result, ensure_ascii=False)
            display    = result_str if len(result_str) <= 200 else result_str[:197] + "…"
            console.print(f"[bold green]\\[Observation][/bold green] {display}")

            work_msgs.append({"role": "assistant", "content": reply})
            work_msgs.append({
                "role":    "user",
                "content": f"<tool_response>\n{result_str}\n</tool_response>",
            })
            continue

        work_msgs.append({"role": "assistant", "content": reply})
        new_history = history + [
            {"role": "user",      "content": user_input},
            {"role": "assistant", "content": reply},
        ]
        return reply, _trim_history(new_history)

    return "⚠️ 已达最大推理步数，请重新描述您的需求。", history


def _trim_history(history: list[dict], max_turns: int = 6) -> list[dict]:
    return history[-(max_turns * 2):]


# ── CLI ───────────────────────────────────────────────────────────────────────

def _print_summary(s: dict) -> None:
    lines = [
        f"  总任务：[bold]{s['total']}[/bold]  完成率：[bold]{s['completion_rate']}[/bold]",
        f"  ✅ {s['done']}  🟡 {s['in_progress']}  🔴 {s['blocked']}  ⬜ {s['todo']}",
    ]
    if s["top3_urgent"]:
        lines.append("  ⚡ 高优先：" + " / ".join(t["name"] for t in s["top3_urgent"]))
    console.print(Panel("\n".join(lines), title="当前进度", border_style="dim cyan", padding=(0, 1)))


def _print_mood() -> None:
    mode  = get_mood()
    label = MOOD_LABELS.get(mode, mode)
    opts  = "  ".join(
        f"[bold]{k}[/bold]" if k == mode else k for k in MOOD_LABELS
    )
    console.print(f"[dim]当前人格：{label}  可选：{opts}[/dim]")


def main() -> None:
    console.print(
        Panel.fit(
            "[bold cyan]🤖 工作进度 Agent[/bold cyan]\n"
            "[dim]'quit' 退出  |  'summary' 进度  |  '/mood <friend|drill|boss>' 切换人格[/dim]",
            border_style="cyan",
        )
    )
    _print_summary(get_cached_summary())
    _print_mood_status = _print_mood
    _print_mood_status()
    console.print()

    history: list[dict] = []

    while True:
        try:
            user_input = console.input("[bold]你:[/bold] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见！[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "退出"):
            console.print("[dim]再见！[/dim]")
            break
        if user_input.lower() in ("summary", "进度"):
            _print_summary(get_cached_summary())
            continue
        if user_input.startswith("/mood"):
            parts = user_input.split()
            mode  = parts[1].strip() if len(parts) > 1 else ""
            if not mode:
                _print_mood()
            else:
                console.print(f"[dim]{set_mood(mode)}[/dim]")
            continue

        console.print()
        answer, history = run_agent(user_input, history)
        console.print(f"\n[bold green]Agent:[/bold green] {answer}")
        console.print(Rule(style="dim"))


if __name__ == "__main__":
    main()
