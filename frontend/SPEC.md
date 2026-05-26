# CAP Frontend Specification

This document specifies the Svelte single-page web application that
fronts the ASF Infra Contingent Approval Provider (CAP). It complements
the backend contract in [`../backend/SPEC.md`](../backend/SPEC.md) and
defines the runtime, framework, page structure, component layout, and
HTTP integration for the initial UI iteration.

The audience for this document is anyone writing or reviewing the
frontend code. Anything the frontend does over the wire is already
governed by the backend spec; this document only addresses the
client-side concerns of presenting that API to a human.

## 1. Goals and Scope

The frontend is a static, single-page application (SPA) that consumes
the CAP HTTP API. It is served as plain HTML, JavaScript, and CSS by
the same reverse proxy that fronts the backend. All dynamic behavior
happens client-side via the Svelte runtime; the server contract is
strictly the JSON API defined by `backend/SPEC.md`.

The initial iteration covers exactly these user-facing capabilities:

1. **Session bootstrap.** On load, the app probes `GET {API_BASE}/auth`
   to discover the current user. If the response indicates the caller
   is not logged in, the app redirects the browser to
   `{API_BASE}/auth?login` so the asfquart OAuth handshake can run.
2. **Dashboard with two tabs.** A single landing page lists, in two
   tabs, (a) questions the user still needs to respond to, and
   (b) questions created or closed in the past 30 days that the user
   has already responded to, or whose project or committee the user
   belongs to. Both tabs sort newest first.
3. **Create question.** A form for filing a new question against any
   project in `session.projects`. Members of a project's committee
   (`session.committees`) may additionally mark the question private.
   The form adapts dynamically to the chosen `approval_type` and
   `response_option.kind`.
4. **View and respond.** A question detail view shows the current
   tally and the list of recorded responses, and, if the question is
   still open, a response form whose fields are derived from the
   question's `response_option`.
5. **Edit and withdraw.** The question detail view exposes edit and
   withdraw controls for questions the current user originally
   created. Edit fields mirror the `EditQuestionRequest` body
   (section 9.4 of the backend spec).

Out of scope for this iteration:

- The admin surface under `/admin/...` (section 9.10 of the backend
  spec). The UI never invokes admin endpoints; SREs use them through
  scripts.
- Mobile-first responsive design beyond what Bootstrap's default grid
  provides. Layouts target a desktop browser first and degrade
  gracefully to tablets.
- Offline mode, service workers, or push notifications. The UI is
  online-only; it relies on the live HTTP API.
- Internationalization. All strings are English.

## 2. Technology Stack

| Concern              | Choice                                                        |
|----------------------|---------------------------------------------------------------|
| Framework            | Svelte 4 (with optional opt-in to Svelte 5 runes when stable) |
| Build tooling        | Vite (`create-vite` Svelte template, TypeScript flavor)       |
| Language             | TypeScript for `.ts` modules, Svelte SFCs for components      |
| Routing              | `svelte-spa-router` (hash-based, static-deploy friendly)      |
| HTTP                 | Native `fetch` wrapped by `src/lib/api.ts`                    |
| State                | Svelte stores (`writable`, `derived`)                         |
| CSS framework        | Bootstrap 5.3 (CSS bundle, no jQuery)                         |
| Interactive widgets  | `bootstrap.bundle.min.js` (Popper + native JS) for modals,    |
|                      | tabs, dropdowns, tooltips                                     |
| Icons                | Font Awesome 6 Free (Solid + Regular subsets)                 |
| Form helpers         | No third-party form library; Svelte's two-way binding suffices|
| Date handling        | `Intl.DateTimeFormat` and a small `src/lib/time.ts` helper    |
| Linting / formatting | `eslint` + `prettier` with Svelte plugins                     |
| Testing              | `vitest` for units, `@testing-library/svelte` for components  |

Bootstrap is chosen because the user-facing reference design,
<https://agenda.apache.org/>, is itself Bootstrap-based; matching the
framework keeps the visual idiom consistent with the rest of the ASF
ecosystem. Font Awesome Free is sufficient for every icon required
in this iteration (clipboard, gavel, check, times, edit, pencil,
clock, lock, unlock, comment, paper-plane, sign-in); no Pro icons
appear in any mockup.

`svelte-spa-router` is chosen over SvelteKit because the deliverable
is a fully static asset bundle (HTML + JS + CSS) deployed behind the
same reverse proxy that fronts the backend. SvelteKit's server-side
rendering features would be unused; the hash-router approach avoids
any server rewrite rules for client routes.

## 3. Project Layout

