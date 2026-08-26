import asyncio
import base64
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.websockets import WebSocketState

import config as cfg
import speech as sp
import transcript as tr
from agents import AgentRunner
from modes import MODES, parse_presentation_document, parse_presentation_script, parse_presentation_script_per_slide

STATIC_DIR = Path(__file__).parent / "static"
SESSION_CONNECTIONS: Dict[str, List[WebSocket]] = {}
SESSION_BROADCASTS: Dict[str, asyncio.Transport] = {}
BROADCAST_PORT = 5000
BROADCAST_INTERVAL = 2


def get_lan_ip_candidates() -> List[str]:
    candidates = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            candidates.add(ip)
    except Exception:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                candidates.add(ip)
    except Exception:
        pass
    if not candidates:
        candidates.add("127.0.0.1")
    return list(candidates)


def broadcast_addresses_for_ip(ip: str) -> List[str]:
    parts = ip.split(".")
    if len(parts) != 4:
        return []
    return [f"{parts[0]}.{parts[1]}.{parts[2]}.255"]


class BroadcastProtocol(asyncio.DatagramProtocol):
    def __init__(self, message: bytes, targets: List[str]):
        self.message = message
        self.targets = targets
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        self._schedule_send()

    def _schedule_send(self):
        if self.transport:
            for target in self.targets:
                try:
                    self.transport.sendto(self.message, (target, BROADCAST_PORT))
                except Exception:
                    pass
            loop = asyncio.get_event_loop()
            loop.call_later(BROADCAST_INTERVAL, self._schedule_send)

    def error_received(self, exc):
        pass


async def start_broadcast(session_id: str):
    await stop_broadcast(session_id)
    port = int(os.environ.get("PORT", 8000))
    ips = get_lan_ip_candidates()
    primary_ip = ips[0] if ips else "127.0.0.1"
    server_url = f"ws://{primary_ip}:{port}"
    message = json.dumps({"server": server_url, "session_id": session_id}, ensure_ascii=False).encode()
    targets = ["255.255.255.255"]
    for ip in ips:
        targets.extend(broadcast_addresses_for_ip(ip))
    targets = list(dict.fromkeys(targets))
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(False)
    transport, _ = await loop.create_datagram_endpoint(
        lambda: BroadcastProtocol(message, targets),
        sock=sock,
    )
    SESSION_BROADCASTS[session_id] = transport


async def stop_broadcast(session_id: str):
    transport = SESSION_BROADCASTS.pop(session_id, None)
    if transport:
        transport.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg.ensure_dirs()
    tr.ensure_dirs()
    yield
    for transport in list(SESSION_BROADCASTS.values()):
        transport.close()
    SESSION_BROADCASTS.clear()


