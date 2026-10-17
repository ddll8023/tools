# -*- mode: python ; coding: utf-8 -*-

import json
import shutil
import sys
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


PROJECT_ROOT = Path(SPECPATH).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"

binaries = []
datas = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
hiddenimports.extend(collect_submodules("reportlab.graphics.barcode"))

# 这些包包含 MinerU 的命令行入口、模型加载器和运行时数据；仅依赖静态分析
# 会漏掉动态导入，因此显式收集其子模块和数据。
for package_name in ("mineru", "modelscope", "mtcnnruntime"):
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(package_name)
    except Exception:
        continue
    datas.extend(package_datas)
    binaries.extend(package_binaries)
    hiddenimports.extend(package_hiddenimports)

resource_dir = BACKEND_ROOT / "resources"
if resource_dir.is_dir():
    # 通用资源整体收集，但排除 usb 子树：USB 原生库只从构建暂存目录按平台收集，
    # 避免本机残留或跨平台资源混入产物。
    staged_resources = Path(tempfile.mkdtemp(prefix="toolbox-resources-")) / "resources"
    shutil.copytree(
        resource_dir, staged_resources, symlinks=True, ignore=shutil.ignore_patterns("usb")
    )
    datas.append((str(staged_resources), "resources"))

# USB 原生依赖：仅 macOS 产物收集，路径与 core/config.py 的随包约定一致。
usb_native_dir = PROJECT_ROOT / "build" / "usb-native" / "dist"
if sys.platform == "darwin":
    manifest_path = usb_native_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"缺少 USB 原生依赖清单，未完成分发准备: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["libraries"]:
        library = usb_native_dir / "lib" / entry["file"]
        if not library.is_file():
            raise SystemExit(f"缺少 USB 原生库: {library}")
        binaries.append((str(library), "resources/usb/lib"))
        datas.append((str(usb_native_dir / entry["license"]), "resources/usb/licenses"))
    datas.append((str(usb_native_dir / manifest["notice"]), "resources/usb"))
    datas.append((str(usb_native_dir / manifest["buildInfo"]), "resources/usb"))

# 局域网投送的浏览器页面随应用分发，PyInstaller 不会自动收集包内非 .py 文件。
lan_web_dir = BACKEND_ROOT / "src" / "toolbox_backend" / "modules" / "lan_transfer" / "web"
if lan_web_dir.is_dir():
    datas.append((str(lan_web_dir), "toolbox_backend/modules/lan_transfer/web"))

app_entry = BACKEND_ROOT / "packaging" / "server.py"
a = Analysis(
    [str(app_entry)],
    pathex=[str(BACKEND_ROOT / "src"), str(BACKEND_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="toolbox-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    strip=False,
    upx=False,
    name="backend-runtime",
)
