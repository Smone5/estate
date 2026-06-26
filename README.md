# Estate Steward 🕊️

> [!WARNING]
> **Estate Steward is a work in progress.** It is under active development, is not feature-complete, and may contain bugs, incomplete workflows, or breaking changes. Please do not rely on it for legal, fiduciary, or production use without independently reviewing and validating the results.

Estate Steward is an AI-powered, local-first probate mediation platform. It is designed to assist Executors and grieving families in navigating the emotional and logistical challenges of dividing estate keepsakes and personal property.

By using the **Maximum Nash Welfare (MNW)** algorithm, Estate Steward guarantees a fair, mathematically optimal distribution of assets based on private points allocations from the heirs.

## Key Features

- **Private Points Allocation**: Heirs assign points (out of 1,000) to items based on personal and sentimental value. All allocations are blind and private.
- **AI Mediator**: An integrated AI assistant (using local models) helps heirs explore the catalog, recount sentimental stories, and ask questions.
- **Fiduciary Compliance**: Compiles a mathematically fair, cryptographically sealed Probate Audit Ledger for court filing.
- **Privacy First**: Fully local architecture (Docker). ID scans and chat transcripts are kept completely offline.
- **Digital Keepsakes**: Automatically generates personalized Keepsake Memory Book PDFs for each heir containing the history and allocations of the estate items.

## Architecture

This project is a **Monorepo** consisting of two main pieces:

1. **Frontend** (`/frontend`): A modern React application (Vite + React Router + Zustand).
2. **Backend** (`/backend`): A FastAPI Python server handling the database (PostgreSQL), fair division math, AI integration (Ollama / LangChain), and PDF generation.

---

## 🚀 Quickstart (Local Development)

### Prerequisites
- [Docker](https://docs.docker.com/get-docker/) & Docker Compose
- [Node.js](https://nodejs.org/) (for building the frontend)
- [uv](https://docs.astral.sh/uv/) (for generating the local encryption key — `pip install uv` or see their install docs)
- (Optional) [Ollama](https://ollama.ai/) installed locally if you wish to run the AI Mediator features locally.

### One-command setup

```bash
git clone https://github.com/your-org/estate-steward.git
cd estate-steward
./scripts/start_local.sh
```

This single script handles first-time setup end-to-end: it creates `.env` from `.env.example` if missing, generates a real `ENCRYPTION_KEY` (the app refuses to start with a placeholder one), points SMTP at the bundled Mailpit inbox for local testing, builds the frontend, starts the Docker stack, waits for Postgres, runs database migrations, and health-checks the backend before printing the URLs you need and first-run steps (creating the admin account, etc.).

Re-run the same command any time to restart everything — it's idempotent and safe to run repeatedly.

- **Frontend / first admin setup:** `http://localhost/admin`
- **Backend API docs:** `http://localhost:8000/docs`
- **Mailpit (Local Email Testing):** `http://localhost:8025`

### Manual setup (if you'd rather not run the script)

1. Copy the example environment file and set a real `ENCRYPTION_KEY` (see the comment in `.env.example` for how to generate one):
   ```bash
   cp .env.example .env
   ```
2. Run with Docker Compose:
   ```bash
   docker compose up --build
   ```
   - **Frontend:** `http://localhost`
   - **Backend API Docs:** `http://localhost/api/docs`
   - **Mailpit (Local Email Testing):** `http://localhost:8025`

---

## 📱 Installing on Your Phone (PWA)

Estate Steward is a Progressive Web App (PWA) — install it on a phone's home screen to test camera/photo capture, voice recording, and the mobile inventory workflow like a real user would.

```bash
./scripts/install_on_phone.sh
```

This builds the frontend, starts the Docker stack, and prints a link + QR code for your phone to scan.

> [!WARNING]
> Without HTTPS (i.e. no Cloudflare Tunnel configured), this falls back to your LAN IP over plain HTTP. That's fine for a quick look at the UI, but **voice recording will not work** — browsers require a secure context (HTTPS) for live audio capture, no exceptions. See the guides below for full setup and troubleshooting.

📖 **[Mobile & PWA Testing Guide](./docs/mobile-pwa-testing.md)** — full install walkthrough, why HTTPS matters, updating an installed app after code changes, and troubleshooting common phone issues.

📖 **[Cloudflare Tunnel Setup](./docs/cloudflare-tunnel-setup.md)** — step-by-step guide to getting a real `https://` URL for your local dev stack, required for full mobile feature testing.

---

## 📦 Deployment (Separated Deployments)

This monorepo is structured so that the **Frontend** and **Backend** can be deployed independently to different platforms (e.g., Vercel for Frontend, Render/AWS for Backend). 

### Option 1: Using Platform Integrations (Vercel, Netlify, Render)
Most modern platforms support "Root Directory" settings.
- **Frontend (Vercel/Netlify):** Connect your GitHub repository. In the build settings, set the **Root Directory** to `frontend`. The build command will automatically be `npm run build`.
- **Backend (Render/Heroku):** Connect your repository and set the **Root Directory** to `backend`. You can either use the provided `backend/Dockerfile` or native Python environments using `backend/requirements.txt`.

### Option 2: GitHub Actions
We have provided sample GitHub Actions in `.github/workflows/` that demonstrate how to trigger deployments separately based on path changes:
- `deploy-frontend.yml` triggers only when files in `/frontend/` change.
- `deploy-backend.yml` triggers only when files in `/backend/` change.

You can modify these workflows to push to your specific infrastructure (AWS ECS, SSH to VPS, etc.).

---

## 🤝 Contributing

Feedback and contributions are welcome, including from people who are new to open source. Please read [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup and pull request guidance.

### Reporting Bugs and Suggesting Improvements

If you find a problem or have an idea, please open a GitHub Issue using the repository's **Issues** tab.

Before opening an issue:

1. Search the existing issues to see whether it has already been reported.
2. Use a clear title and describe what you expected to happen and what happened instead.
3. Include steps that someone else can follow to reproduce the problem.
4. Include relevant environment details, such as your operating system, browser, Docker version, and any useful error messages or logs.
5. Remove passwords, API keys, personal information, estate records, and other sensitive data before sharing screenshots or logs.

Maintainers may ask follow-up questions, combine duplicate reports, or close issues that cannot be reproduced. A submitted issue is helpful feedback, but it does not guarantee that or when a fix will be released.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.
