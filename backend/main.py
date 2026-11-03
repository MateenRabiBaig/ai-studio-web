
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlmodel import select
from starlette.responses import JSONResponse

from agent import agent
from db import (
    DIETARY_PREFERENCES,
    MAX_COOK_TIME_MINUTES_MAX,
    MAX_COOK_TIME_MINUTES_MIN,
    SERVINGS_MAX,
    SERVINGS_MIN,
    Conversation,
    Message,
    User,
    get_session,
    init_db,
)
from ratelimit import check, retry_after
from security import create_access_token, decode_access_token, hash_password, verify_password

logger = logging.getLogger("ai_studio")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="AI Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)

init_db()

# ---- Limits -------------------------------------------------------------

MAX_MESSAGE_LENGTH = 8000
MAX_TITLE_LENGTH = 120
MAX_HISTORY_MESSAGES_TO_MODEL = 20
AI_TIMEOUT_SECONDS = 60

LOGIN_RATE_LIMIT = (5, 60)  # 5 attempts per minute per IP
REGISTER_RATE_LIMIT = (3, 600)  # 3 attempts per 10 minutes per IP
CHAT_RATE_LIMIT = (20, 60)  # 20 AI requests per minute per user

bearer_scheme = HTTPBearer(auto_error=False)


# ---- Errors -------------------------------------------------------------

def fail(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Log the real error server-side; never leak internals to the client.
    logger.exception("Unhandled error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. Please try again."})


# ---- Auth dependency ----------------------------------------------------

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise fail(401, "You need to sign in to continue.")

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise fail(401, "Your session has expired. Please sign in again.")

    with get_session() as session:
        user = session.get(User, user_id)
        if not user:
            raise fail(401, "Your session has expired. Please sign in again.")

        session.refresh(user)
        return user


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ---- Schemas ------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserResponse"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    dietary_preference: str
    max_cook_time_minutes: int
    servings: int
    last_active_conversation_id: str | None


class PreferencesUpdate(BaseModel):
    dietary_preference: str | None = None
    max_cook_time_minutes: int | None = Field(default=None, ge=MAX_COOK_TIME_MINUTES_MIN, le=MAX_COOK_TIME_MINUTES_MAX)
    servings: int | None = Field(default=None, ge=SERVINGS_MIN, le=SERVINGS_MAX)


class ConversationCreate(BaseModel):
    title: str = Field(default="New conversation", max_length=MAX_TITLE_LENGTH)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)


class ConversationResponse(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        dietary_preference=user.dietary_preference,
        max_cook_time_minutes=user.max_cook_time_minutes,
        servings=user.servings,
        last_active_conversation_id=user.last_active_conversation_id,
    )


def conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at.isoformat(),
        updated_at=conversation.updated_at.isoformat(),
    )


def message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at.isoformat(),
    )


def get_own_conversation(session, conversation_id: str, user: User) -> Conversation:
    """Fetch a conversation and enforce ownership. 404 (not 403) on mismatch
    so one user can never probe for the existence of another user's data."""
    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.user_id != user.id:
        raise fail(404, "Conversation not found.")
    return conversation


# ---- Auth endpoints -----------------------------------------------------

@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
async def register(request: RegisterRequest, request_obj: Request):
    limit, window = REGISTER_RATE_LIMIT
    ip = client_ip(request_obj)
    if not check(f"register:{ip}", limit, window):
        raise fail(
            429,
            f"Too many registration attempts. Please try again in {retry_after(f'register:{ip}', window)} seconds.",
        )

    email = request.email.lower().strip()

    with get_session() as session:
        existing = session.exec(select(User).where(User.email == email)).first()
        if existing:
            raise fail(409, "An account with this email already exists. Try signing in instead.")

        user = User(
            email=email,
            name=request.name.strip(),
            hashed_password=hash_password(request.password),
        )
        session.add(user)
        session.commit()
        session.refresh(user)

    return AuthResponse(access_token=create_access_token(user.id), user=user_response(user))


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(request: LoginRequest, request_obj: Request):
    limit, window = LOGIN_RATE_LIMIT
    ip = client_ip(request_obj)
    key = f"login:{ip}"
    if not check(key, limit, window):
        raise fail(
            429,
            f"Too many sign-in attempts. Please try again in {retry_after(key, window)} seconds.",
        )

    email = request.email.lower().strip()

    with get_session() as session:
        user = session.exec(select(User).where(User.email == email)).first()
        if not user or not verify_password(request.password, user.hashed_password):
            raise fail(401, "Incorrect email or password.")

    return AuthResponse(access_token=create_access_token(user.id), user=user_response(user))


@app.post("/api/auth/logout")
async def logout():
    # Tokens are stateless JWTs held by the client; logout happens by
    # deleting the token client-side. Replace with a server-side blocklist
    # if immediate revocation is ever needed.
    return {"ok": True}


