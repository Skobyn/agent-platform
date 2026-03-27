"""Agent Platform - Multi-tenant AI Agent Deployment Platform."""
import os
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Request, Response, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from google.cloud import firestore

# --- Config ---
SECRET_KEY = os.environ.get("JWT_SECRET", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@agentplatform.ai")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "AgentPlatform2026!")
GCP_PROJECT = os.environ.get("GCP_PROJECT", "apex-internal-apps")

# --- App ---
app = FastAPI(title="Agent Platform", version="1.0.0")
app.mount("/static", StaticFiles(directory="static"), name="static")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Firestore client - lazy init
class FirestoreProxy:
    def __init__(self):
        self._client = None
        self._initialized = False
    
    def _ensure_init(self):
        if not self._initialized:
            try:
                self._client = firestore.Client(project=GCP_PROJECT)
                self._initialized = True
                print(f"Firestore connected to project {GCP_PROJECT}")
            except Exception as e:
                print(f"Firestore init warning: {e}")
                self._client = None
                self._initialized = True
    
    def collection(self, *args, **kwargs):
        self._ensure_init()
        if self._client is None:
            return None
        return self._client.collection(*args, **kwargs)
    
    @property
    def available(self):
        self._ensure_init()
        return self._client is not None

    def __bool__(self):
        self._ensure_init()
        return self._client is not None

db = FirestoreProxy()

# --- Models ---
class UserCreate(BaseModel):
    email: str
    password: str
    name: str = ""

class UserLogin(BaseModel):
    email: str
    password: str

class AgentCreate(BaseModel):
    name: str
    system_prompt: str = ""
    model: str = "gpt-4"
    capabilities: str = ""

class AgentUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    capabilities: Optional[str] = None
    status: Optional[str] = None

# --- Auth Helpers ---
def create_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None

def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")
    return payload

def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

# --- Firestore Helpers ---
def get_user_by_email(email: str):
    if not db:
        return None
    coll = db.collection("platform_users")
    if coll is None:
        return None
    users = coll.where("email", "==", email).limit(1).stream()
    for u in users:
        data = u.to_dict()
        data["id"] = u.id
        return data
    return None

def ensure_admin():
    """Create default admin user if not exists."""
    try:
        if not db:
            print("Firestore not available, skipping admin creation")
            return
        existing = get_user_by_email(ADMIN_EMAIL)
        if not existing:
            admin_id = str(uuid.uuid4())
            db.collection("platform_users").document(admin_id).set({
                "email": ADMIN_EMAIL,
                "password_hash": pwd_context.hash(ADMIN_PASSWORD),
                "name": "Platform Admin",
                "role": "admin",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "active"
            })
            print(f"Admin user created: {ADMIN_EMAIL}")
    except Exception as e:
        print(f"Admin creation warning: {e}")

@app.on_event("startup")
async def startup():
    ensure_admin()

# --- HTML Page Serving ---
def read_template(name: str) -> str:
    with open(f"templates/{name}", "r") as f:
        return f.read()

# --- Landing Page ---
@app.get("/", response_class=HTMLResponse)
async def landing_page():
    return read_template("landing.html")

# --- Auth Pages ---
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return read_template("login.html")

@app.get("/signup", response_class=HTMLResponse)
async def signup_page():
    return read_template("signup.html")

# --- Dashboard Pages ---
@app.get("/dashboard", response_class=HTMLResponse)
async def user_dashboard():
    return read_template("dashboard.html")

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard():
    return read_template("admin.html")

# --- API: Health ---
@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "agent-platform", "version": "1.0.0"}

