"""Where documents, conversations and chat history are kept.

Two interchangeable backends, chosen by DATABASE_URL:
- empty: everything in process memory (required case scope, no setup);
- PostgreSQL: our two small tables plus LangChain's PostgresChatMessageHistory,
  so conversations survive restarts and can be reopened from the sidebar.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
from langchain_core.chat_history import BaseChatMessageHistory, InMemoryChatMessageHistory
from langchain_postgres import PostgresChatMessageHistory
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    func,
    insert,
    select,
    update,
)

HISTORY_TABLE = "chat_history"


@dataclass
class DocumentRecord:
    document_id: str
    filename: str
    metadata: dict


@dataclass
class ConversationRecord:
    id: str
    client_id: str
    document_id: str
    filename: str
    title: str
    updated_at: datetime


# --- in memory -------------------------------------------------------------------

class MemoryRepository:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._conversations: dict[str, ConversationRecord] = {}
        self._histories: dict[str, InMemoryChatMessageHistory] = {}
        self._lock = threading.Lock()

    def history(self, conversation_id: str) -> BaseChatMessageHistory:
        with self._lock:
            return self._histories.setdefault(conversation_id, InMemoryChatMessageHistory())

    def save_document(self, record: DocumentRecord) -> None:
        with self._lock:
            self._documents[record.document_id] = record

    def get_document(self, document_id: str) -> DocumentRecord | None:
        return self._documents.get(document_id)

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        return self._conversations.get(conversation_id)

    def touch_conversation(self, conversation_id: str, client_id: str, document_id: str,
                           title: str) -> None:
        with self._lock:
            existing = self._conversations.get(conversation_id)
            doc = self._documents.get(document_id)
            self._conversations[conversation_id] = ConversationRecord(
                id=conversation_id,
                client_id=client_id,
                document_id=document_id,
                filename=doc.filename if doc else "",
                title=existing.title if existing else title,
                updated_at=datetime.now(UTC),
            )

    def list_conversations(self, client_id: str) -> list[ConversationRecord]:
        rows = [c for c in self._conversations.values() if c.client_id == client_id]
        return sorted(rows, key=lambda c: c.updated_at, reverse=True)

    def delete_conversation(self, conversation_id: str) -> None:
        with self._lock:
            self._conversations.pop(conversation_id, None)
            self._histories.pop(conversation_id, None)


# --- PostgreSQL ----------------------------------------------------------------------

_meta = MetaData()
documents = Table(
    "documents", _meta,
    Column("id", String(64), primary_key=True),
    Column("filename", String(255), nullable=False),
    Column("page_count", Integer, nullable=False),
    Column("doc_metadata", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
conversations = Table(
    "conversations", _meta,
    Column("id", String(36), primary_key=True),  # UUID created by the browser
    Column("client_id", String(100), nullable=False, index=True),
    Column("document_id", String(64), ForeignKey("documents.id"), nullable=False),
    Column("title", String(200), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


class PostgresRepository:
    def __init__(self, database_url: str):
        self._engine = create_engine(_psycopg_url(database_url), pool_pre_ping=True)
        _meta.create_all(self._engine)
        # One autocommit connection for LangChain's history class; psycopg serialises
        # concurrent use of a connection, which is enough at demo scale.
        self._history_conn = psycopg.connect(database_url, autocommit=True)
        PostgresChatMessageHistory.create_tables(self._history_conn, HISTORY_TABLE)

    def history(self, conversation_id: str) -> BaseChatMessageHistory:
        return PostgresChatMessageHistory(
            HISTORY_TABLE, conversation_id, sync_connection=self._history_conn
        )

    def save_document(self, record: DocumentRecord) -> None:
        with self._engine.begin() as db:
            if db.execute(select(documents.c.id).where(documents.c.id == record.document_id)
                          ).first() is None:
                db.execute(insert(documents).values(
                    id=record.document_id, filename=record.filename,
                    page_count=record.metadata.get("page_count", 0),
                    doc_metadata=record.metadata,
                ))

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self._engine.connect() as db:
            row = db.execute(select(documents).where(documents.c.id == document_id)).first()
        return DocumentRecord(row.id, row.filename, row.doc_metadata) if row else None

    def get_conversation(self, conversation_id: str) -> ConversationRecord | None:
        with self._engine.connect() as db:
            row = db.execute(self._conversation_query().where(
                conversations.c.id == conversation_id)).first()
        return _conversation(row) if row else None

    def touch_conversation(self, conversation_id: str, client_id: str, document_id: str,
                           title: str) -> None:
        with self._engine.begin() as db:
            updated = db.execute(update(conversations)
                                 .where(conversations.c.id == conversation_id)
                                 .values(updated_at=func.now()))
            if updated.rowcount == 0:
                db.execute(insert(conversations).values(
                    id=conversation_id, client_id=client_id, document_id=document_id,
                    title=title,
                ))

    def list_conversations(self, client_id: str) -> list[ConversationRecord]:
        with self._engine.connect() as db:
            rows = db.execute(self._conversation_query()
                              .where(conversations.c.client_id == client_id)
                              .order_by(conversations.c.updated_at.desc())).all()
        return [_conversation(r) for r in rows]

    def delete_conversation(self, conversation_id: str) -> None:
        self.history(conversation_id).clear()
        with self._engine.begin() as db:
            db.execute(delete(conversations).where(conversations.c.id == conversation_id))

    @staticmethod
    def _conversation_query():
        return select(conversations, documents.c.filename).join(documents)


def _conversation(row) -> ConversationRecord:
    return ConversationRecord(row.id, row.client_id, row.document_id, row.filename,
                              row.title, row.updated_at)


Repository = MemoryRepository | PostgresRepository


def build_repository(database_url: str) -> Repository:
    return PostgresRepository(database_url) if database_url else MemoryRepository()
