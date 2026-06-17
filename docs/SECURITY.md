# ROScribe — Security Analysis

_Last reviewed: 2026-06-11. Scope: the public-facing NiceGUI app (`app/workspace.py`),
the scrape/ingest/index pipeline, and how secrets + data are handled._

## 1. What is exposed, and how

ROScribe runs as a single local Python process on port 8080. It is published to
the internet through a **Tailscale Funnel** at `https://roscribesl.tail37a12e.ts.net`
(`scripts/roscribe.sh`). So although the data, models, and database never leave the
machine, the **web surface is reachable by anyone on the internet**. The trust model
is therefore "public website backed by a private corpus", not "localhost tool".

Three entry points exist:

| Path | Auth | Notes |
|------|------|-------|
| `/` and the workspace | **Required** (session cookie) | Full app: search, breakdowns, chat, extractor |
| `/demo` | **None (public)** | Read-only browse + search + **AI chat + breakdowns** |
| `/login` | n/a | Username/password against `ROSCRIBE_USERS` |
| `/pdf/{name}`, `/logo/{name}` | None | Static file serving from `data/` |
| `/extractor` | Required | Upload + metadata extraction tool |

Auth is enforced by `AuthMiddleware`: any registered page route not in
`{"/login", "/demo"}` redirects to `/login` unless the session is authenticated.

## 2. Findings and fixes

### Fixed in this pass

- **Path traversal on `/pdf` and `/logo` (High).** Both routes joined the
  URL-supplied `name` straight onto a base directory and served the result. A
  crafted name (`..%2f..%2f..%2fetc%2fpasswd`, absolute paths, null bytes) could
  potentially read files outside the corpus. **Fix:** `_safe_child()` resolves the
  path and asserts it stays inside the base dir (`Path.relative_to`), rejects null
  bytes, and the PDF route now also requires a `.pdf` suffix. Verified: traversal
  vectors return 404, legitimate files still 200.

- **No brute-force protection on login (Medium).** Because the app is on a public
  funnel, the login form could be hammered indefinitely. **Fix:** timing-safe
  password comparison (`secrets.compare_digest`, so response time doesn't leak
  whether the username exists) plus an in-memory per-username throttle
  (`_LOGIN_FAILS`: 6 failures / 5-minute window). It survives cookie-clearing
  (server-side state) and is a sliding delay, so it can't permanently lock a user
  out. The account password is a random 10-char alnum string (~8×10¹⁷ space), so
  online brute force was already infeasible; this closes the unlimited-attempts gap.

- **Insecure default session secret (Medium).** `ROSCRIBE_STORAGE_SECRET` defaulted
  to a hardcoded constant. The session cookie is *signed* with this secret, so a
  known value lets anyone **forge an authenticated cookie and bypass login entirely**.
  `scripts/roscribe.sh` already writes a random 48-hex secret into `.env` on first
  start; **fix:** the app now prints a loud warning at startup if it's running on the
  default, so you can't accidentally expose it unsecured.

### Confirmed safe

- **Private TLS key is not committed.** `*.key` is gitignored and absent from the
  full git history (`git log --all` over `*.key` is empty). The `.crt` *is* tracked,
  which is fine — a certificate is public by design.
- **`.env` is gitignored** and not in history; secrets live there.
- **SQL is parameterised** throughout (`store.py`, `workspace.py`) — no string-built
  queries with user input. FTS5 `MATCH` strings are constructed from tokenised input
  with quoting, not raw concatenation.
- **Scraper is not an SSRF vector** — it fetches two fixed `supremecourt.lk` URLs;
  it does not follow user-supplied URLs.

### Open risks (reported, not changed — they need a product decision)

1. **The `/demo` page exposes the LLM to the public (Medium, cost/DoS).** Anyone can
   trigger `Ask ROS` chat and (implicitly) breakdown generation with no rate limit.
   Each call occupies the single shared llama.cpp context for 40–180 s. A handful of
   concurrent visitors can saturate the model and wedge the queue, and on a paid LLM
   provider this is also a cost vector. *Mitigations:* per-IP/session rate limit on
   chat + breakdown; disable chat on `/demo`; or a small request queue with a cap.
2. **Chat context overflow (reliability).** Per-case chat loads the full ~10k-token
   judgment and reserves 4096 output tokens; after several turns the history overflows
   `n_ctx` and re-triggers `llama_decode returned`. The history cap is still deferred
   (noted in CLAUDE/feature branch).
3. **Plaintext credentials in `.env`.** Acceptable for a single-user local deploy, but
   if this ever grows to multiple real users, move to hashed passwords (e.g. `bcrypt`).
4. **No CSRF/security headers.** NiceGUI is largely websocket-driven so classic CSRF
   is low-risk, but adding `X-Content-Type-Options`, a CSP, and `Referrer-Policy`
   would harden the static responses. Low priority behind the funnel.

## 3. Data-handling posture

The design goal — confidential legal data never leaves the machine — holds: judgments,
notes, embeddings (bge-m3), and the breakdown LLM (llama.cpp) all run locally. The only
outbound traffic is (a) the scraper fetching public judgments from `supremecourt.lk`
and (b) the "open this citation on the web" links, which open a Google search in the
user's browser (not server-side). If `LLM_PROVIDER` is ever switched to Anthropic/OpenAI,
judgment text would then be sent to that API — a deliberate trade-off to document.

## 4. Quick hardening checklist

- [x] Path-traversal guard on file routes
- [x] Login throttle + timing-safe compare
- [x] Startup warning on default session secret
- [ ] Rate-limit / queue the public LLM endpoints (`/demo` chat + breakdown)
- [ ] Cap chat history to fit `n_ctx`
- [ ] Security response headers / CSP
- [ ] Hashed passwords if the user base grows
