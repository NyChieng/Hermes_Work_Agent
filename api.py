"""
FastAPI 后端 — REST 接口 + SSE 流式聊天。
所有路由（除 /api/login 和 /）都需要 X-Auth-Token 请求头。
"""

import asyncio
import csv
import io
import json
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Hermes Work Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

UI_PASSWORD = os.getenv("UI_PASSWORD", "changeme")


# ── 认证 ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    password: str


@app.post("/api/login")
def login(req: LoginRequest):
    if req.password != UI_PASSWORD:
        raise HTTPException(status_code=401, detail="密码错误")
    return {"ok": True, "token": UI_PASSWORD}


def _verify(request: Request) -> None:
    token = (
        request.headers.get("X-Auth-Token", "")
        or request.query_params.get("_t", "")
    )
    if token != UI_PASSWORD:
        raise HTTPException(status_code=401, detail="未授权")


# ── 摘要 ──────────────────────────────────────────────────────────────────────

@app.get("/api/summary")
def api_summary(request: Request):
    _verify(request)
    from tools import get_summary
    return get_summary()


# ── 任务 CRUD ─────────────────────────────────────────────────────────────────

@app.get("/api/tasks")
def api_list_tasks(
    request: Request,
    status: str | None = None,
    priority: str | None = None,
    limit: int = 100,
):
    _verify(request)
    from tools import list_tasks
    return list_tasks(status=status or None, priority=priority or None, limit=limit)


class AddTaskBody(BaseModel):
    name: str
    priority: str = "medium"
    notes: str = ""
    tags: str = ""
    deadline: str = ""


