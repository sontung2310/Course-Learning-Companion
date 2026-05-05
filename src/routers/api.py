from fastapi import APIRouter
from src.routers import agents, users, reports

api_router = APIRouter()
api_router.include_router(users.router, prefix="/users", tags=["User Management"])
api_router.include_router(agents.router, prefix="/agents", tags=["Agent Orchestrator"])
api_router.include_router(reports.router, prefix="/reports", tags=["Reports"])
