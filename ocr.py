"""
OCR 模块 — 用 Google Gemini Flash 从图片中提取任务列表。

依赖 google-generativeai 包和 GEMINI_API_KEY 环境变量。
未配置时优雅降级，不会崩溃。
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

_OCR_PROMPT = """请仔细分析这张图片，找出所有的任务、待办事项、工作项目或清单内容。

返回 **严格的 JSON 数组**，不要有任何额外文字或 markdown 代码块：
[
  {
    "name": "任务名称（简洁，一句话）",
    "priority": "high 或 medium 或 low",
    "deadline": "YYYY-MM-DD 格式，图中有日期才填，否则空字符串",
    "notes": "补充说明或上下文，没有就空字符串"
  }
]

判断规则：
- name 必须是具体的任务，不是标题或分类
- priority：有截止日期/紧急字眼 → high，普通任务 → medium，无明确要求 → low
- 如果图中没有任何任务，返回空数组 []
- 不要自己编任务，只提取图中确实存在的内容"""


def extract_tasks_from_image(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> list[dict] | str:
    """
    将图片发给 Gemini Flash，提取任务列表。

    返回值：
      - 成功：[{"name": "", "priority": "", "deadline": "", "notes": ""}]
      - 失败：错误说明字符串

    GEMINI_API_KEY 未配置时返回提示字符串，不抛异常。
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return "GEMINI_API_KEY 未配置，无法进行图片识别。请在 .env 中填写该值。"

    try:
        import google.generativeai as genai
    except ImportError:
        return "google-generativeai 包未安装，请运行：pip install google-generativeai"

    try:
        import base64
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        image_part = {
            "inline_data": {
                "mime_type": mime_type,
                "data": base64.b64encode(image_bytes).decode("utf-8"),
            }
        }

        response = model.generate_content(
            contents=[{"role": "user", "parts": [image_part, {"text": _OCR_PROMPT}]}]
        )

        text = (response.text or "").strip()

        # 清理可能的 markdown 代码块包裹
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉首尾的 ``` 行
            start = 1
            end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
            text  = "\n".join(lines[start:end])

        tasks = json.loads(text)
        if not isinstance(tasks, list):
            return "识别结果格式不对，请重试。"

        # 规范化每个任务字段
        cleaned = []
        for t in tasks:
            if not isinstance(t, dict) or not t.get("name"):
                continue
            cleaned.append({
                "name":     str(t.get("name", "")).strip()[:100],
                "priority": t.get("priority", "medium") if t.get("priority") in ("high", "medium", "low") else "medium",
                "deadline": str(t.get("deadline", "")).strip()[:10],
                "notes":    str(t.get("notes", "")).strip()[:200],
            })
        return cleaned

    except json.JSONDecodeError:
        logger.warning("OCR 返回内容无法解析为 JSON")
        return "图片识别完成，但结果格式异常，请换一张图片或重试。"
    except Exception as exc:
        logger.warning("OCR 识别失败: %s", exc)
        return f"图片识别失败：{exc}"
