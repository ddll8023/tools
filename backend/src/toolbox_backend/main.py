"""创建本地工具 API 应用，统一注册中间件、路由、生命周期及异常处理。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from toolbox_backend.api.control_auth_middleware import ControlAuthMiddleware
from toolbox_backend.api.exception_handlers import register_exception_handlers
from toolbox_backend.api.router import router as api_router
from toolbox_backend.lifecycle import lifespan


app = FastAPI(title="工具盒子", version="0.1.0", lifespan=lifespan)

# 注册顺序决定包装顺序：后注册的中间件位于外层，因此 CORS 先处理预检，
# 认证中间件只看到已经过来源判定的请求。
app.add_middleware(ControlAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    # 仅信任桌面外壳的两种来源：开发态的 Vite 地址与打包态的 file:// 空来源。
    allow_origins=["http://127.0.0.1:5173", "null"],
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    expose_headers=["Content-Disposition", "X-Missing-Assets"],
)

app.include_router(api_router)
register_exception_handlers(app)