app = FastAPI(title="TalkAssist", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SettingsPayload(BaseModel):
    provider: str
    ollama: Optional[dict] = None
    sakura: Optional[dict] = None
    speech: Optional[dict] = None


class CreateSessionPayload(BaseModel):
    mode: str
    title: Optional[str] = None


class UtterancePayload(BaseModel):
    speaker: str
    text: str


class KnowledgePayload(BaseModel):
    content: str


class PresentationPayload(BaseModel):
    document: Optional[str] = ""
    script: Optional[str] = ""


class MinutesPayload(BaseModel):
    regenerate: bool = False


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/settings")
async def get_settings():
    return cfg.load_config()


@app.post("/api/settings")
async def post_settings(payload: SettingsPayload):
    current = cfg.load_config()
    current["provider"] = payload.provider
    if payload.ollama is not None:
        current["ollama"].update(payload.ollama)
    if payload.sakura is not None:
        current["sakura"].update(payload.sakura)
    if payload.speech is not None:
        current["speech"].update(payload.speech)
    cfg.save_config(current)
    return current


@app.get("/api/modes")
async def get_modes():
    return MODES


@app.post("/api/session")
async def create_session(payload: CreateSessionPayload):
    if payload.mode not in MODES:
        raise HTTPException(status_code=400, detail="不明なモード")
    session = tr.create_session(payload.mode, payload.title)
    await start_broadcast(session["id"])
    return session


@app.get("/api/sessions")
async def list_sessions():
    return tr.list_sessions()


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return session


@app.post("/api/session/{session_id}/utterance")
async def add_utterance(session_id: str, payload: UtterancePayload):
    session = tr.add_utterance(session_id, payload.speaker, payload.text)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return session


@app.get("/api/session/{session_id}/knowledge")
async def get_knowledge(session_id: str):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    content = tr.load_knowledge(session["mode"])
    return {"mode": session["mode"], "content": content}


@app.post("/api/session/{session_id}/knowledge")
async def post_knowledge(session_id: str, payload: KnowledgePayload):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    tr.save_knowledge(session["mode"], payload.content)
    return {"ok": True}


@app.post("/api/session/{session_id}/presentation")
async def set_presentation(session_id: str, payload: PresentationPayload):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    pres = session["presentation"]
    pres["document"] = payload.document or ""
    pres["script"] = payload.script or ""
    pres["slides"] = parse_presentation_document(pres["document"])

    raw_script = pres["script"]
    if "---" in raw_script:
        pres["script_per_slide"] = parse_presentation_script_per_slide(raw_script)
    else:
        script_lines = parse_presentation_script(raw_script)
        slides = pres["slides"]
        if len(slides) <= 1 or not script_lines:
            pres["script_per_slide"] = [script_lines]
        else:
            settings = cfg.load_config()
            runner = AgentRunner(settings)
            pres["script_per_slide"] = await runner.run_assign_script_to_slides(slides, script_lines)

    pres["current_slide_index"] = 0
    pres["covered"] = []
    tr.save_session(session)
    return pres


@app.post("/api/session/{session_id}/minutes")
async def generate_minutes(session_id: str, payload: Optional[MinutesPayload] = None):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    if payload and not payload.regenerate and session.get("minutes"):
        return {"minutes": session["minutes"]}
    settings = cfg.load_config()
    runner = AgentRunner(settings)
    knowledge = tr.load_knowledge(session["mode"])
    minutes = await runner.run_minutes(session, knowledge)
    tr.set_minutes(session_id, minutes)
    return {"minutes": minutes}


@app.get("/api/session/{session_id}/minutes")
async def get_minutes(session_id: str):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    return {"minutes": session.get("minutes", "")}


@app.post("/api/session/{session_id}/assist")
async def assist(session_id: str):
    session = tr.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")
    settings = cfg.load_config()
    runner = AgentRunner(settings)
    knowledge = tr.load_knowledge(session["mode"])
    results = await runner.run_all(session, knowledge)
    return results


@app.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    session = tr.load_session(session_id)
    if not session:
        await websocket.send_text(json.dumps({"type": "error", "message": "セッションが見つかりません"}))
        await websocket.close()
        return

    device = websocket.query_params.get("device", "browser")
    settings = cfg.load_config()
    runner = AgentRunner(settings)
    SESSION_CONNECTIONS.setdefault(session_id, []).append(websocket)

    async def send(kind: str, payload: dict):
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_text(json.dumps({"type": kind, **payload}))

    async def broadcast(kind: str, payload: dict):
        for ws in list(SESSION_CONNECTIONS.get(session_id, [])):
            if ws.client_state == WebSocketState.CONNECTED:
                try:
                    await ws.send_text(json.dumps({"type": kind, **payload}))
                except Exception:
                    pass

    async def process_utterance(speaker: str, text: str):
        session = tr.add_utterance(session_id, speaker, text)
        if not session:
            return
        await broadcast("transcript", {"speaker": speaker, "text": text})
        knowledge = tr.load_knowledge(session["mode"])
        results = await runner.run_all(session, knowledge)
        await broadcast("assist", results)

    async def process_pause():
        session = tr.load_session(session_id)
        if not session:
            return
        knowledge = tr.load_knowledge(session["mode"])
        suggestion = await runner.run_suggestion(session, knowledge, situation="pause")
        await broadcast("suggestion", {"text": suggestion})
        if session.get("mode") == "presentation":
            nav = await runner.run_presentation_navigation(session, knowledge)
            await broadcast("presentation_nav", nav)

    async def process_gap():
        session = tr.load_session(session_id)
        if not session:
            return
        knowledge = tr.load_knowledge(session["mode"])
        filler = await runner.run_suggestion(session, knowledge, situation="gap")
        await broadcast("filler", {"text": filler})
        if session.get("mode") == "presentation":
            nav = await runner.run_presentation_navigation(session, knowledge)
            await broadcast("presentation_nav", nav)

    recognizer = None
    if device == "watch":
        vosk_model = settings.get("speech", {}).get("vosk_model", "small")
        try:
            recognizer = sp.VoskRecognizer(model_type=vosk_model)
        except Exception as e:
            await send("error", {"message": f"Vosk 認識器の初期化に失敗しました: {e}"})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")

            if device == "watch":
                if mtype == "start":
                    model_type = msg.get("model", settings.get("speech", {}).get("vosk_model", "small"))
                    try:
                        recognizer = sp.VoskRecognizer(model_type=model_type)
                        await send("ready", {"model": model_type})
                    except Exception as e:
                        await send("error", {"message": str(e)})
                elif mtype == "audio":
                    if not recognizer:
                        await send("error", {"message": "認識器が開始されていません"})
                        continue
                    try:
                        pcm = base64.b64decode(msg.get("data", ""))
                        result = recognizer.accept_waveform(pcm)
                        text = result.get("text", "") or result.get("partial", "")
                        await send(result["type"], {"text": text})
                    except Exception as e:
                        await send("error", {"message": str(e)})
                elif mtype == "stop":
                    if recognizer:
                        result = recognizer.final_result()
                        text = result.get("text", "")
                        if text:
                            await process_utterance("watch", text)
                        else:
                            await send("final", {"text": ""})
                        recognizer.reset()
                elif mtype == "ping":
                    await send("pong", {})
            else:
                if mtype == "utterance":
                    await process_utterance(msg.get("speaker", "話者"), msg.get("text", ""))
                elif mtype == "pause":
                    await process_pause()
                elif mtype == "gap":
                    await process_gap()
                elif mtype == "assist":
                    session = tr.load_session(session_id)
                    if session:
                        knowledge = tr.load_knowledge(session["mode"])
                        results = await runner.run_all(session, knowledge)
                        await broadcast("assist", results)
                elif mtype == "slide_change":
                    index = msg.get("index", 0)
                    session = tr.load_session(session_id)
                    if session:
                        pres = session.get("presentation", {})
                        slides = pres.get("slides", [])
                        if 0 <= index < len(slides):
                            pres["current_slide_index"] = index
                            tr.save_session(session)
                            knowledge = tr.load_knowledge(session["mode"])
                            nav = await runner.run_slide_check(session, knowledge)
                            await broadcast("presentation_nav", nav)
                elif mtype == "ping":
                    await send("pong", {})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await send("error", {"message": str(e)})
        except Exception:
            pass
    finally:
        connections = SESSION_CONNECTIONS.get(session_id, [])
        if websocket in connections:
            connections.remove(websocket)


@app.websocket("/ws/speech/vosk")
async def vosk_speech_endpoint(websocket: WebSocket):
    await websocket.accept()
    recognizer = None
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
            if mtype == "start":
                model_type = msg.get("model", "small")
                try:
                    recognizer = sp.VoskRecognizer(model_type=model_type)
                    await websocket.send_text(json.dumps({"type": "ready", "model": model_type}))
                except Exception as e:
                    await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
            elif mtype == "audio":
                if not recognizer:
                    await websocket.send_text(json.dumps({"type": "error", "message": "認識器が開始されていません"}))
                    continue
                try:
                    pcm = base64.b64decode(msg.get("data", ""))
                    result = recognizer.accept_waveform(pcm)
                    text = result.get("text", "") or result.get("partial", "")
                    await websocket.send_text(json.dumps({
                        "type": result["type"],
                        "text": text,
                    }))
                except Exception as e:
                    await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
            elif mtype == "stop":
                if recognizer:
                    result = recognizer.final_result()
                    await websocket.send_text(json.dumps({
                        "type": "final",
                        "text": result.get("text", ""),
                    }))
                    recognizer.reset()
            elif mtype == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
