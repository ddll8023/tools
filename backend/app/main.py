"""创建本地工具 API 应用，统一注册路由、生命周期及异常处理。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.exception_handlers import register_exception_handlers
from app.api.router import router as api_router
from app.lifecycle import lifespan


app = FastAPI(title="工具盒子", version="0.1.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(api_router)
register_exception_handlers(app)
