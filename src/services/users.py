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

    async def list_active_chat_sessions(self, user_id: str) -> list[str]:
        """List active chat session IDs for a user (from short-term memory / Redis)."""
        return await self.short_term_memory.get_active_sessions(user_id)

    async def get_chat_session_messages(self, user_id: str, session_id: str) -> dict[str, Any]:
        """Get stored chat messages for a session (best-effort; may be empty if TTL expired)."""
        ctx = await self.short_term_memory.get_conversation_context(session_id, user_id)
        messages = (ctx or {}).get("context", {}).get("messages") or []
        if not isinstance(messages, list):
            messages = []
        return {"user_id": user_id, "session_id": session_id, "messages": messages}
