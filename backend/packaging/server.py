"""PyInstaller 入口：启动 FastAPI，或复用自身执行 MinerU CLI、USB 工作进程与更新守卫。"""

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

def _run_update_guard() -> None:
    """更新安装期间只持有应用所有权，不启动 API、恢复记录或访问设备。"""
    sys.argv.remove("--toolbox-update-guard")
    from toolbox_backend.core.runtime import run_update_guard

    raise SystemExit(run_update_guard())


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

    if "--toolbox-update-guard" in sys.argv:
        _run_update_guard()
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