```
frontend/
├── package.json                # npm package manifest
├── package-lock.json           # committed lockfile
├── vite.config.ts              # Vite build config
├── tsconfig.json               # TypeScript config for .ts files
├── svelte.config.js            # Svelte compiler options
├── index.html                  # Vite entry HTML (single page)
├── public/
│   ├── config.js               # runtime config, loaded by index.html
│   │                           # BEFORE the bundled JS (see section 5)
│   └── favicon.svg
├── README.md                   # operator notes (how to develop/build)
├── SPEC.md                     # this document
└── src/
    ├── main.ts                 # Svelte app bootstrap
    ├── App.svelte              # top-level layout + <Router>
    ├── routes.ts               # path -> component mapping for svelte-spa-router
    ├── lib/
    │   ├── api.ts              # typed fetch wrapper (see section 9)
    │   ├── auth.ts             # session bootstrap + redirect logic
    │   ├── stores.ts           # session, current-question, toast stores
    │   ├── time.ts             # countdown / relative-time helpers
    │   ├── types.ts            # TypeScript interfaces mirroring backend
    │   │                       # Pydantic models (Question, ResponseOption,
    │   │                       # SubmittedResponse, QuestionDetail, etc.)
    │   └── tally.ts            # client-side preview of the tally rules
    │                           # described in section 9.6 of the backend
    │                           # spec; used ONLY for the "current status"
    │                           # widget, never as authoritative
    ├── components/
    │   ├── NavBar.svelte
    │   ├── Footer.svelte
    │   ├── AuthGuard.svelte    # wraps any route that needs a session
    │   ├── ToastHost.svelte    # site-wide ephemeral notifications
    │   ├── QuestionCard.svelte # one row in the dashboard tabs
    │   ├── QuestionList.svelte # the two-tab pane (see section 8.2)
    │   ├── QuestionForm.svelte # shared create/edit form
    │   ├── ResponseOptionEditor.svelte  # discriminated-union builder
    │   ├── ResponseForm.svelte # voter-side response submission
    │   ├── TallyPanel.svelte   # live tally summary on the detail page
    │   ├── ResponseTimeline.svelte # full per-voter response history
    │   ├── CountdownBadge.svelte    # closes_at -> "2d 14h" badge
    │   ├── ProjectPicker.svelte     # select project_id from session
    │   ├── ApprovalTypeSelector.svelte
    │   ├── BindingBadge.svelte
    │   ├── PrivacyBadge.svelte
    │   └── ErrorAlert.svelte
    ├── pages/
    │   ├── Dashboard.svelte    # path "/" - the two-tab landing page
    │   ├── NewQuestion.svelte  # path "/question/new"
    │   ├── QuestionView.svelte # path "/question/:id"
    │   ├── EditQuestion.svelte # path "/question/:id/edit"
    │   ├── Resolution.svelte   # path "/resolution/:id" (read-only mirror
    │   │                       # of GET /resolution/{id})
    │   ├── NotFound.svelte     # path "*" fallback
    │   └── LoginRequired.svelte # shown briefly while redirecting
    └── styles/
        ├── theme.scss          # Bootstrap variable overrides + custom rules
        └── icons.scss          # Font Awesome import + local overrides
```

The `public/config.js` file is deliberately placed outside the bundled
`src/` tree so operators can edit it on a deployed instance without
rebuilding the app. See section 5 for the runtime-config contract.

## 4. Build and Dependency Management

The project is managed with `npm`. Typical commands:

```bash
# install dependencies (writes to ./node_modules using package-lock.json)
npm ci

# run the dev server with hot-reload on http://localhost:5173
npm run dev

# typecheck (does not emit)
npm run check

# build production assets into ./dist
npm run build

# preview the built bundle locally (sanity check before deploy)
npm run preview
```

