"""PyInstaller 入口：启动 FastAPI，或复用自身执行 MinerU CLI 与 USB 工作进程。"""

from __future__ import annotations

import multiprocessing
import os
import sys


def _run_mineru() -> None:
    """在打包后的同一运行时中执行 MinerU 命令行入口。"""
    sys.argv.remove("--toolbox-mineru")
    from mineru.cli.client import main as mineru_main

    raise SystemExit(mineru_main())


def _run_mineru_models() -> None:
    """在打包后的同一运行时中执行 MinerU 模型下载入口。"""
    sys.argv.remove("--toolbox-mineru-models")
    from mineru.cli.models_download import download_models

    raise SystemExit(download_models())


def _run_usb_worker() -> None:
    """在打包后的同一运行时中执行 USB 工作进程。"""
    sys.argv.remove("--toolbox-usb-worker")
    from toolbox_backend.modules.usb_transfer.worker import main as worker_main

    raise SystemExit(worker_main())


def main() -> None:
    if "--toolbox-mineru" in sys.argv:
        _run_mineru()
        return

    if "--toolbox-mineru-models" in sys.argv:
        _run_mineru_models()
        return

    if "--toolbox-usb-worker" in sys.argv:
        _run_usb_worker()
        return

    # Windows 的 ProcessPoolExecutor 需要此调用才能在 frozen 进程中安全派生。
    multiprocessing.freeze_support()

    import uvicorn
    from toolbox_backend.main import app

    uvicorn.run(
        app,
        host=os.environ.get("API_HOST", "127.0.0.1"),
        port=int(os.environ.get("API_PORT", "18740")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
