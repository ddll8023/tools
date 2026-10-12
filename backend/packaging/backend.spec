# -*- mode: python ; coding: utf-8 -*-

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
    datas.append((str(resource_dir), "resources"))

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
