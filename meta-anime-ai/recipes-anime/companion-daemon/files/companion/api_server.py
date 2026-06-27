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
  POST /stt             — body: raw 16-bit PCM WAV — returns {"text": "..."}
"""
import json
import logging
import os
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from companion import tts as _tts

log = logging.getLogger("companion.api")

_DEFAULT_PORT = 8080

# Candidate model directories, checked in order at runtime.
_STT_MODEL_DIRS = [
    "/opt/ensoul/models/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
    "/tmp/stt/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
]


def _find_stt_model() -> str | None:
    for d in _STT_MODEL_DIRS:
        enc = os.path.join(d, "encoder-epoch-99-avg-1.int8.onnx")
        if os.path.isfile(enc):
            return d
    return None


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

  /* ── Voice panel ───────────────────────────────────────────────────── */
  #voice-panel {
    background: #0f0f20;
    border-top: 1px solid #1e1e35;
    padding: 10px 16px;
    flex-shrink: 0;
  }
  #voice-controls {
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .voice-btn {
    border: none;
    border-radius: 22px;
    padding: 8px 18px;
    font-size: 0.82rem;
    font-weight: 600;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 7px;
    transition: opacity 0.2s, transform 0.1s;
    flex-shrink: 0;
  }
  .voice-btn:active { transform: scale(0.95); }
  .voice-btn:disabled { opacity: 0.35; cursor: default; }
  #record-btn {
    background: linear-gradient(135deg, #be123c, #e11d48);
    color: #fff;
    box-shadow: 0 2px 10px rgba(225,29,72,0.35);
  }
  #record-btn.recording {
    background: linear-gradient(135deg, #9f1239, #be123c);
    box-shadow: 0 0 0 0 rgba(225,29,72,0.6);
    animation: pulse-ring 1.2s ease-out infinite;
  }
  @keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0   rgba(225,29,72,0.6); }
    70%  { box-shadow: 0 0 0 10px rgba(225,29,72,0);   }
    100% { box-shadow: 0 0 0 0   rgba(225,29,72,0);   }
  }
  #listen-btn {
    background: #1e1e38;
    border: 1px solid #3a3a5a;
    color: #a0a0c8;
  }
  #listen-btn:not(:disabled):hover { background: #26263a; color: #c0c0e0; }
  #voice-status {
    font-size: 0.75rem;
    color: #555577;
    flex: 1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  #voice-status.active { color: #f43f5e; }
  #voice-status.processing { color: #a78bfa; }
  #voice-status.done { color: #34d399; }

  #stt-box {
    display: none;
    margin-top: 8px;
    background: #111128;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 0.88rem;
    line-height: 1.5;
    color: #c8c8e8;
    position: relative;
  }
  #stt-label {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #555577;
    margin-bottom: 4px;
  }
  #stt-text { min-height: 1.4em; }
  #use-in-chat {
    position: absolute;
    top: 8px; right: 10px;
    background: #6d28d9;
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: 3px 10px;
    font-size: 0.72rem;
    font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s;
  }
  #use-in-chat:hover { opacity: 0.8; }

  /* ── Text footer ───────────────────────────────────────────────────── */
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
  <button id="mute-btn" title="Toggle Aria voice" style="
    background:none; border:1px solid #2a2a4a; border-radius:50%;
    width:36px; height:36px; cursor:pointer; font-size:16px;
    color:#8888aa; flex-shrink:0; transition:all 0.2s;
  ">🔊</button>
</header>

<div id="messages">
  <div class="msg aria">
    <div class="bubble">Hi! I&#39;m Aria, your desk companion. What&#39;s on your mind? ✨</div>
    <div class="msg-meta">Aria</div>
  </div>
</div>
<div id="typing"><span></span><span></span><span></span></div>

<!-- Voice testing panel -->
<div id="voice-panel">
  <div id="voice-controls">
    <button class="voice-btn" id="record-btn" title="Record from mic">🎤 Record</button>
    <button class="voice-btn" id="listen-btn" disabled title="Play back recording">🔊 Listen</button>
    <span id="voice-status">Ready — click Record to start</span>
  </div>
  <div id="stt-box">
    <div id="stt-label">STT Transcript</div>
    <div id="stt-text"></div>
    <button id="use-in-chat">Use in chat ↑</button>
  </div>
</div>

<footer>
  <textarea id="input" rows="1" placeholder="Talk to Aria…"></textarea>
  <button id="send-btn" title="Send">&#10148;</button>
</footer>

<script>
// ── Chat UI ────────────────────────────────────────────────────────────────
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
      playTTS(data.reply);
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

// ── TTS auto-play ──────────────────────────────────────────────────────────
let isMuted = false;
const muteBtn = document.getElementById('mute-btn');

muteBtn.addEventListener('click', () => {
  isMuted = !isMuted;
  muteBtn.textContent = isMuted ? '🔇' : '🔊';
  muteBtn.style.color  = isMuted ? '#6d28d9' : '#8888aa';
});

async function playTTS(text) {
  if (isMuted) return;
  try {
    const res = await fetch('/tts', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text}),
    });
    if (!res.ok) return;
    const blob  = await res.blob();
    const url   = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => URL.revokeObjectURL(url);
    audio.play();
  } catch {
    // TTS playback failure is non-fatal — Aria stays silent
  }
}

// ── Voice / STT panel ──────────────────────────────────────────────────────
const recordBtn   = document.getElementById('record-btn');
const listenBtn   = document.getElementById('listen-btn');
const voiceStatus = document.getElementById('voice-status');
const sttBox      = document.getElementById('stt-box');
const sttText     = document.getElementById('stt-text');
const useInChat   = document.getElementById('use-in-chat');

let audioCtx      = null;
let mediaStream   = null;
let processor     = null;
let recordedChunks = [];   // Float32Array[]
let recordingBlob  = null; // WAV Blob for Listen playback
let isRecording    = false;

function setVoiceStatus(msg, cls) {
  voiceStatus.textContent = msg;
  voiceStatus.className   = cls || '';
}

// Encode Float32 PCM chunks → WAV ArrayBuffer (16-bit mono, 16 kHz)
function encodeWAV(chunks, sampleRate) {
  let total = 0;
  for (const c of chunks) total += c.length;
  const pcm = new Float32Array(total);
  let off = 0;
  for (const c of chunks) { pcm.set(c, off); off += c.length; }

  const buf  = new ArrayBuffer(44 + pcm.length * 2);
  const view = new DataView(buf);
  function str(o, s) { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); }

  str(0,  'RIFF');
  view.setUint32(4,  36 + pcm.length * 2, true);
  str(8,  'WAVE');
  str(12, 'fmt ');
  view.setUint32(16, 16,            true);   // chunk size
  view.setUint16(20, 1,             true);   // PCM
  view.setUint16(22, 1,             true);   // mono
  view.setUint32(24, sampleRate,    true);
  view.setUint32(28, sampleRate * 2, true);  // byte rate
  view.setUint16(32, 2,             true);   // block align
  view.setUint16(34, 16,            true);   // bits per sample
  str(36, 'data');
  view.setUint32(40, pcm.length * 2, true);

  let p = 44;
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    view.setInt16(p, s * 0x7FFF, true);
    p += 2;
  }
  return buf;
}

async function startRecording() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
  } catch (e) {
    setVoiceStatus('Mic access denied — allow mic in browser', '');
    return;
  }

  audioCtx = new AudioContext({ sampleRate: 16000 });
  const source = audioCtx.createMediaStreamSource(mediaStream);
  processor = audioCtx.createScriptProcessor(2048, 1, 1);
  recordedChunks = [];

  processor.onaudioprocess = (e) => {
    if (isRecording) recordedChunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  };

  source.connect(processor);
  processor.connect(audioCtx.destination);

  isRecording = true;
  recordBtn.textContent = '⏹ Stop';
  recordBtn.classList.add('recording');
  listenBtn.disabled = true;
  sttBox.style.display = 'none';
  setVoiceStatus('Recording… speak now', 'active');
}

async function stopRecording() {
  isRecording = false;
  processor.disconnect();
  mediaStream.getTracks().forEach(t => t.stop());
  audioCtx.close();

  recordBtn.textContent = '🎤 Record';
  recordBtn.classList.remove('recording');

  if (recordedChunks.length === 0) {
    setVoiceStatus('Nothing recorded', '');
    return;
  }

  setVoiceStatus('Processing… running STT on device', 'processing');
  recordBtn.disabled = true;
  listenBtn.disabled = true;

  const wavBuf = encodeWAV(recordedChunks, 16000);
  recordingBlob = new Blob([wavBuf], { type: 'audio/wav' });

  // Enable Listen playback
  listenBtn.disabled = false;

  // Send WAV to /stt endpoint on the device
  try {
    const res  = await fetch('/stt', {
      method: 'POST',
      headers: { 'Content-Type': 'audio/wav' },
      body: wavBuf,
    });
    const data = await res.json();

    if (res.ok && data.text) {
      sttText.textContent = data.text;
      sttBox.style.display = 'block';
      setVoiceStatus('Done — transcript below', 'done');
    } else if (res.status === 503) {
      sttText.textContent = data.error || 'STT model not found on device.';
      sttBox.style.display = 'block';
      setVoiceStatus('Model missing — run fetch-stt-model.sh inside QEMU', '');
    } else {
      setVoiceStatus('STT error: ' + (data.error || res.status), '');
    }
  } catch (e) {
    setVoiceStatus('Network error — is device reachable?', '');
  }

  recordBtn.disabled = false;
}

recordBtn.addEventListener('click', () => {
  if (isRecording) stopRecording();
  else startRecording();
});

listenBtn.addEventListener('click', () => {
  if (!recordingBlob) return;
  const url   = URL.createObjectURL(recordingBlob);
  const audio = new Audio(url);
  audio.onended = () => URL.revokeObjectURL(url);
  audio.play();
});

useInChat.addEventListener('click', () => {
  const t = sttText.textContent.trim();
  if (!t) return;
  inputEl.value = t;
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + 'px';
  inputEl.focus();
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

        elif self.path == "/stt":
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._send_json(400, {"error": "no audio data"})
                return

            audio_data = self.rfile.read(length)

            model_dir = _find_stt_model()
            if not model_dir:
                self._send_json(503, {
                    "error": "STT model not found. Run /usr/share/ensoul/fetch-stt-model.sh inside the device."
                })
                return

            tmp = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    f.write(audio_data)
                    tmp = f.name

                result = subprocess.run(
                    [
                        "sherpa-onnx",
                        f"--encoder={model_dir}/encoder-epoch-99-avg-1.int8.onnx",
                        f"--decoder={model_dir}/decoder-epoch-99-avg-1.int8.onnx",
                        f"--joiner={model_dir}/joiner-epoch-99-avg-1.int8.onnx",
                        f"--tokens={model_dir}/tokens.txt",
                        "--num-threads=2",
                        tmp,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )

                transcript = ""
                for line in result.stderr.splitlines():
                    if '"text"' in line:
                        try:
                            obj = json.loads(line.strip())
                            t = obj.get("text", "").strip()
                            if t:
                                transcript = t
                        except json.JSONDecodeError:
                            pass

                self._send_json(200, {"text": transcript})

            except subprocess.TimeoutExpired:
                self._send_json(504, {"error": "STT inference timed out"})
            except Exception as e:
                log.exception("STT error")
                self._send_json(500, {"error": str(e)})
            finally:
                if tmp and os.path.exists(tmp):
                    os.unlink(tmp)

        elif self.path == "/tts":
            body = self._read_json()
            text = body.get("text", "").strip()
            if not text:
                self._send_json(400, {"error": "text field required"})
                return
            try:
                cfg = self.daemon_ref.cfg
                wav_path = _tts.synthesize(text, cfg.api.tts_provider, cfg.openai_api_key)
                wav_data = wav_path.read_bytes()
                wav_path.unlink(missing_ok=True)
                self.send_response(200)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(wav_data)))
                self.end_headers()
                self.wfile.write(wav_data)
            except Exception as e:
                log.exception("TTS error")
                self._send_json(500, {"error": str(e)})

        else:
            self._send_json(404, {"error": "not found"})


def start(daemon, host: str = "0.0.0.0", port: int = _DEFAULT_PORT) -> None:
    _Handler.daemon_ref = daemon
    server = HTTPServer((host, port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True, name="api-server")
    t.start()
    log.info("API server listening on %s:%d", host, port)
