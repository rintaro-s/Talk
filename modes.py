from typing import Dict, List
import re

MODES: Dict[str, Dict] = {
    "general": {
        "name": "汎用会話",
        "description": "会議・相談・打ち合わせ向け",
    },
    "interviewer": {
        "name": "面接官",
        "description": "候補者を評価・深掘りする場面向け",
    },
    "ideation": {
        "name": "アイデア出し",
        "description": "ブレスト・企画会議向け",
    },
    "presentation": {
        "name": "プレゼン",
        "description": "資料を見ながら話す場面向け",
    },
}


def get_mode_prompt(mode: str, knowledge: str) -> str:
    """各モード専用のシステムプロンプト。JSON で構造化された出力を期待する。"""
    base = ""
    if mode == "general":
        base = """あなたは会話の補助アシスタントです。
会話から以下を抽出し、必ず JSON だけで返してください。

{
  "next_task": "今すぐ次にやるべきことを1行で",
  "summary": "会話の要約",
  "decisions": ["決定事項"],
  "unresolved": ["未解決事項"],
  "next_actions": ["次のアクション"],
  "questions": ["疑問点"]
}

説明や前置きは書かないでください。"""
    elif mode == "interviewer":
        base = """あなたは面接官向けの支援アシスタントです。
候補者の発言から以下を抽出し、必ず JSON だけで返してください。

{
  "claim": "候補者の主張を1行で",
  "deep_questions": ["今すぐ深掘りすべき質問", "次の質問", "さらに質問"],
  "evaluation_axes": ["まだ確認できていない評価軸"],
  "contradictions": ["曖昧さや矛盾"],
  "observation": "次に観察すべきポイント"
}

説明や前置きは書かないでください。"""
    elif mode == "ideation":
        base = """あなたはアイデア出しのファシリテーターです。
会話からアイデアを抽出・整理し、必ず JSON だけで返してください。

{
  "root": "現在のテーマ",
  "categories": [
    {
      "name": "カテゴリ名",
      "ideas": [
        {"text": "アイデア", "note": "優先度や関連性など"}
      ]
    }
  ],
  "similar": "過去のアイデアと似ている点",
  "next_question": "次に広げるべき問い"
}

説明や前置きは書かないでください。"""
    elif mode == "presentation":
        base = """あなたはプレゼンのナビゲーターです。
資料とカンペ、発話履歴から以下を抽出し、必ず JSON だけで返してください。

{
  "current_slide": "現在話しているセクション",
  "current_topic": "今このスライドで話すべきこと",
  "missing": ["言い漏れ"],
  "next_script": "次に話す一文",
  "filler": "言葉に詰まった時の場繋ぎ文"
}

説明や前置きは書かないでください。"""
    else:
        base = """あなたは会話の補助アシスタントです。
会話から要点を抽出し、必ず JSON だけで返してください。

{
  "summary": "要約",
  "next_task": "次にやること",
  "questions": ["疑問点"]
}

説明や前置きは書かないでください。"""

    if knowledge.strip():
        return f"【事前情報】\n{knowledge.strip()}\n\n【指示】\n{base}"
    return base


def get_suggestion_prompt(mode: str, knowledge: str) -> str:
    base = "会話が途切れました。次に話すべき短い一文を提案してください。無理に長くせず、自然な流れに戻すだけで構いません。"
    if mode == "interviewer":
        base = "面接が止まりました。候補者に次の深掘り質問を短く投げかけてください。"
    elif mode == "ideation":
        base = "アイデア出しが止まりました。話を再開させるための短い問いかけや視点を提案してください。"
    elif mode == "presentation":
        base = "プレゼンで言葉が出ません。次のカンペの内容に自然に繋げる短い一文を提案してください。"
    if knowledge.strip():
        return f"【事前情報】\n{knowledge.strip()}\n\n{base}"
    return base


def get_minutes_prompt(mode: str, knowledge: str) -> str:
    base = "以下の会話から議事録を作成してください。"
    if mode == "general":
        base = "以下の会話から、要約・決定事項・未解決事項・次のアクションを含む議事録を作成してください。"
    elif mode == "interviewer":
        base = "以下の面接の会話から、候補者の回答と面接官の確認ポイントの議事録を作成してください。"
    elif mode == "ideation":
        base = "以下のアイデア出しの会話から、出たアイデアと評価の議事録を作成してください。"
    elif mode == "presentation":
        base = "以下のプレゼンの会話から、話された内容と未カバーのポイントを含む議事録を作成してください。"
    if knowledge.strip():
        return f"【事前情報】\n{knowledge.strip()}\n\n{base}"
    return base


def parse_presentation_document(text: str) -> List[Dict]:
    """資料テキストをスライドに分割する（--- または # 見出しで区切る）"""
    raw = text.replace("\r\n", "\n")
    blocks = [b.strip() for b in re.split(r"^---\s*$", raw, flags=re.MULTILINE) if b.strip()]
    if len(blocks) > 1:
        sections = []
        for i, block in enumerate(blocks, 1):
            lines = block.splitlines()
            title = ""
            body_lines = []
            for line in lines:
                line = line.rstrip()
                if not line.strip():
                    continue
                if line.startswith("#") and not title:
                    title = line.lstrip("#").strip()
                else:
                    body_lines.append(line)
            sections.append({
                "title": title or f"スライド {i}",
                "body": "\n".join(body_lines).strip(),
            })
        return sections

    sections = []
    current = {"title": "", "body": []}
    for line in text.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("#"):
            if current["body"] or current["title"]:
                sections.append({
                    "title": current["title"],
                    "body": "\n".join(current["body"]).strip(),
                })
            current = {"title": line.lstrip("#").strip(), "body": []}
        else:
            current["body"].append(line)
    if current["body"] or current["title"]:
        sections.append({
            "title": current["title"],
            "body": "\n".join(current["body"]).strip(),
        })
    if not sections:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        for i, p in enumerate(paragraphs):
            sections.append({"title": f"セクション {i+1}", "body": p})
    return sections


def parse_presentation_script(text: str) -> List[str]:
    """カンペを行単位に分割する"""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)
    return lines


def parse_presentation_script_per_slide(text: str) -> List[List[str]]:
    """カンペをスライドごとに分割する（--- で区切る）"""
    slides = []
    current = []
    for line in text.splitlines():
        line = line.strip()
        if line == "---":
            slides.append(current)
            current = []
        elif line:
            current.append(line)
    if current:
        slides.append(current)
    if not slides:
        return [[]]
    return slides
