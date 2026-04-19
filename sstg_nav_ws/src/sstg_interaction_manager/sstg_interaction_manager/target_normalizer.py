"""Canonical normalization for user search target strings.

This module is shared between `sstg_interaction_manager` and
`sstg_navigation_planner`. Both packages MUST keep this file byte-identical;
`test_navigation_planner.py::test_normalize_search_target_cross_package`
guards against drift.

Input: an already-extracted entity like "我的书包", "帮我找书包", "书包呢".
Output: canonical form like "书包". Returns '' when reduction yields nothing.
"""

# Longest prefixes first — the first match wins (greedy).
_PREFIXES = (
    '找我的', '帮我找', '到我的', '给我找',
    '我的', '找', '到', '帮', '给',
)

_SUFFIXES = (
    '在哪里', '在哪', '的位置', '去哪了', '的图',
)

_TRAILING_STOP_CHARS = set('的了吗呢吧在')


# English synonym → Chinese canonical label. When NLP (LLM) mistakenly picks the
# English synonym but the user spoke Chinese, we map back so UI text stays in
# the user's language. Keys must be lowercase.
_EN_TO_ZH_LABEL = {
    'backpack': '书包', 'schoolbag': '书包', 'bag': '书包', 'handbag': '包',
    'chair': '椅子', 'seat': '椅子', 'office chair': '椅子',
    'table': '桌子', 'desk': '桌子',
    'bed': '床',
    'door': '门', 'gate': '门',
    'window': '窗', 'window_frame': '窗',
    'lamp': '灯', 'light': '灯', 'bulb': '灯', 'ceiling_light': '灯',
    'sofa': '沙发', 'couch': '沙发', 'settee': '沙发',
    'book': '书', 'books': '书',
    'computer': '电脑', 'laptop': '电脑', 'monitor': '电脑',
    'computer_monitor': '电脑',
    'refrigerator': '冰箱', 'fridge': '冰箱',
    'trash_can': '垃圾桶', 'trash bin': '垃圾桶', 'dustbin': '垃圾桶',
    'cabinet': '柜子', 'file cabinet': '柜子', 'cupboard': '柜子',
    'fire_extinguisher': '灭火器', 'fire_extinguisher_cabinet': '灭火器',
    'water_bottle': '水瓶', 'water_bottles': '水瓶', 'bottle': '水瓶',
    'headphones': '耳机', 'earphone': '耳机',
    'toy': '玩具', 'toys': '玩具',
    'carpet': '地毯', 'rug': '地毯',
    'person': '人', 'people': '人',
}


def _contains_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def prefer_chinese_label(target: str, original_text: str = '') -> str:
    """If `target` is English but its Chinese equivalent lives in `original_text`
    (or the user context is clearly Chinese), return the Chinese canonical.

    This is a display-layer safety net: NLP sometimes returns "backpack" when the
    user typed "找书包". Downstream modules (planner, VLM prompts, UI text) all
    share the same search_target value — mapping it back to Chinese keeps UI
    consistent with what the user actually said.
    """
    if not target:
        return target
    # Already contains Chinese chars → trust it.
    if _contains_chinese(target):
        return target
    zh = _EN_TO_ZH_LABEL.get(target.strip().lower())
    if not zh:
        return target
    # Strongest signal: the Chinese label already appears in user's text.
    if original_text and zh in original_text:
        return zh
    # Fallback: if user's original_text is Chinese overall, prefer Chinese label.
    if original_text and _contains_chinese(original_text):
        return zh
    # No original text at all — still prefer Chinese for display consistency,
    # since this codebase's UI is Chinese-first.
    if not original_text:
        return zh
    return target


def normalize_search_target(raw: str) -> str:
    if not raw:
        return ''
    text = raw.strip()
    if not text:
        return ''

    for prefix in _PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix):
            text = text[len(prefix):]
            break

    for suffix in _SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break

    while text and text[-1] in _TRAILING_STOP_CHARS:
        text = text[:-1]

    text = text.strip()
    # Single-character residuals (e.g. '我' from '我的') are treated as noise:
    # legitimate object names are ≥2 chars in Chinese; this aligns with the
    # `len(e) <= 1` filters upstream.
    if len(text) <= 1:
        return ''
    return text
