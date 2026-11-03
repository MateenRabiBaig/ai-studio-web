import { useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Bot,
  Check,
  ChefHat,
  Clock3,
  Copy,
  Loader2,
  LogOut,
  Menu,
  MessageSquare,
  Pencil,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Utensils,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./App.css";
import {
  api,
  ApiError,
  UNAUTHORIZED_EVENT,
  type Conversation,
  type User,
} from "./api";
import { AuthProvider } from "./auth";
import { useAuth } from "./authContext";
import AuthScreen from "./AuthScreen";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type Toast = {
  id: string;
  kind: "info" | "success" | "error";
  text: string;
};

const PENDING_MESSAGE_KEY = "ai_studio_pending";

const suggestions = [
  {
    icon: ChefHat,
    title: "Create a healthy breakfast",
    description: "A nutritious recipe to start the day",
  },
  {
    icon: Clock3,
    title: "Plan a quick dinner",
    description: "Something delicious in 20 minutes",
  },
  {
    icon: Utensils,
    title: "Build a weekly meal plan",
    description: "Organize meals around my preferences",
  },
];

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}

function Root() {
  const { initializing, user } = useAuth();
  const [toasts, setToasts] = useState<Toast[]>([]);

  function toast(text: string, kind: Toast["kind"] = "info") {
    const id = crypto.randomUUID();
    setToasts((current) => [...current.slice(-2), { id, kind, text }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 4000);
  }

  useEffect(() => {
    function handleUnauthorized() {
      toast("Your session has expired. Please sign in again.", "error");
    }

    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () =>
      window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  if (initializing) {
    return (
      <div className="splash" aria-live="polite">
        <Loader2 size={22} className="spinner" />
        <span>Loading your workspace...</span>
      </div>
    );
  }

  return (
    <>
      <div className="toaster" aria-live="polite">
        {toasts.map((item) => (
          <div className={`toast ${item.kind}`} key={item.id} role="status">
            {item.kind === "error" && <AlertCircle size={15} />}
            {item.kind === "success" && <Check size={15} />}
            {item.kind === "info" && <Sparkles size={15} />}
            <span>{item.text}</span>
          </div>
        ))}
      </div>

      {user ? (
        <ChatApp user={user} toast={toast} />
      ) : (
        <AuthScreen />
      )}
    </>
  );
}

function ChatApp({
  user,
  toast,
}: {
  user: User;
  toast: (text: string, kind?: Toast["kind"]) => void;
}) {
  const { logout, updateUser } = useAuth();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState(() =>
    sessionStorage.getItem(PENDING_MESSAGE_KEY) ?? "",
  );
  const [thinking, setThinking] = useState(false);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [copiedMessage, setCopiedMessage] = useState<string | null>(null);
  const [failedTurn, setFailedTurn] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const [dietaryPreference, setDietaryPreference] = useState(
    user.dietary_preference,
  );
  const [maxCookTime, setMaxCookTime] = useState(
    String(user.max_cook_time_minutes),
  );
  const [servings, setServings] = useState(String(user.servings));

  const prefsInitialized = useRef(false);
  const prefsTimer = useRef<number | undefined>(undefined);
  const scrollAnchor = useRef<HTMLDivElement | null>(null);

  // Restore the last active conversation after refresh.
  useEffect(() => {
    void refreshConversations();

    if (user.last_active_conversation_id) {
      void openConversation(user.last_active_conversation_id, {
        allowMissing: true,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist preferences (debounced) whenever they change.
  useEffect(() => {
    if (!prefsInitialized.current) {
      prefsInitialized.current = true;
      return;
    }

    window.clearTimeout(prefsTimer.current);
    prefsTimer.current = window.setTimeout(async () => {
      try {
        const updated = await api<User>("/api/me/preferences", {
          method: "PATCH",
          body: {
            dietary_preference: dietaryPreference,
            max_cook_time_minutes: Number(maxCookTime),
            servings: Number(servings),
          },
        });
        updateUser(updated);
      } catch (caught) {
        toast(
          caught instanceof ApiError
            ? caught.message
            : "Could not save your preferences.",
          "error",
        );
      }
    }, 600);

    return () => window.clearTimeout(prefsTimer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dietaryPreference, maxCookTime, servings]);

  // Keep the newest message in view.
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, thinking]);

  async function refreshConversations() {
    try {
      setConversations(await api<Conversation[]>("/api/conversations"));
    } catch {
      // Sidebar stays empty; the chat itself still works.
    }
  }

  async function openConversation(
    id: string,
    { allowMissing = false }: { allowMissing?: boolean } = {},
  ) {
    if (id === activeId && !allowMissing) return;

    setLoadingConversation(true);
    setFailedTurn(null);

    try {
      const history = await api<Message[]>(
        `/api/conversations/${id}/messages`,
      );

      setActiveId(id);
      setMessages(history);
      setInput(sessionStorage.getItem(PENDING_MESSAGE_KEY) ?? "");
      sessionStorage.removeItem(PENDING_MESSAGE_KEY);
    } catch (caught) {
      if (allowMissing && caught instanceof ApiError && caught.status === 404) {
        // The last active conversation was deleted; fall back to the welcome view.
        return;
      }
      toast(
        caught instanceof ApiError
          ? caught.message
          : "Could not load that conversation.",
        "error",
      );
    } finally {
      setLoadingConversation(false);
    }
  }

  function newConversation() {
    if (thinking) return;
    // No record is created until the first message is actually sent.
    setActiveId(null);
    setMessages([]);
    setFailedTurn(null);
    setInput("");
  }

  async function submitRename(id: string) {
    const title = renameValue.trim();

    if (!title) {
      setRenamingId(null);
      return;
    }

    try {
      const updated = await api<Conversation>(
        `/api/conversations/${id}`,
        { method: "PATCH", body: { title } },
      );

      setConversations((current) =>
        current.map((item) => (item.id === id ? updated : item)),
      );
      setRenamingId(null);
    } catch (caught) {
      toast(
        caught instanceof ApiError
          ? caught.message
          : "Could not rename the conversation.",
        "error",
      );
    }
  }

  async function deleteConversation(id: string) {
    setDeletingId(null);

    try {
      await api(`/api/conversations/${id}`, { method: "DELETE" });
    } catch (caught) {
      toast(
        caught instanceof ApiError
          ? caught.message
          : "Could not delete the conversation.",
        "error",
      );
      return;
    }

    setConversations((current) =>
      current.filter((conversation) => conversation.id !== id),
    );

    if (id === activeId) {
      setActiveId(null);
      setMessages([]);
    }

    toast("Conversation deleted.", "success");
  }

  async function sendMessage(value = input) {
    const content = value.trim();

    if (!content || thinking) return;

    setFailedTurn(null);

    const optimistic: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content,
    };

    setMessages((current) => [...current, optimistic]);
    setInput("");
    sessionStorage.removeItem(PENDING_MESSAGE_KEY);
    setThinking(true);

    try {
      const data = await api<{ reply: string; conversation_id: string }>(
        "/api/chat",
        { method: "POST", body: { conversation_id: activeId, content } },
      );

      if (data.conversation_id !== activeId) {
        setActiveId(data.conversation_id);
      }

      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.reply,
        },
      ]);

      void refreshConversations();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        // Session expired mid-send: stash the message so it survives re-login.
        sessionStorage.setItem(PENDING_MESSAGE_KEY, content);
        return;
      }

      // Keep the unsent message visible and offer a retry.
      setFailedTurn(content);
      toast(
        caught instanceof ApiError
          ? caught.message
          : "Something went wrong. Please try again.",
        "error",
      );
    } finally {
      setThinking(false);
    }
  }

  function retryFailedTurn() {
    if (failedTurn) {
      // Drop the optimistic user message; sendMessage re-adds it fresh.
      setMessages((current) => current.slice(0, -1));
      void sendMessage(failedTurn);
    }
  }

  async function copyMessage(message: Message) {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopiedMessage(message.id);
      window.setTimeout(() => setCopiedMessage(null), 1500);
    } catch {
      toast("Could not copy to the clipboard.", "error");
    }
  }

  async function handleLogout() {
    await logout();
  }

  return (
    <main className="app-shell">
      {sidebarOpen && (
        <>
          <button
            className="sidebar-backdrop"
            aria-label="Close sidebar"
            onClick={() => setSidebarOpen(false)}
            tabIndex={-1}
          />
          <aside className="sidebar">
            <div className="brand-row">
              <div className="brand-mark">
                <Sparkles size={19} />
              </div>
              <span className="brand-name">AI Studio</span>
              <button
                className="icon-button sidebar-close"
                aria-label="Close sidebar"
                onClick={() => setSidebarOpen(false)}
              >
                <X size={17} />
              </button>
            </div>

            <button className="new-chat-button" onClick={newConversation}>
              <Plus size={17} />
              <span>New conversation</span>
            </button>

            {conversations.length > 0 ? (
              <div className="section-label">YOUR CONVERSATIONS</div>
            ) : (
              <div className="section-label">NO CONVERSATIONS YET</div>
            )}

            <div className="conversation-list">
              {conversations.map((conversation) => (
                <div
                  className={`conversation-item ${
                    conversation.id === activeId ? "active" : ""
                  }`}
                  key={conversation.id}
                >
                  {renamingId === conversation.id ? (
                    <input
                      className="rename-input"
                      value={renameValue}
                      autoFocus
                      aria-label="Rename conversation"
                      onChange={(event) =>
                        setRenameValue(event.target.value)
                      }
                      onBlur={() => void submitRename(conversation.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          void submitRename(conversation.id);
                        }
                        if (event.key === "Escape") {
                          setRenamingId(null);
                        }
                      }}
                      maxLength={120}
                    />
                  ) : deletingId === conversation.id ? (
                    <div className="delete-confirm">
                      <span>Delete this conversation?</span>
                      <button
                        className="delete-confirm-button danger"
                        onClick={() => void deleteConversation(conversation.id)}
                      >
                        Delete
                      </button>
                      <button
                        className="delete-confirm-button"
                        onClick={() => setDeletingId(null)}
                      >
                        Keep
                      </button>
                    </div>
                  ) : (
                    <>
                      <button
                        className="conversation-open"
                        onClick={() => openConversation(conversation.id)}
                      >
                        <MessageSquare size={16} />
                        <span className="conversation-title">
                          {conversation.title}
                        </span>
                      </button>
                      <button
                        className="conversation-action"
                        aria-label={`Rename ${conversation.title}`}
                        onClick={() => {
                          setRenamingId(conversation.id);
                          setRenameValue(conversation.title);
                        }}
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        className="conversation-action"
                        aria-label={`Delete ${conversation.title}`}
                        onClick={() => setDeletingId(conversation.id)}
                      >
                        <Trash2 size={13} />
                      </button>
                    </>
                  )}
                </div>
              ))}
            </div>

            <div className="preferences-panel">
              <div className="preferences-heading">
                <ChefHat size={16} />
                <span>Recipe preferences</span>
              </div>

              <label className="preference-field">
                <span>Dietary preference</span>
                <select
                  value={dietaryPreference}
                  onChange={(event) =>
                    setDietaryPreference(event.target.value)
                  }
                >
                  <option value="vegetarian">Vegetarian</option>
                  <option value="vegan">Vegan</option>
                  <option value="high-protein">High protein</option>
                  <option value="no-restrictions">No restrictions</option>
                </select>
              </label>

              <label className="preference-field">
                <span>Maximum cooking time</span>
                <select
                  value={maxCookTime}
                  onChange={(event) => setMaxCookTime(event.target.value)}
                >
                  <option value="15">15 minutes</option>
                  <option value="20">20 minutes</option>
                  <option value="30">30 minutes</option>
                  <option value="45">45 minutes</option>
                </select>
              </label>

              <label className="preference-field">
                <span>Servings</span>
                <select
                  value={servings}
                  onChange={(event) => setServings(event.target.value)}
                >
                  <option value="1">1 person</option>
                  <option value="2">2 people</option>
                  <option value="4">4 people</option>
                  <option value="6">6 people</option>
                </select>
              </label>
            </div>

            <div className="sidebar-bottom">
              <div className="profile-avatar">
                {(user.name || user.email).charAt(0).toUpperCase()}
              </div>
              <div className="profile-details">
                <strong>{user.name || "AI Studio"}</strong>
                <span>{user.email}</span>
              </div>
              <button
                className="icon-button"
                aria-label="Sign out"
                title="Sign out"
                onClick={() => void handleLogout()}
              >
                <LogOut size={17} />
              </button>
            </div>
          </aside>
        </>
      )}

      <section className="main-panel">
        <header className="topbar">
          <div className="topbar-left">
            {!sidebarOpen && (
              <button
                className="icon-button"
                aria-label="Open sidebar"
                onClick={() => setSidebarOpen(true)}
              >
                <Menu size={19} />
              </button>
            )}
            <div className="page-heading">
              <span>AI Assistant</span>
              <span className="ready-dot" />
              <span className="ready-label">Ready</span>
            </div>
          </div>

          <div className="topbar-right">
            <span className="model-label">
              <Sparkles size={14} />
              AI Workspace
            </span>
            <button
              className="icon-button"
              aria-label="Start new conversation"
              onClick={newConversation}
            >
              <Plus size={18} />
            </button>
          </div>
        </header>

        <div className="chat-scroll-area">
          {loadingConversation ? (
            <div className="conversation-loader" aria-live="polite">
              <Loader2 size={20} className="spinner" />
              <span>Loading conversation...</span>
            </div>
          ) : messages.length === 0 ? (
            <div className="welcome-screen">
              <div className="hero-icon">
                <Sparkles size={28} />
              </div>

              <div className="eyebrow">THINK · CREATE · EXPLORE</div>

              <h1>
                What can we
                <br />
                <span>create together?</span>
              </h1>

              <p className="hero-description">
                Your personal AI workspace. Turn your ideas into useful
                answers, thoughtful plans, and interactive experiences.
              </p>

              <div className="suggestion-header">
                <span>GET STARTED</span>
                <span className="suggestion-caption">Choose an idea</span>
              </div>

              <div className="suggestion-grid">
                {suggestions.map((suggestion) => {
                  const Icon = suggestion.icon;

                  return (
                    <button
                      className="suggestion-card"
                      key={suggestion.title}
                      onClick={() => sendMessage(suggestion.title)}
                      disabled={thinking}
                    >
                      <span className="suggestion-icon">
                        <Icon size={19} />
                      </span>
                      <span className="suggestion-copy">
                        <strong>{suggestion.title}</strong>
                        <span>{suggestion.description}</span>
                      </span>
                      <ArrowDown
                        className="suggestion-arrow"
                        size={16}
                      />
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((message) => (
                <article
                  className={`message-row ${message.role}`}
                  key={message.id}
                >
                  <div className="message-avatar">
                    {message.role === "assistant" ? (
                      <Bot size={18} />
                    ) : (
                      <span>Y</span>
                    )}
                  </div>

                  <div className="message-content">
                    <div className="message-header">
                      <strong>
                        {message.role === "assistant" ? "AI Studio" : "You"}
                      </strong>
                      {message.role === "assistant" && (
                        <span className="assistant-label">ASSISTANT</span>
                      )}
                    </div>
                    <div className="markdown-content">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {message.content}
                      </ReactMarkdown>
                    </div>

                    {message.role === "assistant" && (
                      <button
                        className="copy-button"
                        onClick={() => copyMessage(message)}
                      >
                        {copiedMessage === message.id ? (
                          <Check size={14} />
                        ) : (
                          <Copy size={14} />
                        )}
                        {copiedMessage === message.id ? "Copied" : "Copy"}
                      </button>
                    )}
                  </div>
                </article>
              ))}

              {failedTurn && (
                <div className="error-row">
                  <div className="message-avatar error-avatar">
                    <AlertCircle size={18} />
                  </div>
                  <div className="error-content">
                    <p>
                      Your last message could not be delivered.
                    </p>
                    <button className="retry-button" onClick={retryFailedTurn}>
                      <RefreshCw size={14} />
                      Retry
                    </button>
                  </div>
                </div>
              )}

              {thinking && (
                <div className="thinking-row">
                  <div className="message-avatar">
                    <Bot size={18} />
                  </div>
                  <div className="thinking-content">
                    <span className="thinking-dots">
                      <i />
                      <i />
                      <i />
                    </span>
                    <span>Preparing a response</span>
                  </div>
                </div>
              )}

              <div ref={scrollAnchor} />
            </div>
          )}
        </div>

        <footer className="composer-section">
          <form
            className="composer"
            onSubmit={(event) => {
              event.preventDefault();
              sendMessage();
            }}
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Message AI Studio..."
              aria-label="Message AI Studio"
              rows={2}
              maxLength={8000}
            />

            <div className="composer-footer">
              <div className="composer-hint">
                <Sparkles size={14} />
                <span>Ask, explore, or create something new</span>
              </div>

              <button
                className="send-button"
                type="submit"
                aria-label="Send message"
                disabled={!input.trim() || thinking}
              >
                <ArrowUp size={19} />
              </button>
            </div>
          </form>
        </footer>
      </section>
    </main>
  );
}
