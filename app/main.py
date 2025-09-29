from __future__ import annotations

import logging
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.routers import api
from app.core.config import SETTINGS

logger = logging.getLogger(__name__)

def create_app() -> FastAPI:
    app = FastAPI(
        title="AI-Ops 巡检系统",
        description="自动化运维巡检系统Web界面",
        version="1.0.0"
    )
    
    # 添加压缩与CORS中间件
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态资源
    try:
        app.mount("/static", StaticFiles(directory="static"), name="static")
    except Exception:
        # 目录不存在时忽略
        pass

    @app.on_event("startup")
    async def _on_startup():
        # 确保数据库表结构存在（兼容首次启动/升级）
        try:
            from app.models.db import init_schema
            init_schema()
            logger.info("数据库表结构初始化完成")
        except Exception as e:
            logger.warning(f"数据库表结构初始化失败: {e}")

    # 注册API路由
    app.include_router(api.router)

    # 主页面路由
    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        """主仪表板页面"""
        try:
            with open("static/dashboard.html", "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content)
        except FileNotFoundError:
            return HTMLResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>AI-Ops 巡检系统</title>
                <meta charset="utf-8">
            </head>
            <body>
                <h1>AI-Ops 巡检系统</h1>
                <p>系统正在启动中，请稍后刷新页面...</p>
                <p><a href="/docs">API文档</a></p>
            </body>
            </html>
            """)

    @app.get("/reports", response_class=HTMLResponse)
    async def reports():
        """巡检报告页面"""
        try:
            with open("static/reports.html", "r", encoding="utf-8") as f:
                content = f.read()
            return HTMLResponse(content=content)
        except FileNotFoundError:
            return HTMLResponse("""
            <!DOCTYPE html>
            <html>
            <head>
                <title>巡检报告 - AI-Ops</title>
                <meta charset="utf-8">
            </head>
            <body>
                <h1>巡检报告</h1>
                <p>报告页面正在开发中...</p>
                <p><a href="/">返回主页</a></p>
            </body>
            </html>
            """)

    return app

# 创建应用实例
app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
