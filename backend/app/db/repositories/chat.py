"""Repository for chat sessions + messages."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession, Message


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_session(self, repo_id: str) -> ChatSession:
        cs = ChatSession(repo_id=repo_id)
        self.session.add(cs)
        await self.session.commit()
        await self.session.refresh(cs)
        return cs

    async def get_session(self, session_id: str) -> ChatSession | None:
        return await self.session.get(ChatSession, session_id)

    async def add_message(
        self, *, session_id: str, role: str, content: str, citations_json: list | None = None
    ) -> Message:
        msg = Message(
            session_id=session_id, role=role, content=content, citations_json=citations_json
        )
        self.session.add(msg)
        await self.session.commit()
        await self.session.refresh(msg)
        return msg
