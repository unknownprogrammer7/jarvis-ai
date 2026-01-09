import os, json
from datetime import datetime

import gradio as gr
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from requests_oauthlib import OAuth2Session
from openai import OpenAI
from pypdf import PdfReader
import docx2txt

# =========================================================
# ENVIRONMENT VARIABLES (SET IN RENDER)
# =========================================================
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REDIRECT_URI = os.getenv("REDIRECT_URI")

client = OpenAI(api_key=OPENAI_API_KEY)

USER_FILE = "users.json"
MEMORY_FILE = "memory.json"

# =========================================================
# INIT STORAGE FILES
# =========================================================
for f in [USER_FILE, MEMORY_FILE]:
    if not os.path.exists(f):
        with open(f, "w") as fp:
            json.dump({}, fp)

# =========================================================
# HELPERS
# =========================================================
def load_json(file):
    with open(file, "r") as f:
        return json.load(f)

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

def ethics_guard(text):
    banned = ["kill", "bomb", "terrorist", "hack", "rape", "weapon", "suicide"]
    for w in banned:
        if w in text.lower():
            return False, "⚠️ I can’t help with harmful or illegal requests."
    return True, ""

def update_memory(user, text):
    memory = load_json(MEMORY_FILE)
    memory.setdefault(user, {})

    t = text.lower()
    if "my name is" in t:
        memory[user]["name"] = text.split("is")[-1].strip()
    if "i am from" in t:
        memory[user]["location"] = text.split("from")[-1].strip()

    save_json(MEMORY_FILE, memory)
    return memory[user]

def extract_text(file):
    if not file:
        return ""
    if file.name.endswith(".pdf"):
        reader = PdfReader(file.name)
        return "\n".join(p.extract_text() for p in reader.pages if p.extract_text())
    if file.name.endswith(".docx"):
        return docx2txt.process(file.name)
    if file.name.endswith(".txt"):
        return file.read().decode("utf-8")
    return ""

# =========================================================
# FASTAPI + GOOGLE LOGIN
# =========================================================
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="dexora-session-key")

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
USERINFO_URI = "https://www.googleapis.com/oauth2/v1/userinfo"

@app.get("/")
async def root(request: Request):
    if "user" in request.session:
        return RedirectResponse("/chat")
    return RedirectResponse("/login")

@app.get("/login")
async def login():
    oauth = OAuth2Session(
        GOOGLE_CLIENT_ID,
        redirect_uri=REDIRECT_URI,
        scope=["openid", "email", "profile"]
    )
    auth_url, _ = oauth.authorization_url(AUTH_URI)
    return RedirectResponse(auth_url)

@app.get("/auth/google/callback")
async def callback(request: Request):
    oauth = OAuth2Session(GOOGLE_CLIENT_ID, redirect_uri=REDIRECT_URI)
    oauth.fetch_token(
        TOKEN_URI,
        client_secret=GOOGLE_CLIENT_SECRET,
        authorization_response=str(request.url)
    )
    user = oauth.get(USERINFO_URI).json()
    request.session["user"] = user
    return RedirectResponse("/chat")

# =========================================================
# CHAT LOGIC
# =========================================================
def chat(message, history, username, file):
    if history is None:
        history = []

    allowed, warning = ethics_guard(message)
    if not allowed:
        history.append((message, warning))
        return history, ""

    memory = update_memory(username, message)

    if file:
        message += "\n\n" + extract_text(file)

    if "what is my name" in message.lower() and "name" in memory:
        reply = f"Your name is {memory['name']}."
    else:
        msgs = [{"role": "system", "content": "You are Dexora, an intelligent AI assistant."}]
        for u, a in history:
            msgs.append({"role": "user", "content": u})
            msgs.append({"role": "assistant", "content": a})
        msgs.append({"role": "user", "content": message})

        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msgs
        )
        reply = res.choices[0].message.content

    history.append((message, reply))
    return history, ""

# =========================================================
# CHATGPT-LIKE CSS
# =========================================================
custom_css = """
body {
    background-color: #0f0f0f;
}

.gradio-container {
    max-width: 900px;
    margin: auto;
}

#chatbot {
    background-color: #0f0f0f;
}

.message.user {
    background: #1f2937;
    border-radius: 14px;
    padding: 12px;
}

.message.bot {
    background: #111827;
    border-radius: 14px;
    padding: 12px;
}

textarea {
    background-color: #111827 !important;
    color: white !important;
    border-radius: 12px !important;
}

button {
    background: #10a37f !important;
    color: white !important;
    border-radius: 12px !important;
    font-weight: bold;
}

input[type="file"] {
    color: white;
}
"""

# =========================================================
# GRADIO UI (CHATGPT STYLE)
# =========================================================
with gr.Blocks(css=custom_css) as chat_ui:
    gr.Markdown("## 🤖 Dexora")

    chatbot = gr.Chatbot(elem_id="chatbot", height=480)
    username = gr.State("User")

    with gr.Row():
        msg = gr.Textbox(
            placeholder="Send a message...",
            show_label=False,
            scale=4
        )
        upload = gr.File(
            file_types=[".pdf", ".txt", ".docx"],
            label="📎",
            scale=1
        )
        send = gr.Button("➤", scale=1)

    send.click(chat, [msg, chatbot, username, upload], [chatbot, msg])
    msg.submit(chat, [msg, chatbot, username, upload], [chatbot, msg])

# =========================================================
# MOUNT GRADIO
# =========================================================
app = gr.mount_gradio_app(app, chat_ui, path="/chat")
