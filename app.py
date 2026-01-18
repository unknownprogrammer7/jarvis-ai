import os, json
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from pypdf import PdfReader
import uvicorn

# =========================
# ENV
# =========================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this")

CHAT_FILE = "chat_history.json"

# =========================
# APP
# =========================
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# =========================
# GOOGLE OAUTH
# =========================
oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# =========================
# HELPERS
# =========================
def load_chats():
    if not os.path.exists(CHAT_FILE):
        return {}
    with open(CHAT_FILE, "r") as f:
        return json.load(f)

def save_chats(data):
    with open(CHAT_FILE, "w") as f:
        json.dump(data, f, indent=2)

def read_file(file: UploadFile):
    if file.filename.endswith(".pdf"):
        reader = PdfReader(file.file)
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    if file.filename.endswith(".txt"):
        return file.file.read().decode("utf-8")
    return "Unsupported file"

# =========================
# ROUTES
# =========================

@app.get("/")
async def home(request: Request):
    user = request.session.get("user")
    if not user:
        return HTMLResponse("""
        <h2>Dexora AI</h2>
        <a href="/login">Login with Google</a>
        """)

    chats = load_chats().get(user["email"], [])

    chat_html = "".join(
        f"<p><b>You:</b> {c['user']}<br><b>AI:</b> {c['bot']}</p>"
        for c in chats
    )

    return HTMLResponse(f"""
    <html>
    <head>
      <link rel="manifest" href="/static/manifest.json">
    </head>
    <body>
    <h3>Welcome {user['email']}</h3>

    {chat_html}

    <form method="post" action="/chat">
      <input name="message" required>
      <button type="submit">Send</button>
    </form>

    <form method="post" action="/upload" enctype="multipart/form-data">
      <input type="file" name="file">
      <button type="submit">Upload File</button>
    </form>

    <a href="/logout">Logout</a>
    </body>
    </html>
    """)

@app.post("/chat")
async def chat(request: Request, message: str = Form(...)):
    user = request.session["user"]
    chats = load_chats()

    chats.setdefault(user["email"], [])
    chats[user["email"]].append({
        "user": message,
        "bot": "This is where AI reply will go"
    })

    save_chats(chats)
    return RedirectResponse("/", status_code=302)

@app.post("/upload")
async def upload(request: Request, file: UploadFile = File(...)):
    user = request.session["user"]
    text = read_file(file)

    chats = load_chats()
    chats.setdefault(user["email"], [])
    chats[user["email"]].append({
        "user": f"Uploaded file: {file.filename}",
        "bot": text[:500]
    })

    save_chats(chats)
    return RedirectResponse("/", status_code=302)

@app.get("/login")
async def login(request: Request):
    return await oauth.google.authorize_redirect(
        request,
        request.url_for("auth")
    )

@app.get("/auth")
async def auth(request: Request):
    token = await oauth.google.authorize_access_token(request)
    request.session["user"] = token["userinfo"]
    return RedirectResponse("/")

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")

# =========================
# START
# =========================
if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
