"""视觉服务：用 qwen-vl-max-latest 从报错截图中提取错误信息。"""
import base64
from pathlib import Path

from openai import OpenAI

from ..config import settings


def extract_error_from_image(image_path: str) -> str:
    """读取本地截图，转 base64 data URL，交给 VL 模型提取报错文本。"""
    data = Path(image_path).read_bytes()
    ext = Path(image_path).suffix.lower().lstrip(".")
    if ext == "jpg":
        ext = "jpeg"
    b64 = base64.b64encode(data).decode("utf-8")
    data_url = f"data:image/{ext};base64,{b64}"

    client = OpenAI(
        api_key=settings.DASHSCOPE_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )
    resp = client.chat.completions.create(
        model=settings.LLM_VL_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {
                        "type": "text",
                        "text": (
                            "这是一个代码报错截图。请完整、逐字提取图中的报错信息"
                            "（包括异常类型、错误消息、Traceback 堆栈、涉及的文件与行号），"
                            "以纯文本输出，不要添加任何分析或解释。"
                        ),
                    },
                ],
            }
        ],
    )
    return resp.choices[0].message.content or ""