@app.post("/api/tasks")
def api_add_task(request: Request, body: AddTaskBody):
    _verify(request)
    from tools import add_task
    result = add_task(
        name=body.name,
        priority=body.priority,
        notes=body.notes,
        tags=body.tags,
        deadline=body.deadline,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


class UpdateTaskBody(BaseModel):
    status: str | None = None
    notes: str | None = None
    priority: str | None = None
    deadline: str | None = None


@app.patch("/api/tasks/{task_name}")
def api_update_task(request: Request, task_name: str, body: UpdateTaskBody):
    _verify(request)
    from tools import update_task
    return update_task(
        name=task_name,
        status=body.status,
        notes=body.notes,
        priority=body.priority,
        deadline=body.deadline,
    )


@app.delete("/api/tasks/{task_name}")
def api_delete_task(request: Request, task_name: str):
    _verify(request)
    from tools import delete_task
    result = delete_task(name=task_name)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── 聊天（SSE 流式）───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    history: list = []


@app.post("/api/chat")
async def api_chat(request: Request, body: ChatRequest):
    _verify(request)

    async def generate():
        loop = asyncio.get_event_loop()
        from agent import run_agent
        try:
            answer, _ = await loop.run_in_executor(
                None, run_agent, body.message, body.history
            )
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return

        for char in answer:
            yield f"data: {json.dumps({'char': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.02)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── 人格 ──────────────────────────────────────────────────────────────────────

@app.get("/api/mood")
def api_get_mood(request: Request):
    _verify(request)
    from db import get_mood
    from prompts import MOOD_LABELS
    mode = get_mood()
    return {"mode": mode, "label": MOOD_LABELS.get(mode, mode)}


@app.post("/api/mood/{mode}")
def api_set_mood(request: Request, mode: str):
    _verify(request)
    from agent import set_mood
    return {"message": set_mood(mode)}


# ── Notion ────────────────────────────────────────────────────────────────────

@app.get("/api/notion/status")
def api_notion_status(request: Request):
    _verify(request)
    from db import get_notion_ids
    db_id, _ = get_notion_ids()
    if not db_id:
        return {"configured": False}
    clean = db_id.replace("-", "")
    return {
        "configured": True,
        "url": f"https://www.notion.so/{clean}",
        "db_id": db_id,
    }


@app.post("/api/notion/sync")
async def api_notion_sync(request: Request):
    _verify(request)
    loop = asyncio.get_event_loop()
    from scheduler import trigger_notion_pull_now, trigger_notion_push_all
    pulled = await loop.run_in_executor(None, trigger_notion_pull_now)
    pushed = await loop.run_in_executor(None, trigger_notion_push_all)
    return {"pulled": pulled, "pushed": pushed}


# ── 记忆 / Streak ─────────────────────────────────────────────────────────────

@app.get("/api/memory")
def api_memory(request: Request):
    _verify(request)
    from memory import get_memory_context
    return get_memory_context()


# ── 周报 ──────────────────────────────────────────────────────────────────────

@app.post("/api/weekly")
async def api_weekly(request: Request):
    _verify(request)
    loop = asyncio.get_event_loop()
    from memory import build_weekly_report
    report = await loop.run_in_executor(None, build_weekly_report)
    return {"report": report}


# ── OCR 图片识别 ──────────────────────────────────────────────────────────────

@app.post("/api/ocr")
async def api_ocr(request: Request, file: UploadFile = File(...)):
    """
    接收 multipart/form-data 图片，调用 Gemini 识别任务，返回任务草稿 JSON。
    """
    _verify(request)
    raw      = await file.read()
    filename = file.filename or "image"
    mime     = file.content_type or "image/jpeg"

    # 仅允许图片
    if not mime.startswith("image/"):
        raise HTTPException(400, "只支持图片文件（jpg/png/webp 等）")

    from ocr import extract_tasks_from_image
    result = extract_tasks_from_image(raw, mime_type=mime)

    if isinstance(result, str):
        # 错误信息
        raise HTTPException(400, result)

    return {"tasks": result, "count": len(result)}


# ── 根路由 → SPA ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    index = _STATIC / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"status": "Hermes Work Agent API 运行中"}


# ── 文件上传（PDF / 文本）──────────────────────────────────────────────────────

@app.post("/api/upload")
async def api_upload(request: Request, file: UploadFile = File(...)):
    _verify(request)
    raw      = await file.read()
    filename = file.filename or "file"

    if filename.lower().endswith(".pdf"):
        try:
            import pypdf
            reader  = pypdf.PdfReader(io.BytesIO(raw))
            content = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise HTTPException(400, "PDF 支持未安装，请运行: pip install pypdf")
        except Exception as exc:
            raise HTTPException(400, f"PDF 读取失败: {exc}")
    else:
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise HTTPException(400, "不支持此格式，请上传文本文件或 PDF")

    return {"filename": filename, "content": content[:8000], "truncated": len(content) > 8000}


# ── 导出 ──────────────────────────────────────────────────────────────────────

@app.get("/api/export/csv")
def api_export_csv(request: Request):
    _verify(request)
    from tools import list_tasks

    tasks = list_tasks(limit=500)
    buf   = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["name", "status", "priority", "notes", "tags", "deadline", "updated"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(tasks)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tasks.csv"},
    )


@app.get("/api/export/md")
def api_export_md(request: Request):
    _verify(request)
    from tools import list_tasks

    sections = {
        "in_progress": ("🟡 进行中", False),
        "blocked":     ("🔴 阻塞",   False),
        "todo":        ("⬜ 未开始", False),
        "done":        ("✅ 已完成", True),
    }
    lines = ["# 工作进度\n"]
    for status, (heading, checked) in sections.items():
        tasks = list_tasks(status=status, limit=200)
        if not tasks:
            continue
        lines.append(f"## {heading}\n")
        for t in tasks:
            box  = "[x]" if checked else "[ ]"
            safe = t['name'].replace('*', r'\*').replace('[', r'\[').replace(']', r'\]')
            note = f" — {t['notes']}" if t.get("notes") else ""
            dl   = f" ⏰{t['deadline']}" if t.get("deadline") else ""
            lines.append(f"- {box} **{safe}**{note}{dl}")
        lines.append("")

    return Response(
        content="\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=tasks.md"},
    )


# ── 任务专属聊天（SSE）────────────────────────────────────────────────────────

class TaskChatRequest(BaseModel):
    message: str
    history: list = []


@app.post("/api/chat/task/{task_name}")
async def api_chat_task(request: Request, task_name: str, body: TaskChatRequest):
    _verify(request)

    from tools import query_task
    results = query_task(task_name)
    task    = next((t for t in results if t["name"] == task_name), None)
    if not task:
        task = results[0] if results else {
            "name": task_name, "status": "", "priority": "",
            "notes": "", "tags": "", "deadline": "",
        }

    context_prefix = (
        f"[任务上下文] 当前任务：{task.get('name','')} | "
        f"状态：{task.get('status','')} | "
        f"优先级：{task.get('priority','')} | "
        f"截止：{task.get('deadline','') or '未设置'} | "
        f"备注：{task.get('notes','')} | "
        f"标签：{task.get('tags','')}\n\n"
    )
    enriched_message = context_prefix + body.message

    async def generate():
        loop = asyncio.get_event_loop()
        from agent import run_agent
        try:
            answer, _ = await loop.run_in_executor(
                None, run_agent, enriched_message, body.history
            )
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"
            return

        for char in answer:
            yield f"data: {json.dumps({'char': char}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.02)
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