`vite.config.ts` configures a dev-time proxy so that
`/api` requests from the dev server are forwarded to
`http://localhost:8085` (the backend's default bind). This avoids
CORS in development without baking a dev-only base URL into the
config file:

```ts
// vite.config.ts (excerpt)
export default defineConfig({
  plugins: [svelte()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8085",
        changeOrigin: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
```

Note that the proxy strips the `/api` prefix because the backend mounts
its routes at the root (e.g. `/list`, `/auth`, `/question/...`). In
production the reverse proxy applies the same prefix strip; the
frontend always speaks `{API_BASE}/...` and never knows whether the
backend is mounted at the root or behind a prefix.

## 5. Runtime Configuration (`public/config.js`)

The frontend has exactly one runtime configuration knob: the base URL
prepended to every API call. It lives in `public/config.js`, which is
served as a plain script and loaded by `index.html` **before** the
Svelte bundle:

```html
<!-- index.html (excerpt) -->
<script src="/config.js"></script>
<script type="module" src="/src/main.ts"></script>
```

`public/config.js` is intentionally tiny:

```js
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
  PRODUCT_NAME: "CAP",
};
```

`src/lib/api.ts` reads `window.CAP_CONFIG` once at module init,
substitutes defaults for any missing key, and freezes the resolved
object so that no later code can mutate the live configuration. If
`window.CAP_CONFIG` is absent (e.g. an operator deleted the file),
the defaults above apply and a single `console.warn` is emitted.

Compile-time configuration via `.env` is **not** used. The deployment
story is "drop the static bundle next to a `config.js`," and that
file is the only thing an operator should ever need to edit
post-build.

## 6. Authentication and Session Handling

### 6.1 Session shape

`GET {API_BASE}/auth` is the canonical session probe. The backend
returns an `asfquart.ClientSession` dictionary when the caller is
logged in (see section 3.1 of the backend spec for the dict-normalization
detail). For the purposes of the frontend the response is treated as
the following TypeScript interface, declared in `src/lib/types.ts`:

```ts
export interface UserSession {
  uid: string;                 // ASF UID, e.g. "alice"
  fullname?: string | null;    // human-readable name, may be absent
  isRoot: boolean;             // session.isRoot from asfquart
  projects: string[];          // projects the user may file against
  committees: string[];        // committees the user is on; superset
                               // of "projects" for which they may file
                               // PRIVATE questions
}
```

The `projects` and `committees` lists are taken verbatim from the
asfquart session. The frontend treats `projects` as "any project the
user is associated with (committer, PMC member, contributor)" and
`committees` as "the strictly stronger set of committees the user
serves on." Anyone in `committees[i]` is also in `projects[i]`; the
frontend never asserts this and tolerates it not holding.

If the session response is missing the `isRoot`, `projects`, or
`committees` keys, the frontend treats them as `false` and `[]`
respectively rather than crashing. This is a defensive concession
because `asfquart` is the authority on session shape; the frontend
adapts to what it actually receives.

### 6.2 Bootstrap sequence

`src/lib/auth.ts` exposes a single `loadSession()` function. It is
called exactly once, by `App.svelte` during its `onMount`. The
sequence is:

1. Set `session.loading = true` (a writable store).
2. `fetch(API_BASE + "/auth", { credentials: "include", headers: { Accept: "application/json" } })`.
3. On `200`, parse the JSON body; if it has a `uid` field, populate
   the `session` store with the user and set `session.loading = false`.
4. On `401`, or on a `200` that does not look like a session (no
   `uid`), set `session.user = null`, `session.loading = false`,
   and (only if the current route requires a session, see 6.3)
   trigger the OAuth redirect described below.
5. On any other status, populate `session.error` with a human-readable
   message and render the `<ErrorAlert>` component on the dashboard.
   The user is offered a "retry" button that re-invokes
   `loadSession()`.

### 6.3 Redirect to OAuth

Any route that requires a session is wrapped in `<AuthGuard>`. When
`session.user === null` after `loadSession()` resolves, `AuthGuard`:

1. Computes the desired post-login URL as the current location
   (origin + pathname + hash) so the user lands back where they
   were after the OAuth handshake.
2. Replaces the browser location with
   `window.CAP_CONFIG.LOGIN_URL || (API_BASE + "/auth?login")`,
   appending `&redirect=<encoded>` so the asfquart gateway can
   bounce back. The exact query parameter is the asfquart
   convention (`redirect=`); if the backend is later configured
   to use a different name, only the constant in `auth.ts`
   changes.
3. While the redirect is in flight, the user briefly sees a
   `LoginRequired.svelte` page consisting of a centered Font
   Awesome spinner (`fa-circle-notch fa-spin`) and the text
   "Redirecting to ASF login...". This page is the only fallback
   route that does NOT itself sit behind `<AuthGuard>`.

The `/` route (Dashboard), all `/question/...` routes, and
`/resolution/...` are wrapped in `<AuthGuard>`. The `*` fallback
(`NotFound.svelte`) is **not** wrapped, so an unauthenticated user
who lands on a typo-ed URL sees a clean 404 page rather than being
bounced through OAuth.

### 6.4 Logout

A logout link in `<NavBar>` simply navigates the browser to
`{API_BASE}/auth?logout` and lets the backend's asfquart gateway
clear the session cookie. The frontend does not manage its own
session cookie or token. After the redirect returns, the next
`loadSession()` call will observe an unauthenticated state.

### 6.5 Permission checks (client-side)

All authorization is enforced by the backend. The frontend's
permission checks exist purely to hide UI controls that would
result in a guaranteed 403 if invoked. The rules mirror the
backend spec:

| Action                                | Visible when                                                              |
|---------------------------------------|---------------------------------------------------------------------------|
| "New question" button (public)        | `session.projects` is non-empty                                           |
| "Mark this question private" checkbox | the selected `project_id` is in `session.committees`                      |
| "Edit" / "Withdraw" / "Resolve" links | `question.requester === session.uid` or `session.isRoot`, and `status==='open'` |
| "Respond" form                        | `question.status === 'open'` and `question` is in `/list` (see section 7) |
| "All projects" dashboard switch       | `session.isRoot === true` or `session.committees.includes("tooling")` (privileged viewers); see section 8.2 |

The frontend never tries to derive view-access for a private
question by itself; instead it relies on the fact that
unauthorized callers receive `404` from the backend (per section
7.5 of the backend spec) and renders the standard "not found"
page in that case.

## 7. Routing and Page Structure

Routing is hash-based via `svelte-spa-router`. The choice of hash
routes lets the SPA be deployed as a flat directory of static files
behind any web server without rewrite rules; the URL of the
dashboard, for example, is `https://cap.apache.org/#/`.

| Hash route               | Component             | Auth     | Notes                                            |
|--------------------------|-----------------------|----------|--------------------------------------------------|
| `/`                      | `Dashboard.svelte`    | required | Two-tab landing page                             |
| `/question/new`          | `NewQuestion.svelte`  | required | Visible only if `session.projects` is non-empty  |
| `/question/:id`          | `QuestionView.svelte` | required | Detail view + tally + response form              |
| `/question/:id/edit`     | `EditQuestion.svelte` | required | Mirrors `QuestionForm` in "edit" mode            |
| `/resolution/:id`        | `Resolution.svelte`   | required | Mirrors `GET /resolution/{id}` (read-only)       |
| `*` (everything else)    | `NotFound.svelte`     | none     | Static 404 page with a "Return to dashboard" link|

`App.svelte` lays out the page as:

```
+---------------------------------------------------+
| NavBar (logo, product name, session info, logout) |
+---------------------------------------------------+
|                                                   |
|  <Router routes={routes} />   <- main content     |
|                                                   |
+---------------------------------------------------+
| Footer (links to ASF, backend OpenAPI doc, etc.)  |
+---------------------------------------------------+
| ToastHost (fixed bottom-right ephemeral toasts)   |
+---------------------------------------------------+
```

The NavBar shows, on the right side:
- The user's `fullname || uid`
- A small caret-down opening a dropdown with: "Your projects",
  "Your committees", "Logout".

If the user has `isRoot=true`, a small red "root" badge is added
next to the username so a privileged session is visually obvious.

## 8. Components

### 8.1 `<QuestionCard>`

One card per row in the dashboard tabs. Renders, in a Bootstrap
`.card` with a left border colored by status:

- Top line: question title (linked to `/question/:id`), with a
  `<PrivacyBadge>` (Font Awesome lock icon if `is_private`) and a
  `<BindingBadge>` (gavel icon if `viewer_is_binding`).
- Second line: project, requester, target audience, separated by
  `·`.
- Third line: a `<CountdownBadge>` showing time remaining
  (`time_remaining_seconds`) for open questions, or the resolution
  outcome (`approved` / `vetoed` / `insufficient_votes` /
  `withdrawn`) for closed ones, with a Font Awesome icon per
  outcome.
- Right side: a "Respond" button (open + caller is in the question's
  audience) or a "View tally" button (closed).

### 8.2 `<QuestionList>` (the two-tab pane)

The dashboard's main widget. Two Bootstrap nav-tabs, both lazily
populated:

| Tab title                       | Source                                                                                                            |
|---------------------------------|-------------------------------------------------------------------------------------------------------------------|
| **Awaiting your response**      | `GET /list`, filtered client-side to questions where the caller has not yet submitted a response                  |
| **Recent activity**             | Computed from `/list` + per-question `GET /question/:id` calls (only when the dashboard expands a row), constrained to questions created or resolved within the last 30 days where the user is on the project/committee or has responded |

The "Awaiting your response" tab is the cheap path: a single
`GET /list` populates it. The "Recent activity" tab is a thin
synthesis: it shows everything from `/list` whose `status` is still
`open`, **plus** any resolved questions in the last 30 days that
the caller can see. Because `/list` only returns open questions
(section 9.1 of the backend spec), the "Recent activity" tab pulls
resolved entries by issuing additional `GET /question/:id` requests
for the question ids it has already observed in the user's history.
In practice this means the tab fills in lazily as the user
interacts with questions; a follow-up backend iteration may add a
dedicated "history" endpoint, at which point this tab switches to
use it.

Within each tab:

- A search/filter input at the top filters by title and project
  client-side. Filtering does NOT touch the backend.
- An **"All projects"** Bootstrap form-switch sits immediately to
  the right of the filter input. It is rendered **only** for
  privileged viewers, defined as `session.isRoot === true` or
  `session.committees.includes("tooling")`; non-privileged viewers
  never see the switch because the backend has already narrowed
  `/list` to their audience. The switch controls the project
  scope of both tabs:
  - **Off (default).** Both tabs are restricted to questions whose
    `project_id` is in the viewer's `session.projects` or
    `session.committees`. This is the same scope a non-privileged
    viewer would have, so a root or `tooling` member can run the
    dashboard "as themselves" without being drowned in cross-project
    traffic.
  - **On.** No project restriction is applied; the viewer sees
    every question the backend returned. This matches the
    pre-switch behavior for root/`tooling` viewers and is what
    they want when triaging activity across the foundation.
  The switch's label is intentionally terse ("All projects") and
  carries an explanatory `title` tooltip. The state is component-
  local and resets to "off" on every page load; persisting it is
  out of scope for this iteration.
- Sorting is newest first by `created_at` for "Recent activity" and
  by ascending `closes_at` for "Awaiting your response" (so the
  soonest-to-close items are at the top).
- An empty state shows a Font Awesome icon and the text
  "Nothing here. (Awaiting your response: you have no open
  questions to vote on.)" or the equivalent message for the
  other tab.
