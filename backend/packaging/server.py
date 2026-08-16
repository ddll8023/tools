"""PyInstaller 入口：启动 FastAPI 后端，或复用自身执行 MinerU CLI。"""

from __future__ import annotations

import multiprocessing
import os
import sys


def _run_mineru() -> None:
    """在打包后的同一运行时中执行 MinerU 命令行入口。"""
    sys.argv.remove("--toolbox-mineru")
    from mineru.cli.client import main as mineru_main

    raise SystemExit(mineru_main())


def main() -> None:
    if "--toolbox-mineru" in sys.argv:
        _run_mineru()
        return

    # Windows 的 ProcessPoolExecutor 需要此调用才能在 frozen 进程中安全派生。
    multiprocessing.freeze_support()

    import uvicorn
    from app.main import app

    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "4740")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
