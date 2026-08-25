import base64
import json
import os
import zipfile
from pathlib import Path
from typing import Optional

import requests
from vosk import Model, KaldiRecognizer

DATA_DIR = Path(__file__).parent / "data"
VOSK_DIR = DATA_DIR / "vosk_models"

MODEL_URLS = {
    "small": "https://alphacephei.com/vosk/models/vosk-model-small-ja-0.22.zip",
    "ja": "https://alphacephei.com/vosk/models/vosk-model-ja-0.22.zip",
}


def ensure_vosk_dir():
    VOSK_DIR.mkdir(parents=True, exist_ok=True)


def model_path(model_type: str) -> Optional[Path]:
    ensure_vosk_dir()
    candidates = list(VOSK_DIR.glob(f"vosk-model*{model_type}*"))
    if candidates:
        return candidates[0]
    return None


def download_model(model_type: str) -> Path:
    ensure_vosk_dir()
    if model_type not in MODEL_URLS:
        raise ValueError(f"不明なモデル種別: {model_type}")

    url = MODEL_URLS[model_type]
    zip_path = VOSK_DIR / f"{model_type}.zip"

    if zip_path.exists():
        zip_path.unlink()

    print(f"Downloading Vosk model from {url} ...")
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with zip_path.open("wb") as f:
            downloaded = 0
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = downloaded * 100 // total
                        print(f"\r  {pct}%", end="")
    print()

    print("Extracting...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(VOSK_DIR)
    zip_path.unlink()

    candidates = list(VOSK_DIR.glob("vosk-model*"))
    if not candidates:
        raise RuntimeError("モデル展開後にディレクトリが見つかりません")
    return candidates[0]


def get_model(model_type: str) -> Model:
    path = model_path(model_type)
    if not path:
        path = download_model(model_type)
    return Model(str(path))


class VoskRecognizer:
    def __init__(self, model_type: str = "small", sample_rate: int = 16000):
        self.model_type = model_type
        self.sample_rate = sample_rate
        self.model = get_model(model_type)
        self.recognizer = KaldiRecognizer(self.model, sample_rate)
        self.recognizer.SetWords(False)

    def reset(self):
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
        self.recognizer.SetWords(False)

    def accept_waveform(self, pcm_bytes: bytes) -> dict:
        """PCM bytes (16-bit signed, mono) を受け取り、認識結果を返す"""
        finished = self.recognizer.AcceptWaveform(pcm_bytes)
        if finished:
            return {"type": "final", **json.loads(self.recognizer.Result())}
        else:
            return {"type": "partial", **json.loads(self.recognizer.PartialResult())}

    def final_result(self) -> dict:
        return {"type": "final", **json.loads(self.recognizer.FinalResult())}
