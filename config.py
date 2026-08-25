import json
import os
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent / "data"
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "provider": "ollama",
    "ollama": {
        "endpoint": "http://localhost:11434",
        "model": "qwen3.5:9b",
        "think": False,
    },
    "sakura": {
        "endpoint": "https://api.ai.sakura.ad.jp/v1/responses",
        "model": "sakura-ai-engine",
        "api_key": "",
    },
    "speech": {
        "provider": "web_speech",
        "vosk_model": "small",
    },
}


def ensure_dirs():
    (DATA_DIR / "sessions").mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "knowledge").mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    ensure_dirs()
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as f:
                saved = json.load(f)
            merged = DEFAULT_CONFIG.copy()
            merged.update(saved)
            for key in DEFAULT_CONFIG:
                if isinstance(DEFAULT_CONFIG[key], dict) and key in merged:
                    merged[key] = {**DEFAULT_CONFIG[key], **merged.get(key, {})}
            return merged
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    ensure_dirs()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
