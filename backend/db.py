import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, SQLModel, Session, create_engine

DB_PATH = Path(
    os.getenv("AI_STUDIO_DB_PATH", Path(__file__).with_name("ai_studio.db"))
)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})

# Allowed values for persisted recipe preferences.
DIETARY_PREFERENCES = {"vegetarian", "vegan", "high-protein", "no-restrictions"}
MAX_COOK_TIME_MINUTES_MIN = 5
MAX_COOK_TIME_MINUTES_MAX = 240
SERVINGS_MIN = 1
SERVINGS_MAX = 12


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class User(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str = Field(default="")
    hashed_password: str
    dietary_preference: str = Field(default="no-restrictions")
    max_cook_time_minutes: int = Field(default=30)
    servings: int = Field(default=2)
    last_active_conversation_id: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class Conversation(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    title: str = Field(default="New conversation", max_length=120)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow, index=True)


class Message(SQLModel, table=True):
    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversation.id", index=True)
    role: str
    content: str
    created_at: datetime = Field(default_factory=utcnow)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
