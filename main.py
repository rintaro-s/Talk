import base64
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config as cfg
import speech as sp
import transcript as tr
from agents import AgentRunner
from modes import MODES

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg.ensure_dirs()
    tr.ensure_dirs()
    yield


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
    session["presentation"]["document"] = payload.document or ""
    session["presentation"]["script"] = payload.script or ""
    tr.save_session(session)
    return session["presentation"]


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

    settings = cfg.load_config()
    runner = AgentRunner(settings)

    async def send(kind: str, payload: dict):
        await websocket.send_text(json.dumps({"type": kind, **payload}))

    async def process_utterance(speaker: str, text: str):
        session = tr.add_utterance(session_id, speaker, text)
        if not session:
            return
        await send("transcript", {"speaker": speaker, "text": text})
        knowledge = tr.load_knowledge(session["mode"])
        results = await runner.run_all(session, knowledge)
        await send("assist", results)

    async def process_pause():
        session = tr.load_session(session_id)
        if not session:
            return
        knowledge = tr.load_knowledge(session["mode"])
        suggestion = await runner.run_suggestion(session, knowledge, situation="pause")
        await send("suggestion", {"text": suggestion})
        if session.get("mode") == "presentation":
            nav = await runner.run_presentation_navigation(session, knowledge)
            await send("presentation_nav", nav)

    async def process_gap():
        session = tr.load_session(session_id)
        if not session:
            return
        knowledge = tr.load_knowledge(session["mode"])
        filler = await runner.run_suggestion(session, knowledge, situation="gap")
        await send("filler", {"text": filler})
        if session.get("mode") == "presentation":
            nav = await runner.run_presentation_navigation(session, knowledge)
            await send("presentation_nav", nav)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            mtype = msg.get("type")
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
                    await send("assist", results)
            elif mtype == "ping":
                await send("pong", {})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await send("error", {"message": str(e)})
        except Exception:
            pass


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
