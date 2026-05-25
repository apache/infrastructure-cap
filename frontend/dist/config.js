// Runtime configuration for the CAP frontend.
// Edit this file in place on a deployed instance to change the
// backend endpoint; the bundled JavaScript reads it via window.CAP_CONFIG.
//
// All keys are optional. Defaults are applied by src/lib/api.ts.
window.CAP_CONFIG = {
  // Base URL for the CAP HTTP API. The frontend will issue requests
  // such as `${API_BASE}/list`, `${API_BASE}/auth`, etc.
  // Default: "/api" (the reverse proxy strips this and forwards to
  // the backend).
  API_BASE: "/api",

  // Optional override for the OAuth login URL. If null, the frontend
  // uses `${API_BASE}/auth?login`.
  LOGIN_URL: null,

  // Optional product name shown in the navbar. Defaults to "CAP".
  PRODUCT_NAME: "ASF Contingent Approval Platform",
};
