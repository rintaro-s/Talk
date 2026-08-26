import asyncio
import json
from typing import AsyncIterator, Dict, List, Optional

from llm import build_client, LLMError
from modes import (
    get_mode_prompt,
    get_minutes_prompt,
    get_suggestion_prompt,
    parse_presentation_document,
    parse_presentation_script,
    parse_presentation_script_per_slide,
)


def parse_json(raw: str):
    """モデル出力から最初の JSON ブロックを取り出す。"""
    if not raw:
        return None
    # コードフェンスがあれば中身を取る
    import re
    m = re.search(r"```(?:json)?\s*(.*?)```", raw, re.S)
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
    return None


def _split_evenly(lines: List[str], n: int) -> List[List[str]]:
    if n <= 0:
        return []
    if n == 1:
        return [lines]
    size = max(1, len(lines) // n)
    result = []
    for i in range(n - 1):
        start = i * size
        end = start + size
        result.append(lines[start:end])
    result.append(lines[(n - 1) * size:])
    return result


class AgentRunner:
    def __init__(self, config: dict):
        self.config = config
        self.client = build_client(config)

    def _context_messages(self, session: dict, system: str, extra: str = "") -> List[Dict]:
        messages = [{"role": "system", "content": system}]
        if extra:
            messages.append({"role": "user", "content": extra})
        transcript = _format_utterances(session.get("utterances", []))
        if transcript:
            messages.append({"role": "user", "content": f"【会話履歴】\n{transcript}"})
        return messages

    async def _generate(self, messages: List[Dict]) -> str:
        try:
            chunks = []
            async for chunk in self.client.generate(messages, stream=False):
                chunks.append(chunk)
            return "".join(chunks)
        except LLMError as e:
            return f"エラー：{e}"
        except asyncio.TimeoutError:
            return "エラー：LLMからの応答がタイムアウトしました。サーバーの負荷や設定を確認してください。"
        except Exception as e:
            name = type(e).__name__
            msg = str(e) or "詳細不明"
            return f"エラー：{name} - {msg}"

    async def run_summary(self, session: dict, knowledge: str) -> str:
        system = "あなたは会話の要約アシスタントです。箇条書きで簡潔に要約してください。"
        messages = self._context_messages(session, system)
        return await self._generate(messages)

    async def run_next_actions(self, session: dict, knowledge: str) -> str:
        system = "あなたは次のアクション提案アシスタントです。箇条書きで簡潔に提案してください。"
        messages = self._context_messages(session, system)
        return await self._generate(messages)

    async def run_questions(self, session: dict, knowledge: str) -> str:
        system = "あなたは疑問点を指摘するアシスタントです。箇条書きで簡潔に挙げてください。"
        messages = self._context_messages(session, system)
        return await self._generate(messages)

    async def run_suggestion(self, session: dict, knowledge: str, situation: str = "pause") -> str:
        system = get_suggestion_prompt(session.get("mode", "general"), knowledge)
        messages = self._context_messages(session, system)
        if situation == "gap":
            messages.append({"role": "user", "content": "沈黙が続いています。場をつなぐ短い一文を生成してください。"})
        else:
            messages.append({"role": "user", "content": "会話が途切れました。次に話すべき短い一文を提案してください。"})
        return await self._generate(messages)

    async def run_mode_specific(self, session: dict, knowledge: str):
        mode = session.get("mode", "general")
        system = get_mode_prompt(mode, knowledge)
        messages = self._context_messages(session, system)

        if mode == "presentation":
            doc = session.get("presentation", {}).get("document", "")
            script = session.get("presentation", {}).get("script", "")
            if doc.strip() or script.strip():
                extra = "【資料とカンペ】\n"
                if doc.strip():
                    sections = parse_presentation_document(doc.strip())
                    extra += "資料スライド：\n"
                    for i, sec in enumerate(sections, 1):
                        title = sec.get("title", f"スライド {i}")
                        body = sec.get("body", "")
                        extra += f"[{i}] {title}\n{body}\n\n"
                if script.strip():
                    lines = parse_presentation_script(script.strip())
                    extra += "カンペ：\n" + "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
                    extra += "\n\n"
                messages.insert(1, {"role": "user", "content": extra})

        raw = await self._generate(messages)
        parsed = parse_json(raw)
        if parsed is None:
            return {"error": raw}
        return parsed

    async def run_minutes(self, session: dict, knowledge: str) -> str:
        mode = session.get("mode", "general")
        system = get_minutes_prompt(mode, knowledge)
        messages = self._context_messages(session, system)
        return await self._generate(messages)

    async def run_assign_script_to_slides(self, slides: List[Dict], script_lines: List[str]) -> List[List[str]]:
        """カンペが --- 区切りでない場合、LLM で各スライドに割り当てる"""
        if not script_lines:
            return [[] for _ in slides]
        if len(slides) <= 1:
            return [script_lines]

        system = """あなたはプレゼン資料とカンペを紐付けるアシスタントです。
資料は複数のスライドに分割されています。カンペは1行ごとに話すポイントです。
各カンペ行を、最も関連性の高いスライドに割り当ててください。JSONだけで返してください。
{
  "script_per_slide": [
    ["スライド1に割り当てたカンペ行", "..."],
    ["スライド2に割り当てたカンペ行", "..."],
    ...
  ]
}
説明や前置きは書かないでください。"""
        messages = [{"role": "system", "content": system}]
        ctx = "【資料スライド】\n"
        for i, slide in enumerate(slides, 1):
            ctx += f"[{i}] {slide.get('title', '')}\n{slide.get('body', '')}\n\n"
        ctx += "【カンペ】\n" + "\n".join(f"{i+1}. {line}" for i, line in enumerate(script_lines))
        messages.append({"role": "user", "content": ctx})

        raw = await self._generate(messages)
        parsed = parse_json(raw)
        if parsed is None:
            return _split_evenly(script_lines, len(slides))
        result = parsed.get("script_per_slide", [])
        if not isinstance(result, list) or len(result) != len(slides):
            return _split_evenly(script_lines, len(slides))
        return result

    async def run_slide_check(self, session: dict, knowledge: str) -> Dict:
        """ページめくり時：カンペと発話履歴を比較して未カバー項目を返す"""
        pres = session.get("presentation", {})
        slides = pres.get("slides", [])
        scripts = pres.get("script_per_slide", [])
        index = pres.get("current_slide_index", 0)
        if not slides or index >= len(slides):
            return {
                "current_slide_index": index,
                "current_slide": "",
                "script": [],
                "missing": [],
                "covered": [],
                "next_script": "",
            }
        slide = slides[index]
        script = scripts[index] if index < len(scripts) else []
        transcript = _format_utterances(session.get("utterances", []))
        system = """あなたはプレゼンナビゲーターです。
現在のスライドのカンペと発話履歴を比較し、カンペのうち発話履歴に含まれていないポイントを JSON だけで返してください。
{
  "missing": ["言っていないカンペ行"],
  "covered": ["言ったと判断できるカンペ行"],
  "next_script": "次に話すべきカンペの一文"
}
説明や前置きは書かないでください。"""
        messages = [{"role": "system", "content": system}]
        ctx = f"【現在のスライド】\n{slide.get('title', '')}\n{slide.get('body', '')}\n\n"
        ctx += "【カンペ】\n" + "\n".join(f"{i+1}. {line}" for i, line in enumerate(script))
        ctx += "\n\n"
        if transcript:
            ctx += f"【発話履歴】\n{transcript}\n\n"
        messages.append({"role": "user", "content": ctx})
        raw = await self._generate(messages)
        parsed = parse_json(raw)
        if parsed is None:
            return {
                "current_slide_index": index,
                "current_slide": slide.get("title", ""),
                "script": script,
                "missing": [],
                "covered": [],
                "next_script": "",
            }
        return {
            "current_slide_index": index,
            "current_slide": slide.get("title", ""),
            "script": script,
            "missing": parsed.get("missing", []),
            "covered": parsed.get("covered", []),
            "next_script": parsed.get("next_script", ""),
        }

    async def run_presentation_navigation(self, session: dict, knowledge: str) -> Dict:
        """プレゼン支援専用：次のカンペ行と未カバー項目を返す"""
        pres = session.get("presentation", {})
        doc_text = pres.get("document", "")
        script_text = pres.get("script", "")
        covered = pres.get("covered", [])
        transcript = _format_utterances(session.get("utterances", []))

        index = pres.get("current_slide_index", 0)
        if not doc_text.strip() and not script_text.strip():
            return {
                "current_slide_index": index,
                "current_slide": "",
                "script": [],
                "current_topic": "資料とカンペが未登録です",
                "next_script": "",
                "missing": [],
                "filler": "",
            }
        slides = parse_presentation_document(doc_text.strip())
        scripts = parse_presentation_script_per_slide(script_text.strip())
        slide = slides[index] if index < len(slides) else {}
        script = scripts[index] if index < len(scripts) else []

        system = """あなたはプレゼンのナビゲーターです。資料スライドとカンペ、発話履歴を参照してJSON形式で回答してください。
{
  "current_slide": "現在話しているスライド番号とタイトル 例: 3. 提案する仕組み",
  "current_topic": "今このスライドで話すべきこと",
  "next_script": "次に話すべきカンペの一文",
  "missing": ["まだ触れられていないポイント"],
  "filler": "言葉に詰まった時の短い場繋ぎ文"
}
だけを出力してください。"""
        messages = [{"role": "system", "content": system}]
        ctx = ""
        if doc_text.strip():
            sections = parse_presentation_document(doc_text.strip())
            ctx += "【資料スライド】\n"
            for i, sec in enumerate(sections, 1):
                title = sec.get("title", f"スライド {i}")
                body = sec.get("body", "")
                ctx += f"[{i}] {title}\n{body}\n\n"
        if script_text.strip():
            lines = parse_presentation_script(script_text.strip())
            ctx += "【カンペ】\n" + "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
            ctx += "\n\n"
        if transcript:
            ctx += f"【発話履歴】\n{transcript}\n\n"
        ctx += "これまで触れたポイント：" + (", ".join(covered) if covered else "なし")
        messages.append({"role": "user", "content": ctx})

        raw = await self._generate(messages)
        parsed = parse_json(raw)
        if parsed is None:
            return {
                "current_slide_index": index,
                "current_slide": slide.get("title", ""),
                "script": script,
                "current_topic": raw.strip(),
                "next_script": "",
                "missing": [],
                "filler": "",
            }
        parsed["current_slide_index"] = index
        parsed["current_slide"] = slide.get("title", "")
        parsed["script"] = script
        return parsed

    async def run_all(self, session: dict, knowledge: str) -> Dict[str, object]:
        """モード別構造化データを並列実行"""
        mode = session.get("mode", "general")
        tasks = {
            "mode_specific": self.run_mode_specific(session, knowledge),
            "summary": self.run_summary(session, knowledge),
        }
        if mode in ("general", "interviewer", "ideation"):
            tasks["next_actions"] = self.run_next_actions(session, knowledge)
            tasks["questions"] = self.run_questions(session, knowledge)
        results = await asyncio.gather(*tasks.values())
        return dict(zip(tasks.keys(), results))


def _format_utterances(utterances: List[Dict], max_turns: int = 20) -> str:
    lines = []
    for u in utterances[-max_turns:]:
        speaker = u.get("speaker", "?")
        text = u.get("text", "")
        lines.append(f"{speaker}：{text}")
    return "\n".join(lines)