@app.get("/api/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user_response(user)


@app.patch("/api/me/preferences", response_model=UserResponse)
async def update_preferences(request: PreferencesUpdate, user: User = Depends(get_current_user)):
    if request.dietary_preference is not None and request.dietary_preference not in DIETARY_PREFERENCES:
        raise fail(422, "That dietary preference is not supported.")

    with get_session() as session:
        stored = session.get(User, user.id)
        if not stored:
            raise fail(401, "Your session has expired. Please sign in again.")

        if request.dietary_preference is not None:
            stored.dietary_preference = request.dietary_preference
        if request.max_cook_time_minutes is not None:
            stored.max_cook_time_minutes = request.max_cook_time_minutes
        if request.servings is not None:
            stored.servings = request.servings

        session.add(stored)
        session.commit()
        session.refresh(stored)
        return user_response(stored)


# ---- Conversation endpoints --------------------------------------------

@app.get("/api/conversations", response_model=list[ConversationResponse])
async def list_conversations(user: User = Depends(get_current_user)):
    with get_session() as session:
        conversations = session.exec(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
        ).all()
        return [conversation_response(c) for c in conversations]


@app.post("/api/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(request: ConversationCreate, user: User = Depends(get_current_user)):
    with get_session() as session:
        conversation = Conversation(user_id=user.id, title=request.title.strip() or "New conversation")
        session.add(conversation)
        session.commit()
        session.refresh(conversation)

        stored = session.get(User, user.id)
        if stored:
            stored.last_active_conversation_id = conversation.id
            session.add(stored)
            session.commit()

        return conversation_response(conversation)


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(conversation_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        conversation = get_own_conversation(session, conversation_id, user)

        messages = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        ).all()

        stored = session.get(User, user.id)
        if stored:
            stored.last_active_conversation_id = conversation.id
            session.add(stored)
            session.commit()

        return [message_response(m) for m in messages]


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationResponse)
async def rename_conversation(conversation_id: str, request: ConversationUpdate, user: User = Depends(get_current_user)):
    with get_session() as session:
        conversation = get_own_conversation(session, conversation_id, user)
        conversation.title = request.title.strip() or conversation.title
        session.add(conversation)
        session.commit()
        session.refresh(conversation)
        return conversation_response(conversation)


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: User = Depends(get_current_user)):
    with get_session() as session:
        conversation = get_own_conversation(session, conversation_id, user)

        for message in session.exec(
            select(Message).where(Message.conversation_id == conversation.id)
        ).all():
            session.delete(message)
        session.delete(conversation)

        stored = session.get(User, user.id)
        if stored and stored.last_active_conversation_id == conversation.id:
            stored.last_active_conversation_id = None
            session.add(stored)

        session.commit()
        return {"ok": True}


# ---- Chat ---------------------------------------------------------------

@app.post("/api/chat")
async def chat(request: ChatRequest, user: User = Depends(get_current_user)):
    limit, window = CHAT_RATE_LIMIT
    key = f"chat:{user.id}"
    if not check(key, limit, window):
        raise fail(
            429,
            f"You're sending messages quite quickly. Please wait {retry_after(key, window)} seconds and try again.",
        )

    content = request.content.strip()
    if not content:
        raise fail(422, "Message cannot be empty.")

    with get_session() as session:
        if request.conversation_id:
            conversation = get_own_conversation(session, request.conversation_id, user)
        else:
            # First message with no open conversation: create one on the fly.
            conversation = Conversation(user_id=user.id)
            session.add(conversation)
            session.commit()
            session.refresh(conversation)

        history = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at)
        ).all()

    # Cap how much history is replayed into the model.
    recent = history[-MAX_HISTORY_MESSAGES_TO_MODEL:]
    transcript = "".join(f"{message.role}: {message.content}\n" for message in recent)

    preferences = {
        "dietaryPreference": user.dietary_preference,
        "maxCookTimeMinutes": user.max_cook_time_minutes,
        "servings": user.servings,
    }

    prompt = (
        f"Current user preferences: {preferences}\n\n"
        f"Conversation:\n{transcript}user: {content}\n\n"
        "Respond to the latest user message."
    )

    try:
        result = await asyncio.wait_for(agent.run(prompt), timeout=AI_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("AI request timed out after %ss (conversation %s)", AI_TIMEOUT_SECONDS, conversation.id)
        raise fail(504, "The AI took too long to respond. Please try again.")
    except Exception as exc:
        # Log the real exception in the backend terminal.
        logger.error("AI request failed: %s: %s", type(exc).__name__, exc)
        raise fail(502, "The AI request failed. Please try again in a moment.")

    reply = result.output

    # Persist only after a successful response so failed turns are not stored.
    try:
        with get_session() as session:
            stored_conversation = session.get(Conversation, conversation.id)
            if not stored_conversation:
                raise fail(404, "Conversation not found.")

            user_message = Message(
                conversation_id=conversation.id,
                role="user",
                content=content,
            )
            assistant_message = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=reply,
            )
            session.add(user_message)
            session.add(assistant_message)

            stored_conversation.updated_at = user_message.created_at
            if stored_conversation.title == "New conversation":
                stored_conversation.title = content[:MAX_TITLE_LENGTH]
            session.add(stored_conversation)

            stored_user = session.get(User, user.id)
            if stored_user:
                stored_user.last_active_conversation_id = conversation.id
                session.add(stored_user)

            session.commit()
    except HTTPException:
        raise
    except Exception:
        # The reply was generated but could not be saved — report honestly.
        logger.exception("Failed to persist messages for conversation %s", conversation.id)
        raise fail(500, "Your message was answered but could not be saved. Please try again.")

    return {
        "reply": reply,
        "conversation_id": conversation.id,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "service": "AI Studio"}
