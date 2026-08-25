"""言語モデルの共有クライアント。

日本語の解説・翻訳・省略補完に使う。方針は 2 つ。

1. **構造は渡す、意味だけ聞く。** 文節・述語・格フレームは形態素解析で決定論的に取り、
   LLM には「この穴に入る語はどれか」だけを聞く。丸投げすると外す
   （実測: 明示されている主語を「省略」と誤答した）。
2. **思考は切る。** 推論モードだと 1 件に 30 秒かかり英語の思考文が混ざる。
   切ると 1 秒で JSON が返る。

既定は **ローカルの Ollama** を使う。transformers 版だと解析用のモデルと
VRAM を奪い合い、実際に「CUDA out of memory」で機能が落ちた。Ollama なら
モデルを 1 つのプロセスが抱え、使い終われば手放す。
Ollama が居なければ transformers に落ち、それも無ければ黙って機能が縮退する。
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_MODEL = "Qwen/Qwen3.5-4B"
OLLAMA_MODEL = "qwen3.5:9b"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


@dataclass
class OllamaConfig:
    model: str = OLLAMA_MODEL
    host: str = OLLAMA_HOST
    max_new_tokens: int = 512
    timeout: int = 180


class Ollama:
    """ローカルの Ollama。既定の経路。

    利点は VRAM を占有し続けないこと。解析側（因果着色の言語モデル）と
    取り合いにならない。欠点は起動ごとに読み込みが入ることだが、
    Ollama 側が数分は抱えたままにするので実用上は気にならない。
    """

    available = True
    backend = "ollama"

    def __init__(self, cfg: Optional[OllamaConfig] = None):
        self.cfg = cfg or OllamaConfig()
        tags = self._get("/api/tags")
        names = {m.get("name", "") for m in tags.get("models", [])}
        if self.cfg.model not in names:
            raise RuntimeError(
                f"{self.cfg.model} がありません（ollama pull {self.cfg.model}）。"
                f"あるのは: {', '.join(sorted(names)) or 'なし'}"
            )

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(self.cfg.host + path)
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.load(res)

    def placement(self) -> str:
        """いまモデルが GPU に載っているか CPU に落ちているか。

        Ollama は CUDA バックエンドの入っていないビルドだと黙って CPU で動く。
        実測でその状態だと語を 1 つ引くのに 11〜69 秒かかり、GPU だと 0.5 秒だった。
        **同じ「動いています」でも 100 倍違う。** 黙って劣化させない。
        """
        try:
            ps = self._get("/api/ps")
        except Exception:
            return "unknown"
        for m in ps.get("models", []):
            if m.get("name") != self.cfg.model:
                continue
            total, vram = m.get("size", 0), m.get("size_vram", 0)
            if not total:
                return "unknown"
            if vram >= total * 0.9:
                return "gpu"
            return "partial" if vram else "cpu"
        return "unloaded"

    def ask(self, system: str, user: str, max_new_tokens: Optional[int] = None) -> str:
        body = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,          # 推論モードは遅く、思考文が混ざる
            # 読み込んだままにしておく。既定の 5 分だと、少し間が空いただけで
            # 次のクリックが読み込み待ちになる
            "keep_alive": "30m",
            "options": {
                "temperature": 0,
                "num_predict": max_new_tokens or self.cfg.max_new_tokens,
            },
        }
        req = urllib.request.Request(
            self.cfg.host + "/api/chat",
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as res:
                data = json.load(res)
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama に繋がりません: {exc}") from exc
        return (data.get("message") or {}).get("content", "")

    def ask_json(self, system: str, user: str, max_new_tokens: Optional[int] = None) -> Any:
        raw = self.ask(system, user, max_new_tokens)
        data = parse_json(raw)
        if data is None and raw.strip():
            print(f"[nihongo] JSON を読めませんでした: {raw[:180]!r}")
        return data


@dataclass
class LlmConfig:
    model: str = DEFAULT_MODEL
    device: str = "auto"
    dtype: str = "bfloat16"
    max_new_tokens: int = 512
    enable_thinking: bool = False


class Llm:
    """transformers 版。無い環境では `available = False` になり、機能が黙って落ちる。"""

    available = True
    backend = "transformers"

    def __init__(self, cfg: Optional[LlmConfig] = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.cfg = cfg or LlmConfig()
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(self.cfg.model)
        device = self.cfg.device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        dtype = getattr(torch, self.cfg.dtype) if device != "cpu" else torch.float32
        self.model = AutoModelForCausalLM.from_pretrained(self.cfg.model, dtype=dtype)
        self.model.eval()
        self.model.to(device)
        self.device = device
        self._lock = threading.Lock()

    def ask(self, system: str, user: str, max_new_tokens: Optional[int] = None) -> str:
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        kw: dict[str, Any] = {}
        if self.cfg.enable_thinking is False:
            kw["enable_thinking"] = False
        with self._lock:  # モデルはスレッドセーフでない
            enc = self.tok.apply_chat_template(
                msgs, add_generation_prompt=True, return_dict=True, return_tensors="pt", **kw
            ).to(self.device)
            with self.torch.no_grad():
                out = self.model.generate(
                    **enc,
                    max_new_tokens=max_new_tokens or self.cfg.max_new_tokens,
                    do_sample=False,
                    temperature=None,
                    top_p=None,
                    top_k=None,
                    pad_token_id=self.tok.eos_token_id,
                )
            return self.tok.decode(out[0][enc["input_ids"].shape[1] :], skip_special_tokens=True)

    def ask_json(self, system: str, user: str, max_new_tokens: Optional[int] = None) -> Any:
        """JSON を期待して聞く。壊れた出力は None を返す（呼び出し側で握る）。"""
        raw = self.ask(system, user, max_new_tokens)
        data = parse_json(raw)
        if data is None and raw.strip():
            print(f"[nihongo] JSON を読めませんでした: {raw[:180]!r}")
        return data


class NullLlm:
    available = False
    backend = "none"

    def ask(self, *a, **kw) -> str:
        return ""

    def ask_json(self, *a, **kw) -> Any:
        return None


def parse_json(raw: str) -> Any:
    """モデル出力から JSON を取り出す。前置きやコードフェンスが付いても拾う。

    **最初に現れた括弧から、対応する閉じ括弧まで**を切り出す。
    素朴に「[ を探す」とすると、オブジェクトの内側にある配列を掴んでしまう
    （実測: {"points":[...]} から points の中身だけが返っていた）。
    """
    if not raw:
        return None
    m = _JSON_BLOCK.search(raw)
    if m:
        raw = m.group(1)
    raw = raw.strip()

    start = -1
    for k, ch in enumerate(raw):
        if ch in "[{":
            start = k
            break
    if start < 0:
        return None

    opener = raw[start]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_str = False
    escape = False
    for k in range(start, len(raw)):
        ch = raw[k]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : k + 1])
                except json.JSONDecodeError:
                    break
    # 途中で切れている場合の保険。閉じていない配列から、完成している要素だけを拾う
    try:
        return json.loads(raw[start:])
    except json.JSONDecodeError:
        pass
    if opener == "[":
        items = []
        depth = 0
        in_str = False
        escape = False
        obj_start = -1
        for k in range(start + 1, len(raw)):
            ch = raw[k]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                if depth == 0:
                    obj_start = k
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and obj_start >= 0:
                    try:
                        items.append(json.loads(raw[obj_start : k + 1]))
                    except json.JSONDecodeError:
                        pass
                    obj_start = -1
        if items:
            return items
    return None


_shared: Optional[Any] = None
_shared_lock = threading.Lock()


def get_llm(cfg: Optional[LlmConfig] = None):
    """プロセス内で 1 つだけ持つ。

    順に試す ── Ollama（既定）→ transformers → 無し。
    Ollama を先にするのは VRAM の取り合いを避けるため。
    環境変数 YOMITOKI_LLM で 'ollama' / 'transformers' / 'none' を強制できる。
    """
    global _shared
    with _shared_lock:
        if _shared is not None:
            return _shared
        want = os.environ.get("YOMITOKI_LLM", "").strip().lower()
        if want == "none":
            _shared = NullLlm()
            return _shared
        if want in ("", "ollama"):
            try:
                _shared = Ollama()
                print(f"[nihongo] 言語モデル: Ollama {OLLAMA_MODEL}")
                return _shared
            except Exception as exc:
                if want == "ollama":
                    print(f"[nihongo] Ollama を使えません: {exc}")
                    _shared = NullLlm()
                    return _shared
                print(f"[nihongo] Ollama を使えないので transformers に切り替えます: {exc}")
        try:
            _shared = Llm(cfg)
        except Exception as exc:  # torch 未導入・モデル未取得など
            print(f"[nihongo] 言語モデルを読めません（機能を縮退します）: {exc}")
            _shared = NullLlm()
        return _shared


SYSTEM_JA = "あなたは日本語教師です。出力は JSON のみ。説明や前置きは書かないでください。"