- A refresh button (`fa-arrows-rotate`) at the top right re-issues
  the underlying fetches.

### 8.3 `<QuestionForm>` (create and edit)

A single component used by `NewQuestion.svelte` and
`EditQuestion.svelte`. The mode is selected by a `mode: "create" |
"edit"` prop. Layout:

```
+----------------------------------------------------+
| Title           [ text input, max 200 chars     ]  |
| Description     [ textarea, max 10,000 chars    ]  |
| Project         [ <ProjectPicker> ]                |
| Target audience [ text input ]                     |
| Approval type   [ <ApprovalTypeSelector> ]         |
| Closes at       [ datetime-local input ]           |
| Is binding      [ checkbox, disabled in edit mode ]|
| Is private      [ checkbox, only visible if the    |
|                   selected project is in           |
|                   session.committees ]             |
| Response option [ <ResponseOptionEditor> ]         |
+----------------------------------------------------+
| [ Cancel ]                       [ Create / Save ] |
+----------------------------------------------------+
```

Fields that the backend forbids changing in edit mode
(`project_id`, `approval_type`, `is_binding`, `request_id`) are
rendered read-only when `mode === "edit"`, with a small tooltip
explaining why ("Cannot be changed once the question is filed").

On submit:

- `mode === "create"`: `POST {API_BASE}/question` with a
  `CreateQuestionRequest` body. On success, navigates to
  `/question/:id` of the new question.
- `mode === "edit"`: `PATCH {API_BASE}/question/:id` with an
  `EditQuestionRequest` body containing only the fields whose
  value differs from the original. On success, navigates back to
  `/question/:id`.

Client-side validation mirrors the backend's Pydantic constraints
exactly:

- `title`: non-empty, length <= 200
- `description`: non-empty, length <= 10000
- `closes_at`: strictly in the future (server enforces this also)
- `target_audience`: non-empty
- `response_option`: shape-valid per its `kind`

The form does NOT pre-validate request_id; it generates one on the
client (a ULID-style string) for new questions.

### 8.4 `<ResponseOptionEditor>`

A discriminated-union builder for `response_option`. The user
picks a `kind` from a dropdown (`vote`, `lazy_consensus`,
`free_text`), and the rest of the form reshapes to match:

- **`vote`** — a multi-select of which of `["+1", "+0", "-0",
  "-1"]` are permitted (defaults to all four), plus an
  `allow_comment` toggle.
- **`lazy_consensus`** — an `allow_comment` toggle. No other
  options.
- **`free_text`** — a `max_length` number input (default 4000,
  min 1, max 10000).

The editor enforces the compatibility constraints that follow from
the approval-type semantics in section 8.3.1 of the backend spec.
Currently those constraints are:

- `approval_type = "lazy_consensus"` requires `response_option.kind`
  to be `"lazy_consensus"`.
