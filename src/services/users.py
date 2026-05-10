from src.services.memory import LongTermMemoryService, ShortTermMemoryService
from typing import Optional, Any


class Users:
    def __init__(self):
        self.long_term_memory = LongTermMemoryService()
        self.short_term_memory = ShortTermMemoryService()

    async def create_user_profile(
        self,
        user_id: str,
        name: str,
        course_intake: list,
        interests: Optional[list] = None,
    ):
        """Create or update a user profile for personalized learning."""
        profile_data = {
            "name": name,
            "course_intake": course_intake,
            "interests": interests or [],
        }

        await self.long_term_memory.create_or_update_user_profile(user_id, profile_data)
        return profile_data

    async def get_user_profile(self, user_id: str):
        """Get user profile for personalization."""
        return await self.long_term_memory.get_user_profile(user_id)

    async def clear_user_session(self, user_id: str):
        """Clear user's short-term memory cache."""
        return await self.short_term_memory.clear_user_cache(user_id)

    async def list_active_chat_sessions(self, user_id: str) -> list[dict[str, str]]:
        """List all chat sessions for a user with their titles from long-term memory (Postgres)."""
        return await self.long_term_memory.get_all_sessions_with_metadata(user_id)

    async def get_chat_session_messages(self, user_id: str, session_id: str) -> dict[str, Any]:
        """Get stored chat messages for a session from long-term memory (Postgres)."""
        messages = await self.long_term_memory.get_chat_history(user_id=user_id, session_id=session_id)
        return {"user_id": user_id, "session_id": session_id, "messages": messages}
