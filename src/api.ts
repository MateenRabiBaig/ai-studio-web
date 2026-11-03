export type User = {
  id: string;
  email: string;
  name: string;
  dietary_preference: string;
  max_cook_time_minutes: number;
  servings: number;
  last_active_conversation_id: string | null;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

const TOKEN_KEY = "ai_studio_token";
export const UNAUTHORIZED_EVENT = "ai-studio:unauthorized";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function fallbackMessage(status: number): string {
  switch (status) {
    case 401:
      return "Your session has expired. Please sign in again.";
    case 404:
      return "That conversation could not be found.";
    case 429:
      return "Too many requests. Please wait a moment and try again.";
    case 502:
    case 504:
      return "The AI service is unavailable right now. Please try again shortly.";
    default:
      return "Something went wrong. Please try again.";
  }
}

function detailToMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  // FastAPI validation errors arrive as an array — keep them generic.
  if (Array.isArray(detail)) return "Please check your input and try again.";
  return fallbackMessage(status);
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown } = {},
): Promise<T> {
  const token = getToken();

  let response: Response;
  try {
    response = await fetch(path, {
      method: options.method ?? "GET",
      headers: {
        ...(options.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(options.body !== undefined
        ? { body: JSON.stringify(options.body) }
        : {}),
    });
  } catch {
    throw new ApiError(
      0,
      "Cannot reach the server. Check your connection and try again.",
    );
  }

  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // Non-JSON body — fall through to the status-based message.
  }

  if (!response.ok) {
    const detail = (
      data as { detail?: unknown } | null
    )?.detail;

    // Expired/invalid session: drop the token and let the app return to login.
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
      clearToken();
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT));
    }

    throw new ApiError(response.status, detailToMessage(detail, response.status));
  }

  return data as T;
}
