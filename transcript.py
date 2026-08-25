import json
import time
import uuid
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
KNOWLEDGE_DIR = DATA_DIR / "knowledge"


def ensure_dirs():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def create_session(mode: str, title: Optional[str] = None) -> dict:
    ensure_dirs()
    session_id = str(uuid.uuid4())[:8]
    session = {
        "id": session_id,
        "mode": mode,
        "title": title or f"{now_str()} のセッション",
        "created_at": time.time(),
        "updated_at": time.time(),
        "utterances": [],
        "minutes": "",
        "presentation": {"document": "", "script": "", "covered": []},
    }
    save_session(session)
    return session


def now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime())


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def load_session(session_id: str) -> Optional[dict]:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_session(session: dict):
    ensure_dirs()
    session["updated_at"] = time.time()
    path = session_path(session["id"])
    with path.open("w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def add_utterance(session_id: str, speaker: str, text: str) -> Optional[dict]:
    session = load_session(session_id)
    if not session:
        return None
    session["utterances"].append({
        "speaker": speaker,
        "text": text,
        "timestamp": time.time(),
    })
    save_session(session)
    return session


def set_minutes(session_id: str, minutes: str) -> Optional[dict]:
    session = load_session(session_id)
    if not session:
        return None
    session["minutes"] = minutes
    save_session(session)
    return session


def load_knowledge(mode: str) -> str:
    path = KNOWLEDGE_DIR / f"{mode}.txt"
    if not path.exists():
        return ""
    try:
        with path.open("r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def save_knowledge(mode: str, content: str):
    ensure_dirs()
    path = KNOWLEDGE_DIR / f"{mode}.txt"
    with path.open("w", encoding="utf-8") as f:
        f.write(content)


def list_sessions() -> list:
    ensure_dirs()
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            with path.open("r", encoding="utf-8") as f:
                s = json.load(f)
            sessions.append({
                "id": s.get("id"),
                "mode": s.get("mode"),
                "title": s.get("title"),
                "updated_at": s.get("updated_at"),
            })
        except Exception:
            continue
    return sessions


def format_transcript(session: dict) -> str:
    lines = []
    for u in session.get("utterances", []):
        t = time.strftime("%H:%M", time.localtime(u.get("timestamp", 0)))
        lines.append(f"[{t}] {u['speaker']}：{u['text']}")
    return "\n".join(lines)
