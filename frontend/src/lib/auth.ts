import { config } from "./config";
import { api, NotFoundError, UnauthorizedError } from "./api";
import { session } from "./stores";
import type { UserSession } from "./types";

// asfquart's OAuth gateway uses `?login=<return-path>` to kick off the
// handshake; the value is the path the gateway will return the user to
// after a successful login. We default to "/" so first-time users land
// on the dashboard.
export function loginUrl(redirectTo: string = "/"): string {
  if (config.LOGIN_URL) {
    const sep = config.LOGIN_URL.includes("?") ? "&" : "?";
    return `${config.LOGIN_URL}${sep}login=${encodeURIComponent(redirectTo)}`;
  }
  return `${config.API_BASE}/auth?login=${encodeURIComponent(redirectTo)}`;
}

export function redirectToLogin(): void {
  // Send the user back to wherever they were after OAuth completes. We
  // pass the hash route (e.g. "/question/42") so the SPA opens to the
  // same page; if there is no hash, fall back to "/".
  const hash = window.location.hash;
  const returnTo = hash.startsWith("#/") ? "/" + hash : "/";
  window.location.replace(loginUrl(returnTo));
}

function looksLikeSession(value: unknown): value is UserSession {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { uid?: unknown }).uid === "string"
  );
}

function normalizeSession(raw: unknown): UserSession {
  const obj = raw as Record<string, unknown>;
  return {
    uid: String(obj.uid),
    fullname:
      typeof obj.fullname === "string" ? (obj.fullname as string) : null,
    isRoot: Boolean(obj.isRoot ?? obj.is_root ?? false),
    projects: Array.isArray(obj.projects)
      ? (obj.projects as unknown[]).map((p) => String(p))
      : [],
    committees: Array.isArray(obj.committees)
      ? (obj.committees as unknown[]).map((c) => String(c))
      : [],
  };
}

export async function loadSession(): Promise<void> {
  session.set({ status: "loading" });
  try {
    const raw = await api.getSession();
    if (looksLikeSession(raw)) {
      session.set({ status: "ready", user: normalizeSession(raw) });
    } else {
      session.set({ status: "anonymous" });
    }
  } catch (err) {
    // 401 and 404 from /auth both mean "no session" in asfquart's
    // deployment. 401 -> the gateway already knows about us but the
    // cookie is missing/expired; 404 -> the gateway has no session
    // record at all. Either way the user must reauthenticate.
    if (err instanceof UnauthorizedError || err instanceof NotFoundError) {
      session.set({ status: "anonymous" });
      return;
    }
    const message = err instanceof Error ? err.message : "Unknown error";
    session.set({ status: "error", message });
  }
}
