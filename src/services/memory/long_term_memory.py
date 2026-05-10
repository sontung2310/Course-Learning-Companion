"""Long-term memory service using PostgreSQL for persistent storage."""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from sqlalchemy import Column, String, Text, Integer, ForeignKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.future import select
from pgvector.sqlalchemy import Vector
from src.settings import SETTINGS
from sqlalchemy.orm import mapped_column

Base = declarative_base()

class UserProfile(Base):
    """User profile table for storing learning preferences and history."""

    __tablename__ = "user_profiles"

    user_id = Column(String, primary_key=True)
    name = Column(String)
    course_intake = Column(JSONB)  # List of intaking courses
    interests = Column(JSONB)  # List of subjects/topics
    created_at = Column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ChatMessage(Base):
    """Table for storing chat history with vector embeddings for semantic search."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    session_id = Column(String, index=True)
    role = Column(String)  # 'user' or 'assistant'
    content = Column(Text)
    embedding = Column(Vector(1536))  # OpenAI embedding dimension (text-embedding-3-small)
    created_at = Column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ChatSession(Base):
    """Table for storing chat session metadata like titles."""

    __tablename__ = "chat_sessions"

    session_id = Column(String, primary_key=True)
    user_id = Column(String, index=True)
    title = Column(String)
    created_at = Column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )



class LongTermMemoryService:
    """Service for managing long-term memory using PostgreSQL."""

    def __init__(self):
        # Use DATABASE_URL if provided, otherwise construct it
        if SETTINGS.DATABASE_URL:
            self.database_url = SETTINGS.DATABASE_URL
        else:
            password = SETTINGS.POSTGRES_PASSWORD.get_secret_value()
            self.database_url = (
                f"postgresql+asyncpg://{SETTINGS.POSTGRES_USER}:{password}@"
                f"{SETTINGS.POSTGRES_HOST}:{SETTINGS.POSTGRES_PORT}/{SETTINGS.POSTGRES_DB}"
            )
        
        print(f"Database URL: {self.database_url}")  # Debugging line
        # Create async engine and session
        self.engine = create_async_engine(self.database_url)
        self.async_session = async_sessionmaker(self.engine, class_=AsyncSession)
        print(f"Engine: {self.engine}")  # Debugging line

    async def create_tables(self):
        """Create tables if they don't exist."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def initialize(self):
        """Initialize the service by creating tables and extensions."""
        async with self.engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await self.create_tables()

    async def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for the given text using LiteLLM."""
        import litellm

        try:
            response = await litellm.aembedding(
                model="text-embedding-3-small",
                input=[text],
                api_base=SETTINGS.OPENAI_BASE_URL,
                api_key=SETTINGS.OPENAI_API_KEY.get_secret_value(),
            )
            return response.data[0]["embedding"]
        except Exception as e:
            print(f"Error generating embedding: {e}")
            # Fallback to zeros (1536 is the dimension for text-embedding-3-small)
            return [0.0] * 1536

    async def store_chat_message(
        self, user_id: str, session_id: str, role: str, content: str
    ) -> None:
        """Store a chat message and its embedding in Postgres."""
        embedding = await self._get_embedding(content)
        async with self.async_session() as session:
            message = ChatMessage(
                user_id=user_id,
                session_id=session_id,
                role=role,
                content=content,
                embedding=embedding,
            )
            session.add(message)
            await session.commit()

    async def get_chat_history(
        self, user_id: str, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve chat history for a specific session."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMessage)
                .filter(
                    ChatMessage.user_id == user_id, ChatMessage.session_id == session_id
                )
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
            )
            messages = result.scalars().all()
            return [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]

    async def get_all_sessions(self, user_id: str) -> List[str]:
        """Get all unique session IDs for a user from long-term memory."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatMessage.session_id)
                .filter(ChatMessage.user_id == user_id)
                .distinct()
            )
            return [row[0] for row in result.all()]

    async def get_all_sessions_with_metadata(self, user_id: str) -> List[Dict[str, str]]:
        """Get all sessions with their titles and IDs."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatSession)
                .filter(ChatSession.user_id == user_id)
                .order_by(ChatSession.created_at.desc())
            )
            sessions = result.scalars().all()
            return [{"id": s.session_id, "title": s.title} for s in sessions]

    async def create_chat_session(
        self, session_id: str, user_id: str, title: str
    ) -> None:
        """Create a new chat session with a title."""
        async with self.async_session() as session:
            chat_session = ChatSession(
                session_id=session_id, user_id=user_id, title=title
            )
            session.add(chat_session)
            await session.commit()

    async def get_chat_session(
        self, session_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get chat session metadata."""
        async with self.async_session() as session:
            result = await session.execute(
                select(ChatSession).filter(
                    ChatSession.session_id == session_id, ChatSession.user_id == user_id
                )
            )
            s = result.scalar_one_or_none()
            if s:
                return {"session_id": s.session_id, "title": s.title}
            return None

    async def search_chat_messages(
        self, user_id: str, query: str, limit: int = 5
    ) -> List[Dict[str, Any]]:
        """Semantic search over chat history using cosine distance."""
        query_embedding = await self._get_embedding(query)
        async with self.async_session() as session:
            # Using pgvector distance operator <=> for cosine distance
            result = await session.execute(
                select(ChatMessage)
                .filter(ChatMessage.user_id == user_id)
                .order_by(ChatMessage.embedding.cosine_distance(query_embedding))
                .limit(limit)
            )
            messages = result.scalars().all()
            return [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "session_id": msg.session_id,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]
    
    async def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile by user_id."""
        async with self.async_session() as session:
            result = await session.execute(
                select(UserProfile).filter(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                return {
                    "user_id": profile.user_id,
                    "name": profile.name,
                    "course_intake": profile.course_intake,
                    "interests": profile.interests,
                }
            return None
    
    async def create_or_update_user_profile(
        self, user_id: str, profile_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create or update a user profile."""
        async with self.async_session() as session:
            result = await session.execute(
                select(UserProfile).filter(UserProfile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if profile:
                for key, value in profile_data.items():
                    setattr(profile, key, value)
                profile.updated_at = datetime.now(timezone.utc)
            else:
                profile = UserProfile(user_id=user_id, **profile_data)
                session.add(profile)

            print(f"Profile data: {profile_data}")  # Debugging line

            await session.commit()
            await session.refresh(profile)
            return {
                "user_id": profile.user_id,
                "name": profile.name,
                "course_intake": profile.course_intake,
                "interests": profile.interests,
                "created_at": profile.created_at,
                "updated_at": profile.updated_at,
            }

if __name__ == "__main__":
    async def main() -> None:
        svc = LongTermMemoryService()

        # 1) Check DB connectivity
        try:
            async with svc.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print("DB connectivity: OK")
        except Exception as e:
            print(f"DB connectivity: FAILED ({e})")
            return

        # 2) Check we can create tables
        try:
            await svc.create_tables()
            print("DB create tables: OK")
        except Exception as e:
            print(f"DB create tables: FAILED ({e})")
            return

        # 3) Check we can add a new user (insert/update)
        user_id = f"smoke_{uuid.uuid4().hex}"
        try:
            await svc.create_or_update_user_profile(
                user_id=user_id,
                profile_data={
                    "name": "Smoke Test User",
                    "course_intake": ["CS101"],
                    "interests": ["databases"],
                },
            )
            print(f"DB add user_profile: OK (user_id={user_id})")
        except Exception as e:
            print(f"DB add user_profile: FAILED ({e})")
            return

        # 4) Check get_user_profile
        try:
            profile = await svc.get_user_profile(user_id)
            print(f"DB get_user_profile: OK (result={profile})")
        except Exception as e:
            print(f"DB get_user_profile: FAILED ({e})")

    asyncio.run(main())
