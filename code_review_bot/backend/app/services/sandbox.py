"""代码执行沙箱：subprocess 运行 Agent 生成的修复代码，超时强制终止。"""
import subprocess
import sys
import tempfile
from pathlib import Path

from ..config import settings


def run_python_code(code: str, timeout: int | None = None) -> dict:
    """把代码写入临时 .py 文件，用独立进程执行。

    隔离性说明：
    - 独立子进程运行，崩溃不影响主服务
    - timeout 到点 kill，防止死循环
    - 捕获 stdout/stderr/exit_code 全部返回给 Agent
    """
    timeout = timeout or settings.SANDBOX_TIMEOUT
    with tempfile.TemporaryDirectory(prefix="sandbox_") as tmp_dir:
        script = Path(tmp_dir) / "main.py"
        script.write_text(code, encoding="utf-8")

        # WORKAROUND: PyInstaller-free 直接调当前 venv 的 python
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=tmp_dir,
                timeout=timeout,
            )
            return {
                "exit_code": proc.returncode,
                "stdout": (proc.stdout or "")[-4000:],   # 截断防爆上下文
                "stderr": (proc.stderr or "")[-4000:],
                "timed_out": False,
            }
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"[沙箱] 代码执行超过 {timeout} 秒，已被强制终止",
                "timed_out": True,
            }


def format_run_result(result: dict) -> str:
    """把执行结果格式化为可读文本，供 ToolMessage 使用。"""
    parts = [f"退出码: {result['exit_code']}"]
    if result.get("timed_out"):
        parts.append("状态: 超时终止")
    if result["stdout"].strip():
        parts.append(f"标准输出:\n{result['stdout']}")
    if result["stderr"].strip():
        parts.append(f"错误输出:\n{result['stderr']}")
    if not result["stdout"].strip() and not result["stderr"].strip():
        parts.append("（无输出）")
    return "\n\n".join(parts)