- `approval_type = "unanimous_approval"` requires
  `response_option.kind === "vote"` and `"-1"` to be in
  `allowed_values` (so a veto is even expressible) and
  `allow_comment === true` (vetoes require a comment).
- `approval_type = "majority_approval"` accepts either `"vote"` or
  `"free_text"`.

When the user changes `approval_type` to something incompatible
with the currently-selected `response_option.kind`, the editor
snaps to the simplest compatible default and shows a small banner:
"Approval type changed; response options reset to the default for
this type."

### 8.5 `<ResponseForm>`

The voter-side counterpart. Receives the loaded `Question` as a
prop and renders a form whose shape depends on
`question.response_option.kind`:

- **`vote`**: radio buttons over `allowed_values`. If
  `allow_comment`, a `<textarea>` labeled "Comment (optional, but
  required for a `-1` veto on unanimous approval)" appears beneath.
  The form refuses to submit a `-1` on a `unanimous_approval`
  question with `viewer_is_binding=true` unless the comment is
  non-empty (matching the 400 the backend would otherwise return).
- **`lazy_consensus`**: a single "I object" checkbox, plus an
  optional comment if `allow_comment`. Submitting with the box
  unchecked is functionally a no-op response (`objection=false`),
  which the UI explains under the box: "Silence is assent. Submit
  with this box checked only if you object."
- **`free_text`**: a single `<textarea>` with a character counter
  bounded by `max_length`.

On submit, `POST {API_BASE}/question/:id/responses` with a
`SubmittedResponse` body. The backend endpoint (section 9.7 of
the backend spec) is implemented, so the submit button is live;
`RESPONSE_SUBMISSION_ENABLED` in `src/lib/api.ts` stays as a
single-flag kill switch (set to `false` if an operator needs to
temporarily disable submission client-side without a backend
change).

If the voter has previously responded to this question (visible
via the `responses` array in `QuestionDetail`), the form
pre-populates from the latest entry and the submit button reads
"Update response" instead of "Submit response." The backend
treats this as a new row (append, not update), per section 7.2
of the backend spec; the UI does not pretend otherwise.

### 8.6 `<TallyPanel>`

Shows the current state of a question on the detail page. Its
content depends on `question.status`:

- **`open`**: a live tally computed client-side from the loaded
  `responses` array using `src/lib/tally.ts`, which mirrors the
  rules in section 9.6 of the backend spec. The panel makes it
  clear that this is a preview ("Provisional tally; not yet
  resolved") and shows a per-`approval_type` breakdown:
  - `unanimous_approval`: "No veto" or "Vetoed by <uid>: <comment>"
  - `majority_approval`: binding +1 / 0 / -1 counts, with
    non-binding counts in a muted secondary line
  - `lazy_consensus`: "No objection" or "Objection from <uid>"
- **`resolved`**: the outcome (`approved` / `vetoed` /
  `insufficient_votes`), the tally object from the backend's
  resolve audit row (fetched from `GET /resolution/:id`), and the
  permalink rendered as a clickable URL with a "copy to
  clipboard" button (Font Awesome `fa-clipboard`).
- **`removed`**: a single line "Withdrawn by <requester> on
  <date>".

The client-side tally is **never** authoritative. The backend's
resolve action is the source of truth; the panel just gives users
a fast read on where the question stands.

### 8.7 `<ResponseTimeline>`

A scrollable list of every response in the question's `responses`
array, ordered oldest first (matching the backend's order in
`QuestionDetail.responses`). Each row shows:

- The voter's UID (linked to `https://whimsy.apache.org/roster/committer/<uid>`)
- A binding/non-binding chip
- A veto chip if `is_veto`
- The submitted value (e.g. `+1`, `Objection`, free text excerpt)
- The comment (if any), expandable
- The submission timestamp in the viewer's local time, plus the
  ISO-UTC timestamp as a tooltip

Superseded responses (a voter's earlier vote that they later
amended) are dimmed and marked "superseded by <uid>'s later
response." This is how the UI surfaces veto withdrawals
(section 8.3.1 of the backend spec).

### 8.8 `<CountdownBadge>`

A small chip showing the time remaining on a question. The
component takes `closes_at` and `time_remaining_seconds` as
props; on mount it starts a 1-second `setInterval` that
decrements the remaining time locally, and re-renders. When the
value crosses zero, the chip switches to "Closed" with a clock
icon, and a custom event is dispatched so the parent can refetch
the question detail.

The badge color follows Bootstrap's contextual classes:

| Time remaining          | Badge class       |
|-------------------------|-------------------|
| > 24h                   | `bg-secondary`    |
| 1h..24h                 | `bg-warning`      |
| < 1h                    | `bg-danger`       |
| 0 (closed)              | `bg-dark`         |

### 8.9 `<ErrorAlert>`

A reusable inline error panel. Used everywhere an API call can
fail. Renders the backend's error payload (per the
`AuthenticationRequired` and `ErrorMessage` schemas in the backend
spec) and a "retry" callback. For `401`, the alert does not render
at all; the `AuthGuard` flow takes over and the redirect happens.

## 9. API Client (`src/lib/api.ts`)

A single typed wrapper sits between the components and `fetch`. Every
component imports from `src/lib/api.ts`; no component ever calls
`fetch` directly.

