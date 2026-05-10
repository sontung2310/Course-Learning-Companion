from fastapi import APIRouter, Depends, status
from src.dependencies.users import get_users_service
from src.schemas.users import UserProfileInput
from src.services.users import Users
from typing import Optional, Dict, Any, List

router = APIRouter()


@router.post(
    "/user-profile",
    status_code=status.HTTP_201_CREATED,
    response_model=Dict[str, Any],
)
async def create_user_profile(
    input: UserProfileInput,
    users_service: Users = Depends(get_users_service),
):
    """Create or update a user profile for personalized learning."""
    profile = await users_service.create_user_profile(
        user_id=input.user_id,
        name=input.name,
        course_intake=input.course_intake,
        interests=input.interests,
    )

    return profile


@router.get(
    "/user-profile/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=Optional[Dict[str, Any]],
)
async def get_user_profile(
    user_id: str,
    users_service: Users = Depends(get_users_service),
):
    """Get user profile by user_id."""
    profile = await users_service.get_user_profile(user_id)
    return profile


@router.delete(
    "/clear-session/{user_id}",
    status_code=status.HTTP_200_OK,
)
async def clear_user_session(
    user_id: str,
    users_service: Users = Depends(get_users_service),
):
    """Clear user's short-term memory cache."""
    success = await users_service.clear_user_session(user_id)
    return {"success": success, "message": "User session cleared"}


@router.get(
    "/chat-sessions/{user_id}",
    status_code=status.HTTP_200_OK,
    response_model=List[Dict[str, str]],
)
async def list_active_chat_sessions(
    user_id: str,
    users_service: Users = Depends(get_users_service),
):
    """List active chat session IDs for a user (from short-term memory / Redis)."""
    return await users_service.list_active_chat_sessions(user_id)


@router.get(
    "/chat-sessions/{user_id}/{session_id}",
    status_code=status.HTTP_200_OK,
    response_model=Dict[str, Any],
)
async def get_chat_session_messages(
    user_id: str,
    session_id: str,
    users_service: Users = Depends(get_users_service),
):
    """Get stored chat messages for a session (best-effort; may be empty if TTL expired)."""
    return await users_service.get_chat_session_messages(user_id=user_id, session_id=session_id)
