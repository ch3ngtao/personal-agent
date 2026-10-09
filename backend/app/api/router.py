"""聚合所有子路由。"""

from fastapi import APIRouter

from app.api.routes import chat, embeddings, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(embeddings.router)
api_router.include_router(chat.router)