```ts
// src/lib/api.ts (shape, not full code)
const cfg = Object.freeze({
  API_BASE: window.CAP_CONFIG?.API_BASE ?? "/api",
  LOGIN_URL: window.CAP_CONFIG?.LOGIN_URL ?? null,
});

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> { /* ... */ }

export const api = {
  getSession: () => request<UserSession>("GET", "/auth"),
  list: () => request<ListResponse>("GET", "/list"),
  createQuestion: (body: CreateQuestionRequest) =>
    request<Question>("POST", "/question", body),
  getQuestion: (id: number) =>
    request<QuestionDetail>("GET", `/question/${id}`),
  editQuestion: (id: number, body: EditQuestionRequest) =>
    request<Question>("PATCH", `/question/${id}`, body),
  withdrawQuestion: (id: number) =>
    request<void>("DELETE", `/question/${id}`),
  resolveQuestion: (id: number) =>
    request<Question>("POST", `/question/${id}/resolve`),
  submitResponse: (id: number, body: SubmittedResponse) =>
    request<StoredResponse>("POST", `/question/${id}/responses`, body),
  getResolution: (id: number) =>
    request<ResolutionRecord>("GET", `/resolution/${id}`),
};
```

Behavior baked into `request`:

- All requests carry `credentials: "include"` so the asfquart
  session cookie is sent.
- `Accept: application/json` is sent on every request, which is
  what triggers the JSON-shaped 401 from the backend (per section 6
  of the backend spec) rather than an HTML redirect.
- `Content-Type: application/json` is set when `body !== undefined`.
- A `401` response with a JSON body whose `error ===
  "authentication_required"` immediately invokes the OAuth-redirect
  flow from section 6.3; the returned promise rejects with a
  sentinel so callers stop processing.
- A `404` from `getQuestion` / `getResolution` is surfaced as a
  typed `NotFoundError` (rather than a generic HTTP error), so
  pages can render `NotFound.svelte` directly.
- A `409` from `submitResponse` / `withdrawQuestion` /
  `resolveQuestion` is surfaced as a typed `ConflictError` carrying
  the backend's `ErrorMessage` body so the UI can display the
  specific reason ("Deadline has passed," "Question already
  resolved").
- A `403` is surfaced as a typed `ForbiddenError`; the UI shows
  "You do not have permission to perform this action." rather than
  the literal backend message (which may leak audience hints).
- Every other non-2xx is surfaced as a generic `ApiError` whose
  `.status` and `.body` are forwarded verbatim to `<ErrorAlert>`.

`src/lib/types.ts` mirrors the Pydantic models from the backend
spec one-to-one. Any drift between the two is a bug; the test suite
includes a contract test (see section 13) that fetches
`GET {API_BASE}/api` (the OpenAPI document) and asserts that every
field used by `src/lib/api.ts` is still present in the schema.

## 10. State Management (`src/lib/stores.ts`)

The frontend's persistent state is small enough that Svelte's
built-in stores suffice; no external state library is used.

| Store              | Type                              | Lifetime / purpose                                  |
|--------------------|-----------------------------------|-----------------------------------------------------|
| `session`          | `writable<SessionState>`          | Loaded once on app boot; read by every guarded page |
| `questionsCache`   | `writable<Map<number, QuestionDetail>>` | LRU-ish cache for question details (max 50)   |
| `toasts`           | `writable<Toast[]>`               | Bottom-right ephemeral notifications                |
| `currentQuestion`  | `derived` of `questionsCache`     | Convenience wrapper for `QuestionView.svelte`       |

`SessionState` is:

```ts
type SessionState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "ready"; user: UserSession }
  | { status: "error"; message: string };
```

`session` is the single source of truth for "is the user logged
in." `AuthGuard` subscribes to it, redirects on `anonymous`, shows a
spinner on `loading`, and renders its slot on `ready`. No other
piece of code is allowed to derive auth state from `document.cookie`
or similar.

`questionsCache` is populated by `getQuestion()` calls and
invalidated on `editQuestion`, `withdrawQuestion`,
`resolveQuestion`, and `submitResponse`. The cache is purely a
latency optimization; no UI element treats it as authoritative
beyond the lifetime of the page.

`toasts` is a small list of `{ id, level, message, ttlMs }`
entries. `ToastHost.svelte` renders them as Bootstrap toasts in the
bottom-right corner and removes them after their TTL elapses.

## 11. Forms (Detailed Field Mapping)

This section is the per-form reference. Each field lists the
underlying backend type (from the Pydantic models in section 8 of
the backend spec) and the HTML element used to render it.

### 11.1 `CreateQuestionRequest` (NewQuestion page)

| Field             | Pydantic type                                          | UI element                                    |
|-------------------|--------------------------------------------------------|-----------------------------------------------|
| `request_id`      | `str` (RequestID)                                      | Hidden, generated client-side as a ULID       |
| `project_id`      | `str` (must be in `session.projects`)                  | `<ProjectPicker>` (dropdown of projects)      |
| `title`           | `str`, max 200                                         | `<input type="text" maxlength="200">`         |
| `description`     | `str`, max 10000                                       | `<textarea maxlength="10000" rows="8">`       |
| `target_audience` | `str`                                                  | `<input type="text">`                         |
| `approval_type`   | `Literal["unanimous_approval","majority_approval","lazy_consensus"]` | `<ApprovalTypeSelector>` (radio cards) |
| `is_binding`      | `bool`                                                 | `<input type="checkbox">`                     |
| `is_private`      | `bool` (only enabled if project in `session.committees`) | `<input type="checkbox">`                   |
| `response_option` | discriminated union of `VoteOption / LazyConsensusOption / FreeTextOption` | `<ResponseOptionEditor>`        |
| `closes_at`       | `datetime` (ISO 8601 UTC)                              | `<input type="datetime-local">` + UTC convert |

The `<ApprovalTypeSelector>` is a three-card radio layout, each
card showing the type's name, a one-line description, and an icon
(`fa-balance-scale` for unanimous, `fa-thumbs-up` for majority,
`fa-feather` for lazy consensus). This matches the visual
vocabulary at <https://agenda.apache.org/>.

### 11.2 `EditQuestionRequest` (EditQuestion page)

Only the editable subset (per section 9.4 of the backend spec):
`title`, `description`, `target_audience`, `closes_at`,
`is_private`, `response_option`. All other fields in the form are
read-only, with their values pulled from the existing question.

The form computes the PATCH body as the diff between the original
question and the current form state, so a no-op edit produces an
empty body which the backend correctly handles as a no-op
(section 9.4 of the backend spec).

### 11.3 `SubmittedResponse` (ResponseForm)

| `kind`             | UI element                                                            |
|--------------------|------------------------------------------------------------------------|
| `vote`             | Radio group over `allowed_values`; optional `<textarea>` comment       |
| `lazy_consensus`   | Single "I object" checkbox; optional `<textarea>` comment              |
| `free_text`        | Single `<textarea>` bounded by `max_length` with a character counter   |

The submit handler:

1. Constructs the appropriate `SubmittedResponse` variant.
2. Calls `api.submitResponse(id, body)`.
3. On `201`, refreshes `questionsCache.get(id)`, pushes a
   success toast ("Response recorded"), and stays on the
   question detail page so the user can see their entry in
   `<ResponseTimeline>`.
4. On `400 missing_veto_comment`, focuses the comment textarea
   and shows the message inline next to it. Other `400` error
   codes (`response_kind_mismatch`, `value_not_allowed`,
   `text_too_long`, `invalid_body`) are surfaced verbatim in
   the form's `<ErrorAlert>`; the UI does not pre-validate
   against these because the same constraints are already
   enforced by `<ResponseOptionEditor>` for the editing user
   and by `<ResponseForm>`'s field shapes for the voter, so a
   `400` here is genuinely an out-of-band write (e.g. a
   question edited mid-response that narrowed `allowed_values`).
5. On `409`, displays the backend's `ErrorMessage` body in the
   form's error alert and disables the submit button (the
   question is no longer open).
