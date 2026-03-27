# Agent Platform

Multi-tenant AI Agent Deployment Platform. Launch your own AI agent in minutes.

## Features

- **Landing Page** - Modern SaaS marketing page with pricing tiers
- **User Dashboard** - Create, configure, and manage your AI agents
- **Admin Dashboard** - Platform-wide oversight, user management, agent deployment
- **JWT Auth** - Signup/login with secure token-based authentication
- **Firestore Backend** - Multi-tenant data isolation on GCP

## Tech Stack

- **Backend:** Python / FastAPI
- **Frontend:** HTML / CSS / JavaScript
- **Database:** Google Cloud Firestore
- **Auth:** JWT (python-jose + bcrypt)
- **Deploy:** Cloud Run on GCP (`apex-internal-apps`)
- **CI/CD:** GitHub Actions

## Local Development

```bash
pip install -r requirements.txt
python main.py
# Visit http://localhost:8080
```

## Deploy

Push to `main` triggers auto-deploy via GitHub Actions to Cloud Run.

## Admin Credentials

- Email: `admin@agentplatform.ai`
- Password: `AgentPlatform2026!`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| POST | `/api/auth/signup` | Create account |
| POST | `/api/auth/login` | Login |
| GET | `/api/auth/me` | Current user |
| GET | `/api/agents` | List user's agents |
| POST | `/api/agents` | Create agent |
| GET | `/api/agents/{id}` | Get agent |
| PUT | `/api/agents/{id}` | Update agent |
| DELETE | `/api/agents/{id}` | Delete agent |
| GET | `/api/admin/users` | List all users (admin) |
| GET | `/api/admin/agents` | List all agents (admin) |
| GET | `/api/admin/stats` | Platform stats (admin) |
| PUT | `/api/admin/agents/{id}/suspend` | Suspend agent (admin) |
| PUT | `/api/admin/agents/{id}/activate` | Activate agent (admin) |
