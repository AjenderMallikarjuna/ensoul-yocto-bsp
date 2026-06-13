"""
Lightweight HTTP API + web chat UI for the Anime.AI companion daemon.

Endpoints:
  GET  /                — web chat UI (browser)
  GET  /health          — liveness + uptime + current emotion JSON
  GET  /status          — current state (idle / recording / processing / speaking)
  GET  /chat/history    — full conversation history with emotion annotations
  POST /chat            — body: {"message": "..."} — text chat, returns reply + emotion
  POST /listen          — start one full mic → response turn (async, 202)
  POST /say             — body: {"text": "..."} — skip STT (dev mode, async, 202)
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

log = logging.getLogger("companion.api")

_DEFAULT_PORT = 8080

# ---------------------------------------------------------------------------
# Inline chat UI — dark anime aesthetic, zero external dependencies
# ---------------------------------------------------------------------------
_CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aria — Anime.AI Companion</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0d0f1a;
    color: #e8e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    height: 100dvh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-bottom: 1px solid #2a2a4a;
    padding: 12px 20px;
    display: flex;
    align-items: center;
    gap: 14px;
    flex-shrink: 0;
  }
  .avatar {
    width: 44px; height: 44px;
    border-radius: 50%;
    background: linear-gradient(135deg, #7c3aed, #db2777);
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
    box-shadow: 0 0 16px rgba(124,58,237,0.5);
    flex-shrink: 0;
  }
  .header-info { flex: 1; }
  .header-info h1 { font-size: 1.1rem; font-weight: 700; letter-spacing: 0.03em; }
  .header-info .subtitle { font-size: 0.75rem; color: #8888aa; margin-top: 1px; }
  #emotion-badge {
    display: flex; align-items: center; gap: 7px;
    background: #1e1e3f;
    border: 1px solid #3a3a6a;
    border-radius: 20px;
    padding: 5px 12px;
    font-size: 0.78rem;
    transition: all 0.4s ease;
  }
  #emotion-badge .dot {
    width: 9px; height: 9px; border-radius: 50%;
    background: #818cf8;
    transition: background 0.4s ease, box-shadow 0.4s ease;
    box-shadow: 0 0 6px #818cf8;
  }
  #emotion-label { font-weight: 600; text-transform: capitalize; }
  #emotion-badge[data-emotion="joy"]       .dot { background:#fbbf24; box-shadow:0 0 8px #fbbf24; }
  #emotion-badge[data-emotion="excited"]   .dot { background:#f43f5e; box-shadow:0 0 8px #f43f5e; }
  #emotion-badge[data-emotion="playful"]   .dot { background:#a78bfa; box-shadow:0 0 8px #a78bfa; }
  #emotion-badge[data-emotion="curiosity"] .dot { background:#38bdf8; box-shadow:0 0 8px #38bdf8; }
  #emotion-badge[data-emotion="empathy"]   .dot { background:#34d399; box-shadow:0 0 8px #34d399; }
  #emotion-badge[data-emotion="calm"]      .dot { background:#818cf8; box-shadow:0 0 8px #818cf8; }
  #emotion-badge[data-emotion="concerned"] .dot { background:#fb923c; box-shadow:0 0 8px #fb923c; }
  #messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    scroll-behavior: smooth;
  }
  #messages::-webkit-scrollbar { width: 4px; }
  #messages::-webkit-scrollbar-thumb { background: #2a2a4a; border-radius: 2px; }
  .msg { display: flex; flex-direction: column; max-width: 78%; }
  .msg.user { align-self: flex-end; align-items: flex-end; }
  .msg.aria  { align-self: flex-start; align-items: flex-start; }
  .bubble {
    padding: 10px 15px;
    border-radius: 18px;
    line-height: 1.5;
    font-size: 0.92rem;
    word-break: break-word;
  }
  .msg.user .bubble {
    background: linear-gradient(135deg, #6d28d9, #7c3aed);
    color: #fff;
    border-bottom-right-radius: 4px;
    box-shadow: 0 2px 12px rgba(109,40,217,0.4);
  }
  .msg.aria .bubble {
    background: #1e1e38;
    border: 1px solid #2a2a4a;
    border-bottom-left-radius: 4px;
  }
  .msg-meta { font-size: 0.68rem; color: #555577; margin-top: 4px; padding: 0 4px; }
  .msg.aria .msg-meta { display: flex; align-items: center; gap: 6px; }
  .emo-pill {
    font-size: 0.65rem;
    background: #1a1a30;
    border: 1px solid #2a2a4a;
    border-radius: 10px;
    padding: 1px 7px;
    text-transform: capitalize;
    color: #8888cc;
  }
  #typing {
    display: none;
    align-self: flex-start;
    background: #1e1e38;
    border: 1px solid #2a2a4a;
    border-radius: 18px;
    border-bottom-left-radius: 4px;
    padding: 10px 16px;
    margin: 0 16px;
  }
  #typing span {
    display: inline-block;
    width: 7px; height: 7px;
    background: #7c3aed;
    border-radius: 50%;
    animation: bounce 1.2s infinite;
    margin: 0 2px;
  }
  #typing span:nth-child(2) { animation-delay: 0.2s; }
  #typing span:nth-child(3) { animation-delay: 0.4s; }
  @keyframes bounce {
    0%,60%,100% { transform: translateY(0); }
    30% { transform: translateY(-6px); }
  }
  footer {
    background: #12121f;
    border-top: 1px solid #1e1e35;
    padding: 14px 16px;
    display: flex;
    gap: 10px;
    align-items: flex-end;
    flex-shrink: 0;
  }
  #input {
    flex: 1;
    background: #1a1a30;
    border: 1px solid #2e2e50;
    border-radius: 22px;
    padding: 10px 18px;
    color: #e8e8f0;
    font-size: 0.92rem;
    resize: none;
    max-height: 120px;
    min-height: 44px;
    line-height: 1.4;
    outline: none;
    transition: border-color 0.2s;
    font-family: inherit;
  }
  #input:focus { border-color: #6d28d9; }
  #input::placeholder { color: #444466; }
  #send-btn {
    background: linear-gradient(135deg, #6d28d9, #7c3aed);
    color: #fff;
    border: none;
    border-radius: 50%;
    width: 44px; height: 44px;
    cursor: pointer;
    font-size: 18px;
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: opacity 0.2s, transform 0.1s;
    box-shadow: 0 2px 12px rgba(109,40,217,0.5);
  }
  #send-btn:hover { opacity: 0.85; }
  #send-btn:active { transform: scale(0.93); }
  #send-btn:disabled { opacity: 0.4; cursor: default; }
</style>
</head>
<body>
<header>
  <div class="avatar">✦</div>
  <div class="header-info">
    <h1>Aria</h1>
    <div class="subtitle">Anime.AI Desk Companion</div>
  </div>
  <div id="emotion-badge" data-emotion="calm">
    <div class="dot"></div>
    <span id="emotion-label">calm</span>
  </div>
</header>

<div id="messages">
  <div class="msg aria">
    <div class="bubble">Hi! I&#39;m Aria, your desk companion. What&#39;s on your mind? ✨</div>
    <div class="msg-meta">Aria</div>
  </div>
</div>
<div id="typing"><span></span><span></span><span></span></div>

<footer>
  <textarea id="input" rows="1" placeholder="Talk to Aria…"></textarea>
  <button id="send-btn" title="Send">&#10148;</button>
</footer>

<script>
const messagesEl = document.getElementById('messages');
const inputEl    = document.getElementById('input');
const sendBtn    = document.getElementById('send-btn');
const typingEl   = document.getElementById('typing');
const emoBadge   = document.getElementById('emotion-badge');
const emoLabel   = document.getElementById('emotion-label');

function ts() {
  return new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
}

function appendMessage(role, text, emoLbl, emoInt) {
  const wrap   = document.createElement('div');
  wrap.className = 'msg ' + role;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = text;
  const meta = document.createElement('div');
  meta.className = 'msg-meta';
  meta.textContent = (role === 'aria' ? 'Aria' : 'You') + ' · ' + ts();
  if (role === 'aria' && emoLbl) {
    const pill = document.createElement('span');
    pill.className = 'emo-pill';
    pill.textContent = emoLbl + ' ' + Math.round(emoInt * 100) + '%';
    meta.appendChild(pill);
  }
  wrap.appendChild(bubble);
  wrap.appendChild(meta);
  messagesEl.appendChild(wrap);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function setEmotion(label) {
  emoBadge.setAttribute('data-emotion', label);
  emoLabel.textContent = label;
}

function setLoading(on) {
  sendBtn.disabled = on;
  inputEl.disabled = on;
  typingEl.style.display = on ? 'flex' : 'none';
  if (on) messagesEl.scrollTop = messagesEl.scrollHeight;
}

async function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = '';
  inputEl.style.height = 'auto';
  appendMessage('user', text);
  setLoading(true);
  try {
    const res  = await fetch('/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text}),
    });
    const data = await res.json();
    setLoading(false);
    if (res.ok) {
      appendMessage('aria', data.reply, data.emotion.label, data.emotion.intensity);
      setEmotion(data.emotion.label);
    } else {
      appendMessage('aria', '⚠ ' + (data.error || 'Something went wrong.'), 'concerned', 0.7);
    }
  } catch {
    setLoading(false);
    appendMessage('aria', '⚠ Could not reach Aria. Is the device online?', 'concerned', 0.8);
  }
}

sendBtn.addEventListener('click', sendMessage);
inputEl.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
inputEl.addEventListener('input', () => {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
});
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# History helper
# ---------------------------------------------------------------------------

def _build_history(session) -> list[dict]:
    result = []
    for msg in session._history:
        entry = {"role": msg["role"], "content": msg["content"]}
        if msg["role"] == "assistant":
            entry["emotion"] = {
                "label": msg.get("_emo_label", "calm"),
                "intensity": msg.get("_emo_intensity", 0.5),
            }
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    daemon_ref = None  # set by start()

    def log_message(self, fmt, *args):
        log.debug(fmt, *args)

    def _send_json(self, code: int, body: dict) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_html(self, code: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/":
            self._send_html(200, _CHAT_HTML)
        elif self.path == "/health":
            self._send_json(200, self.daemon_ref.health())
        elif self.path == "/status":
            self._send_json(200, {"state": self.daemon_ref.state})
        elif self.path == "/chat/history":
            d = self.daemon_ref
            emotion_label, emotion_intensity = d.session.current_emotion
            self._send_json(200, {
                "history": _build_history(d.session),
                "current_emotion": {"label": emotion_label, "intensity": emotion_intensity},
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        d = self.daemon_ref

        if self.path == "/chat":
            body = self._read_json()
            message = body.get("message", "").strip()
            if not message:
                self._send_json(400, {"error": "message field required"})
                return
            # Serialize LLM calls with the daemon lock so voice pipeline turns
            # and web chat turns don't interleave inside ChatSession.
            with d._lock:
                reply, label, intensity = d.session.send(message)
            threading.Thread(
                target=d.on_emotion_change,
                args=(label, intensity),
                daemon=True,
                name="emotion-actuator",
            ).start()
            self._send_json(200, {
                "reply": reply,
                "emotion": {"label": label, "intensity": intensity},
                "history": _build_history(d.session),
            })

        elif self.path == "/listen":
            if d.state != "idle":
                self._send_json(409, {"error": "busy", "state": d.state})
                return
            threading.Thread(target=d.handle_conversation, daemon=True).start()
            self._send_json(202, {"status": "started"})

        elif self.path == "/say":
            if d.state != "idle":
                self._send_json(409, {"error": "busy", "state": d.state})
                return
            body = self._read_json()
            text = body.get("text", "").strip()
            if not text:
                self._send_json(400, {"error": "text field required"})
                return
            threading.Thread(target=d.handle_text_input, args=(text,), daemon=True).start()
            self._send_json(202, {"status": "started", "text": text})

        else:
            self._send_json(404, {"error": "not found"})


def start(daemon, host: str = "0.0.0.0", port: int = _DEFAULT_PORT) -> None:
    _Handler.daemon_ref = daemon
    server = HTTPServer((host, port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="api-server")
    t.start()
    log.info("API server listening on %s:%d", host, port)
