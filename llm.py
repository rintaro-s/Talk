import json
import os
from typing import AsyncIterator, List, Dict, Optional
import aiohttp

LLM_TIMEOUT = aiohttp.ClientTimeout(total=60, connect=5)


class LLMError(Exception):
    pass


def build_client(config: dict):
    provider = config.get("provider", "ollama")
    if provider == "ollama":
        return OllamaClient(config["ollama"])
    if provider == "sakura":
        return SakuraClient(config["sakura"])
    raise LLMError(f"不明なプロバイダ: {provider}")


class OllamaClient:
    def __init__(self, cfg: dict):
        self.endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")
        self.model = cfg.get("model", "qwen3.5:9b")
        self.think = cfg.get("think", False)

    def _prepare_messages(self, messages: List[Dict]) -> List[Dict]:
        # think はリクエストボディのトップレベルで制御
        return [m.copy() for m in messages]

    async def generate(self, messages: List[Dict], stream: bool = False) -> AsyncIterator[str]:
        url = f"{self.endpoint}/api/chat"
        options = {"temperature": 0.7}
        payload = {
            "model": self.model,
            "messages": self._prepare_messages(messages),
            "stream": stream,
            "think": self.think,
            "keep_alive": "30m",
            "options": options,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=LLM_TIMEOUT) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise LLMError(f"Ollama error {resp.status}: {text}")
                if not stream:
                    data = await resp.json()
                    yield data.get("message", {}).get("content", "")
                    return
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    chunk = data.get("message", {}).get("content", "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break


class SakuraClient:
    def __init__(self, cfg: dict):
        self.endpoint = cfg.get("endpoint", "https://api.ai.sakura.ad.jp/v1/responses").rstrip("/")
        self.model = cfg.get("model", "sakura-ai-engine")
        self.api_key = cfg.get("api_key", "")

    def _is_responses_endpoint(self) -> bool:
        return self.endpoint.endswith("/responses")

    def _headers(self) -> Dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def generate(self, messages: List[Dict], stream: bool = False) -> AsyncIterator[str]:
        if self._is_responses_endpoint():
            payload = {
                "model": self.model,
                "input": messages,
                "stream": stream,
                "temperature": 0.7,
            }
        else:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": stream,
                "temperature": 0.7,
            }
        async with aiohttp.ClientSession() as session:
            async with session.post(self.endpoint, json=payload, headers=self._headers(), timeout=LLM_TIMEOUT) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise LLMError(f"Sakura error {resp.status}: {text}")
                if not stream:
                    data = await resp.json()
                    if "output_text" in data:
                        yield data["output_text"]
                    elif "choices" in data and data["choices"]:
                        yield data["choices"][0].get("message", {}).get("content", "")
                    else:
                        yield ""
                    return
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line or not line.startswith("data: "):
                        continue
                    json_str = line[len("data: "):]
                    if json_str == "[DONE]":
                        break
                    try:
                        data = json.loads(json_str)
                    except json.JSONDecodeError:
                        continue
                    chunk = ""
                    if "delta" in data:
                        chunk = data["delta"].get("content", "")
                    elif "output" in data and data["output"]:
                        chunk = data["output"][0].get("content", "")
                    elif "choices" in data and data["choices"]:
                        delta = data["choices"][0].get("delta", {})
                        chunk = delta.get("content", "")
                    if chunk:
                        yield chunk