6. On `404`, replaces the entire page with `NotFound.svelte` (the
   caller has lost view access since the page loaded).

## 12. Visual Design

### 12.1 Reference

The visual idiom is taken from <https://agenda.apache.org/>: a
clean Bootstrap theme with an Apache-feather logo in the top-left,
a thin top navigation bar with the product name, a generous
content column on a white background, soft `card` surfaces for
each entity, and contextual colors (Bootstrap's
`primary/secondary/success/warning/danger`) for status chips.

Specifically, the frontend matches agenda.apache.org on:

- **Typography**: the default Bootstrap stack (`system-ui`)
  augmented with `"Helvetica Neue", Arial, sans-serif`. No web
  font is loaded.
- **Color palette**: Bootstrap defaults with one override; the
  primary accent is `#3a5e8c` (a muted Apache-blue) rather than
  the stock `#0d6efd`. The override lives in
  `src/styles/theme.scss` as `$primary: #3a5e8c;`.
- **Density**: compact (`$enable-rounded: true; $border-radius:
  .375rem;`). Cards and tables use `table-sm` / `.p-3` rather than
  `.p-4` to keep the dashboard scannable on a 13" laptop.
- **Iconography**: Font Awesome Free for every glyph. No raster
  images other than the favicon and the Apache feather (an SVG in
  `public/feather.svg`).

### 12.2 Navbar

A single Bootstrap `.navbar.navbar-expand-md.navbar-dark.bg-dark`
across the top, containing:

- Left: the Apache feather SVG, then the product name
  (`window.CAP_CONFIG.PRODUCT_NAME` defaulting to "CAP").
- Center: a single `<a class="nav-link">` reading "Dashboard"
  (pointing to `#/`) and another reading "New question"
  (`#/question/new`), visible only when `session.projects` is
  non-empty.
- Right: the user dropdown described in section 7.

### 12.3 Page chrome

Each page sets its own `<svelte:head>` `<title>`:

| Route                | Title                                        |
|----------------------|----------------------------------------------|
| `/`                  | `CAP - Dashboard`                            |
| `/question/new`      | `CAP - New question`                         |
| `/question/:id`      | `CAP - <question title>` (after load)        |
| `/question/:id/edit` | `CAP - Edit <question title>`                |
| `/resolution/:id`    | `CAP - Resolution #<id>`                     |

