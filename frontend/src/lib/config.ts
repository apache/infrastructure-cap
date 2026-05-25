// Resolves window.CAP_CONFIG once at module load. The runtime config
// file (public/config.js) is loaded by index.html before this bundle,
// so window.CAP_CONFIG is in scope by the time this module evaluates.

declare global {
  interface Window {
    CAP_CONFIG?: {
      API_BASE?: string;
      LOGIN_URL?: string | null;
      PRODUCT_NAME?: string;
    };
  }
}

interface ResolvedConfig {
  API_BASE: string;
  LOGIN_URL: string | null;
  PRODUCT_NAME: string;
}

function resolve(): ResolvedConfig {
  const raw = typeof window !== "undefined" ? window.CAP_CONFIG : undefined;
  if (!raw) {
    // eslint-disable-next-line no-console
    console.warn(
      "[CAP] window.CAP_CONFIG missing; falling back to compiled defaults.",
    );
  }
  return Object.freeze({
    API_BASE: raw?.API_BASE ?? "/api",
    LOGIN_URL: raw?.LOGIN_URL ?? null,
    PRODUCT_NAME: raw?.PRODUCT_NAME ?? "CAP",
  });
}

export const config: ResolvedConfig = resolve();
