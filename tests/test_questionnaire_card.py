import pytest
from cc_feishu_bridge.format.questionnaire_card import (
    parse_ask_user_question,
    format_questionnaire_card,
    _AskUserQuestionMarker,
)

def test_parse_basic():
    tool_input = '{"question":"你的用户从哪里来？","header":"用户来源","options":[{"label":"私域流量","description":"已有公众号或社群"},{"label":"内容引流","description":"微博/小红书/抖音发内容导流"}],"multiSelect":false}'
    result = parse_ask_user_question(tool_input)
    assert result.question == "你的用户从哪里来？"
    assert result.header == "用户来源"
    assert len(result.options) == 2
    assert result.options[0].label == "私域流量"
    assert result.multi_select is False

def test_format_card_structure():
    tool_input = '{"question":"你的用户从哪里来？","header":"用户来源","options":[{"label":"私域流量","description":"已有公众号或社群"},{"label":"内容引流","description":"微博/小红书/抖音发内容导流"}],"multiSelect":false}'
    marker = _AskUserQuestionMarker("AskUserQuestion", tool_input)
    card = format_questionnaire_card(marker)
    assert card["schema"] == "2.0"
    assert card["config"]["wide_screen_mode"] is True
    assert "body" in card
    assert "elements" in card["body"]

def test_invalid_json_returns_none():
    result = parse_ask_user_question("not json")
    assert result is None