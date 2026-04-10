"""AskUserQuestion 飞书卡片构建。"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass


@dataclass
class _Option:
    label: str
    description: str


@dataclass
class _QuestionnaireData:
    question: str
    header: str
    options: list[_Option]
    multi_select: bool


def parse_ask_user_question(tool_input: str) -> _QuestionnaireData | None:
    """解析 AskUserQuestion tool_input JSON。"""
    try:
        data = json.loads(tool_input)
    except json.JSONDecodeError:
        return None

    question = data.get("question", "")
    header = data.get("header", "")
    multi_select = bool(data.get("multiSelect", False))
    raw_options = data.get("options", [])

    if not question and not raw_options:
        return None

    options = [
        _Option(label=opt.get("label", ""), description=opt.get("description", ""))
        for opt in raw_options
        if isinstance(opt, dict)
    ]
    return _QuestionnaireData(
        question=question,
        header=header,
        options=options,
        multi_select=multi_select,
    )


def _render_question_text(question: str) -> str:
    """渲染问题文本，保留 markdown 格式。"""
    text = re.sub(r"\n{3,}", "\n\n", question)
    return text.strip()


def _render_option_text(option: _Option, index: int) -> str:
    """将单个选项渲染为加粗标签 + 描述。"""
    label = f"**{index}. {option.label}**"
    if option.description:
        return f"{label}\n{option.description}"
    return label


def format_questionnaire_card(marker: "_AskUserQuestionMarker") -> dict:
    """构建 AskUserQuestion 的飞书 Interactive Card。"""
    data = marker.data
    elements = []

    if data.header:
        elements.append({
            "tag": "tag",
            "text": f"📋 {data.header}",
            "color": "grey",
        })

    question_md = _render_question_text(data.question)
    elements.append({
        "tag": "markdown",
        "content": question_md,
    })

    elements.append({"tag": "hr"})

    if data.options:
        select_label = "可多选" if data.multi_select else "单选"
        elements.append({
            "tag": "markdown",
            "content": f"**{select_label}**，请回复选项编号或内容：",
        })

        for i, opt in enumerate(data.options, 1):
            option_md = _render_option_text(opt, i)
            elements.append({
                "tag": "markdown",
                "content": option_md,
            })
            if i < len(data.options):
                elements.append({"tag": "hr"})

    elements.append({
        "tag": "markdown",
        "content": "_请直接回复选项编号（如 1）或选项内容_",
    })

    return {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
        },
        "body": {
            "elements": elements,
        },
    }


class _AskUserQuestionMarker:
    """通知 message_handler 此工具调用需要渲染问卷卡片。"""
    __slots__ = ("tool_name", "tool_input", "data")

    def __init__(self, tool_name: str, tool_input: str):
        self.tool_name = tool_name
        self.tool_input = tool_input
        parsed = parse_ask_user_question(tool_input)
        self.data: _QuestionnaireData | None = parsed