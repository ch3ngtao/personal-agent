"""聚合所有子路由。"""

from fastapi import APIRouter

from app.api.routes import agent, chat, embeddings, faq, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(embeddings.router)
api_router.include_router(chat.router)
api_router.include_router(faq.router)
api_router.include_router(agent.router)