A page is laid out inside a `.container` with `max-width: 960px`
(narrower than Bootstrap's default `lg` breakpoint) so long
descriptions remain readable. Forms use `.row.g-3` with
`.col-md-6` for two-up rows and `.col-12` for full-width rows.

### 12.4 Status colors

| Status / outcome      | Class             | Icon (Font Awesome Free)        |
|-----------------------|-------------------|---------------------------------|
| `open`                | `text-secondary`  | `fa-regular fa-clock`           |
| `approved`            | `text-success`    | `fa-solid fa-check`             |
| `vetoed`              | `text-danger`     | `fa-solid fa-ban`               |
| `insufficient_votes`  | `text-warning`    | `fa-solid fa-triangle-exclamation` |
| `withdrawn`           | `text-muted`      | `fa-solid fa-xmark`             |
| `is_private`          | `bg-warning text-dark` | `fa-solid fa-lock`         |
| `viewer_is_binding`   | `bg-primary`      | `fa-solid fa-gavel`             |

### 12.5 Empty and error states

Every list, table, and detail panel has an explicit empty state
that includes:

- A relevant Font Awesome icon, displayed at 3x scale and muted
  (`text-muted opacity-50`)
- A one-line title
- An optional one-line explanation
- An optional CTA button (e.g. "File a new question" on the empty
  Dashboard)

Error states use `<ErrorAlert>` with `class="alert alert-danger"`
plus a `fa-solid fa-circle-exclamation` icon on the left.

## 13. Accessibility

- Every form control has an associated `<label>` (no placeholder-as-label).
- Color is never the only carrier of meaning; every status chip
  carries both an icon and a textual label.
- Tab order matches visual order; modals trap focus via
  `bootstrap.bundle.min.js` (Bootstrap's built-in handling).
- `aria-live="polite"` on `<ToastHost>` so screen readers
  announce new toasts.
- The countdown badge's `aria-label` reads as
  "Closes in 2 days 14 hours"; the raw `mm:ss` digits are
  visual-only.
- Keyboard shortcuts: `g d` returns to the dashboard, `g n`
  opens the new-question form. Both are documented in a `?` modal
  bound to the `?` key, which lists every shortcut.

## 14. Testing Notes

The test suite lives under `frontend/tests/` and runs through
`npm run test` (vitest). A separate GitHub workflow at
`.github/workflows/frontend-ci.yml` runs `npm run check` and
`npm run test` on every push and pull request that touches
`frontend/`.

Coverage by area:

- **API client** (`tests/api.test.ts`): every wrapper method is
  exercised against a `msw` (Mock Service Worker) handler that
  fakes the backend's responses. Asserts that `401` triggers a
  redirect, `409` produces a `ConflictError`, etc.
- **Stores** (`tests/stores.test.ts`): `session` transitions
  through `loading -> anonymous`, `loading -> ready`, and
  `loading -> error`. `questionsCache` is invalidated correctly
  on `editQuestion` / `withdrawQuestion` / `resolveQuestion` /
  `submitResponse`.
- **`QuestionForm`** (`tests/QuestionForm.test.ts`): rendered in
  both create and edit modes; verifies that read-only fields are
  disabled in edit mode, that the privacy checkbox appears only
  when the selected project is in `session.committees`, and that
  the submitted PATCH body in edit mode contains only the
  changed fields.
- **`ResponseOptionEditor`** (`tests/ResponseOptionEditor.test.ts`):
  the compatibility rules from section 8.4 are tested end-to-end
  (changing `approval_type` snaps the option to a compatible
  default).
- **`ResponseForm`** (`tests/ResponseForm.test.ts`): for each
  `kind`, the form renders the correct controls; a binding `-1`
  on a `unanimous_approval` question without a comment cannot
  submit.
- **`QuestionList`** (`tests/QuestionList.test.ts`): the two tabs
  partition `/list` correctly; the search input filters
  client-side without re-fetching; the "All projects" switch is
  rendered only for `isRoot` and `tooling` viewers, defaults to
  off, and toggles the project-scope filter on both tabs.
- **Contract test** (`tests/contract.test.ts`): fetches
  `GET {API_BASE}/api` against a running backend (in CI) and
  asserts that every field referenced by `src/lib/types.ts` is
  present in the OpenAPI document. Drift is loud, not silent.
- **`AuthGuard`** (`tests/AuthGuard.test.ts`): when `session` is
  `anonymous`, the guard navigates to the configured login URL
  with `redirect=` set to the original location; when `loading`,
  it renders the spinner; when `ready`, it renders its slot.

## 15. Deployment

The build output (`dist/`) is a flat directory of static files:

```
dist/
├── index.html
├── config.js              # copied verbatim from public/config.js
├── favicon.svg
├── feather.svg
└── assets/
    ├── index-<hash>.js
    ├── index-<hash>.css
    └── ...
```

It is served by any HTTP server, typically the same reverse proxy
that fronts the backend (httpd, nginx, or Caddy). The proxy is
configured so that:

- `/api/*` is forwarded to the backend (with the `/api` prefix
  stripped, matching the dev-server proxy in section 4).
- Everything else is served from the static `dist/` directory.
- Requests for any path that does not match an existing file fall
  back to `dist/index.html`, so the hash-router can handle the
  client-side route. (This is the standard SPA fallback rule.)

Operators may edit `dist/config.js` in place to change
`API_BASE`, `LOGIN_URL`, or `PRODUCT_NAME` without rebuilding.
Cache headers should mark `config.js` as
`Cache-Control: no-cache`, and `assets/*` as
`Cache-Control: public, max-age=31536000, immutable` (the
filenames carry content hashes).

## 16. Open Questions

The items below are intentionally left open and will be resolved in
follow-up iterations. Each is sized so that resolving it does not
require revisiting decisions in earlier sections.

1. **History endpoint.** The "Recent activity" tab synthesizes its
   list from `/list` plus per-id lookups; a backend `/history` or
   equivalent would let it issue a single bulk fetch. The
   component is structured so the swap is contained inside
   `<QuestionList>`.
2. **Resolution page UI.** `Resolution.svelte` currently routes to
   the read-only mirror of `GET /resolution/{id}` (sections 9.8
   and 12.3 of the backend spec). Once the backend ships that
   endpoint, this page becomes the canonical "share this
   outcome" URL; until then it falls back to
   `GET /question/{id}` and renders the same `TallyPanel`.
3. **Real-time updates.** Pubsub events (section 10 of the
   backend spec) are not consumed in this iteration. A future
   iteration may add a small WebSocket or SSE bridge that
   subscribes to `cap.{project}.*` and invalidates
   `questionsCache` entries reactively; the cache abstraction in
   `src/lib/stores.ts` is the only file that needs to change.
4. **Theme variants.** A dark mode is plausible but unscoped; the
   accent override in `theme.scss` is currently the only deviation
   from Bootstrap defaults. A future iteration may add a
   `prefers-color-scheme: dark` overlay.
5. **Mobile layout.** Cards and forms wrap to single-column at
   Bootstrap's `md` breakpoint already; an explicit phone layout
   (collapsing the navbar, full-bleed cards) is deferred.
