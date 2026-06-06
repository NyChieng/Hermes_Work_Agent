"""
Work Progress Agent — ReAct 循环，DeepSeek 驱动，三种人格 + 情绪记忆。
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
    find_emails,
    fetch_url,
    get_summary,
    list_tasks,
    query_task,
    read_emails,
    search_web,
    update_task,
)

load_dotenv()

console = Console()

_api_key = os.getenv("DEEPSEEK_API_KEY")
if not _api_key:
    console.print("[bold red]错误：DEEPSEEK_API_KEY 没找到，检查一下 .env 文件。[/bold red]")
    sys.exit(1)

client    = OpenAI(api_key=_api_key, base_url="https://api.deepseek.com")
MODEL     = "deepseek-chat"
MAX_STEPS = 8   # research tasks may need: search → read page → synthesize → answer


# ── 人格切换 ───────────────────────────────────────────────────────────────────

def set_mood(mode: str) -> str:
    if mode not in MOOD_LABELS:
        return f"没有这个模式，可选：{' / '.join(MOOD_LABELS.keys())}"
    save_mood(mode)
    return f"切换到{MOOD_LABELS[mode]}"


# ── 工具分发 ───────────────────────────────────────────────────────────────────

_TOOL_MAP = {
    # Task management
    "get_summary":  lambda a: get_summary(),
    "query_task":   lambda a: query_task(**a),
    "add_task":     lambda a: add_task(**a),
    "update_task":  lambda a: update_task(**a),
    "list_tasks":   lambda a: list_tasks(**a),
    "delete_task":  lambda a: delete_task(**a),
    # Web
    "search_web":   lambda a: search_web(**a),
    "fetch_url":    lambda a: fetch_url(**a),
    # Gmail
    "read_emails":  lambda a: read_emails(**a),
    "find_emails":  lambda a: find_emails(**a),
}


def _call_tool(name: str, args: dict):
    fn = _TOOL_MAP.get(name)
    if fn is None:
        return {"error": f"没这个工具：{name}"}
    try:
        return fn(args)
    except TypeError as exc:
        return {"error": f"参数不对 ({name}): {exc}"}
    except Exception as exc:
        return {"error": str(exc)}


# ── 响应解析 ───────────────────────────────────────────────────────────────────

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


# ── ReAct 主循环 ───────────────────────────────────────────────────────────────

def run_agent(
    user_input: str,
    history: list[dict],
) -> tuple[str, list[dict]]:
    """
    执行一轮对话，返回 (答案, 更新后的历史)。
    每次调用都重新构建系统提示，确保人格切换立即生效。
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

    # MAX_STEPS 超限：强制让 LLM 用已有信息尽力回答
    work_msgs.append({
        "role":    "user",
        "content": "根据目前已有的信息，请直接给出 Final Answer，不要再调用工具了。",
    })
    try:
        final_resp = client.chat.completions.create(
            model=MODEL,
            messages=work_msgs,
            temperature=0.3,
            max_tokens=512,
        )
        final_reply = final_resp.choices[0].message.content
        answer = _final_answer(final_reply) or final_reply
    except Exception:
        answer = "处理时间有点长，能换种方式问我吗？"

    new_history = history + [
        {"role": "user",      "content": user_input},
        {"role": "assistant", "content": answer},
    ]
    return answer, _trim_history(new_history)


def _trim_history(history: list[dict], max_tokens: int = 3000) -> list[dict]:
    """
    按字符数估算 token（每4字符≈1 token），超过 max_tokens 就从头裁剪。
    保证返回的始终是完整的 user/assistant 对。
    """
    while len(history) >= 2:
        total_chars = sum(len(m.get("content", "")) for m in history)
        if total_chars / 4 <= max_tokens:
            break
        history = history[2:]
    return history


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
    _print_mood()
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
