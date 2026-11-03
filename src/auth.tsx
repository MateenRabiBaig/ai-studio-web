import { useEffect, useState, type ReactNode } from "react";
import {
  api,
  clearToken,
  getToken,
  setToken,
  UNAUTHORIZED_EVENT,
  type User,
} from "./api";
import { AuthContext } from "./authContext";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [initializing, setInitializing] = useState(
    () => getToken() !== null,
  );
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    // Restore the session from a persisted token after refresh.
    if (!getToken()) return;

    api<User>("/api/me")
      .then(setUser)
      .catch(() => clearToken())
      .finally(() => setInitializing(false));
  }, []);

  useEffect(() => {
    function handleUnauthorized() {
      setUser(null);
    }

    window.addEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
    return () =>
      window.removeEventListener(UNAUTHORIZED_EVENT, handleUnauthorized);
  }, []);

  async function login(email: string, password: string) {
    const data = await api<{ access_token: string; user: User }>(
      "/api/auth/login",
      {
        method: "POST",
        body: { email, password },
      },
    );
    setToken(data.access_token);
    setUser(data.user);
  }

  async function register(name: string, email: string, password: string) {
    const data = await api<{ access_token: string; user: User }>(
      "/api/auth/register",
      {
        method: "POST",
        body: { name, email, password },
      },
    );
    setToken(data.access_token);
    setUser(data.user);
  }

  async function logout() {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      // Logout succeeds client-side regardless.
    }
    clearToken();
    sessionStorage.removeItem("ai_studio_pending");
    setUser(null);
  }

  function updateUser(updated: User) {
    setUser(updated);
  }

  return (
    <AuthContext.Provider
      value={{ initializing, user, login, register, logout, updateUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}
