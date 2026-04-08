"""
S001-Pro Monitor Backend
FastAPI主应用
"""
import asyncio
import time
import uuid
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import logging
import os

from .config import get_settings
from .database import init_monitor_db
from .routers import summary, positions, orders, logs, charts, share, websocket, alerts, auth

settings = get_settings()

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Starting S001-Pro Monitor...")
    init_monitor_db()
    
    # 初始化警报表
    from .routers.alerts import init_alert_tables
    init_alert_tables()
    
    # 注册WebSocket路由
    from .routers import websocket as ws_router
    app.include_router(ws_router.router)
    
    logger.info(f"Server running on http://{settings.HOST}:{settings.PORT}")
    
    # 启动警报检查任务
    from .routers.alerts import alert_checker
    
    async def alert_check_loop():
        """定期执行警报检查"""
        while True:
            try:
                await alert_checker.check_all_rules()
            except Exception as e:
                logger.error(f"Alert check error: {e}")
            await asyncio.sleep(30)  # 每30秒检查一次
    
    # 启动后台任务
    task = asyncio.create_task(alert_check_loop())
    
    yield
    
    # 关闭时
    task.cancel()
    logger.info("Shutting down...")


app = FastAPI(
    title="S001-Pro Monitor",
    description="S001-Pro 策略实时监控面板",
    version="1.0.0",
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 性能监控中间件
@app.middleware("http")
async def performance_monitor(request: Request, call_next):
    """记录API性能"""
    start_time = time.time()
    request_id = str(uuid.uuid4())[:8]
    
    # 添加request_id到请求状态
    request.state.request_id = request_id
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    response.headers["X-Response-Time"] = f"{duration:.3f}s"
    response.headers["X-Request-ID"] = request_id
    
    # 记录慢查询
    if duration > 0.5:
        logger.warning(f"Slow API [{request_id}]: {request.url.path} took {duration:.2f}s")
    
    return response


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    request_id = getattr(request.state, 'request_id', 'unknown')
    
    logger.error(f"Request {request_id}: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "服务器内部错误",
                "timestamp": datetime.utcnow().isoformat(),
                "request_id": request_id
            }
        }
    )


# 健康检查
@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "success": True,
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0"
    }


# 注册路由
app.include_router(auth.router, prefix="/api", tags=["auth"])  # 登录认证
app.include_router(summary.router, prefix="/api", tags=["summary"])
app.include_router(positions.router, prefix="/api", tags=["positions"])
app.include_router(orders.router, prefix="/api", tags=["orders"])
app.include_router(logs.router, prefix="/api", tags=["logs"])
app.include_router(charts.router, prefix="/api", tags=["charts"])
app.include_router(share.router, tags=["share"])  # 分享功能
app.include_router(alerts.router, prefix="/api", tags=["alerts"])  # 警报系统
# WebSocket 路由在lifespan中处理

# 静态文件目录 (从 backend/app/main.py 定位到 monitor/frontend/dist)
# __file__ = backend/app/main.py -> dirname = backend/app -> dirname = backend
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend", "dist")

# 挂载静态文件
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")
    logger.info(f"Static files mounted from {STATIC_DIR}")
else:
    logger.warning(f"Static files directory not found: {STATIC_DIR}")


@app.get("/")
async def root():
    """根路径 - 返回前端页面"""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {
        "name": "S001-Pro Monitor",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "note": "Frontend not built"
    }


# 前端路由支持 - 所有非API路由返回index.html
@app.get("/{full_path:path}")
async def catch_all(full_path: str):
    """捕获所有路由，支持前端SPA"""
    # 排除API和静态资源路径
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse(status_code=404, content={"detail": "Frontend not built"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