# --- API: Auth ---
@app.post("/api/auth/signup")
async def api_signup(user: UserCreate):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    existing = get_user_by_email(user.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    db.collection("platform_users").document(user_id).set({
        "email": user.email,
        "password_hash": pwd_context.hash(user.password),
        "name": user.name or user.email.split("@")[0],
        "role": "user",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "active"
    })
    
    token = create_token({"sub": user_id, "email": user.email, "role": "user", "name": user.name})
    return {"access_token": token, "token_type": "bearer", "user_id": user_id}

@app.post("/api/auth/login")
async def api_login(user: UserLogin):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    existing = get_user_by_email(user.email)
    if not existing or not pwd_context.verify(user.password, existing.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_token({
        "sub": existing["id"],
        "email": existing["email"],
        "role": existing.get("role", "user"),
        "name": existing.get("name", "")
    })
    return {"access_token": token, "token_type": "bearer", "user_id": existing["id"]}

@app.get("/api/auth/me")
async def api_me(user=Depends(get_current_user)):
    return {"user_id": user["sub"], "email": user["email"], "role": user["role"], "name": user.get("name", "")}

# --- API: Agents (User) ---
@app.get("/api/agents")
async def list_agents(user=Depends(get_current_user)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    query = db.collection("platform_agents").where("owner_id", "==", user["sub"])
    agents = []
    for doc in query.stream():
        agent = doc.to_dict()
        agent["id"] = doc.id
        agents.append(agent)
    return {"agents": agents}

@app.post("/api/agents")
async def create_agent(agent: AgentCreate, user=Depends(get_current_user)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    agent_id = str(uuid.uuid4())
    agent_data = {
        "name": agent.name,
        "system_prompt": agent.system_prompt,
        "model": agent.model,
        "capabilities": agent.capabilities,
        "status": "active",
        "owner_id": user["sub"],
        "owner_email": user["email"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "activity_log": []
    }
    db.collection("platform_agents").document(agent_id).set(agent_data)
    agent_data["id"] = agent_id
    return agent_data

@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str, user=Depends(get_current_user)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    doc = db.collection("platform_agents").document(agent_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent = doc.to_dict()
    agent["id"] = doc.id
    
    # Users can only see their own agents, admins can see all
    if user["role"] != "admin" and agent.get("owner_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    return agent

@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, update: AgentUpdate, user=Depends(get_current_user)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    doc = db.collection("platform_agents").document(agent_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent = doc.to_dict()
    if user["role"] != "admin" and agent.get("owner_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    update_data = {k: v for k, v in update.dict().items() if v is not None}
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    db.collection("platform_agents").document(agent_id).update(update_data)
    agent.update(update_data)
    agent["id"] = agent_id
    return agent

@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str, user=Depends(get_current_user)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    doc = db.collection("platform_agents").document(agent_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    agent = doc.to_dict()
    if user["role"] != "admin" and agent.get("owner_id") != user["sub"]:
        raise HTTPException(status_code=403, detail="Access denied")
    
    db.collection("platform_agents").document(agent_id).delete()
    return {"status": "deleted", "agent_id": agent_id}

# --- API: Admin ---
@app.get("/api/admin/users")
async def admin_list_users(user=Depends(require_admin)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    users = []
    for doc in db.collection("platform_users").stream():
        u = doc.to_dict()
        u["id"] = doc.id
        u.pop("password_hash", None)
        users.append(u)
    return {"users": users}

@app.get("/api/admin/agents")
async def admin_list_all_agents(user=Depends(require_admin)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    agents = []
    for doc in db.collection("platform_agents").stream():
        agent = doc.to_dict()
        agent["id"] = doc.id
        agents.append(agent)
    return {"agents": agents}

@app.put("/api/admin/agents/{agent_id}/suspend")
async def admin_suspend_agent(agent_id: str, user=Depends(require_admin)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    doc = db.collection("platform_agents").document(agent_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    db.collection("platform_agents").document(agent_id).update({
        "status": "suspended",
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    return {"status": "suspended", "agent_id": agent_id}

@app.put("/api/admin/agents/{agent_id}/activate")
async def admin_activate_agent(agent_id: str, user=Depends(require_admin)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    doc = db.collection("platform_agents").document(agent_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    db.collection("platform_agents").document(agent_id).update({
        "status": "active",
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    return {"status": "active", "agent_id": agent_id}

@app.get("/api/admin/stats")
async def admin_stats(user=Depends(require_admin)):
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    users = list(db.collection("platform_users").stream())
    agents = list(db.collection("platform_agents").stream())
    
    active_agents = sum(1 for a in agents if a.to_dict().get("status") == "active")
    paused_agents = sum(1 for a in agents if a.to_dict().get("status") == "paused")
    suspended_agents = sum(1 for a in agents if a.to_dict().get("status") == "suspended")
    
    return {
        "total_users": len(users),
        "total_agents": len(agents),
        "active_agents": active_agents,
        "paused_agents": paused_agents,
        "suspended_agents": suspended_agents
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
