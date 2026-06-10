from __future__ import annotations

from .turn_schema import ParsedTurn, TurnConstraints


SAFETY_ANSWER_TERMS = (
    "过敏",
    "忌口",
    "低糖",
    "低盐",
    "低脂",
    "无糖",
    "敏感肌",
    "干皮",
    "油皮",
    "混合皮",
    "酒精",
    "香精",
    "酸类",
    "脚宽",
    "足弓",
    "膝盖",
    "磨脚",
    "老人",
    "小孩",
    "孩子",
    "宝宝",
    "孕妇",
    "长时间佩戴",
    "入耳不适",
    "肠胃敏感",
)

FOOD_TERMS = ("食品饮料", "坚果/零食", "零食", "牛奶", "酸奶", "咖啡", "酱油", "生抽", "老抽")
SKINCARE_TERMS = ("防晒", "面霜", "面膜", "精华", "洁面", "护肤")
SPORT_TERMS = ("篮球鞋", "跑步鞋", "运动鞋", "鞋")
DIGITAL_WEARABLE_TERMS = ("耳机", "真无线耳机", "蓝牙耳机", "平板")
PET_TERMS = ("宠物用品", "猫咪用品", "宠物", "猫", "狗")


def build_safety_clarification_question(parsed: ParsedTurn, constraints: TurnConstraints) -> str | None:
    if parsed.needs_clarification:
        return None
    if parsed.intent_type not in {"product_search", "filter_refinement", "unknown"}:
        return None
    raw = parsed.raw_message or ""

    haystack = _constraint_text(raw, constraints)
    product_haystack = _product_text(raw, constraints)
    if _matches_any(haystack, FOOD_TERMS) and _has_vague_allergy(raw):
        return "你提到有过敏风险。为了避免推荐到不适合的食品，请问具体对什么过敏？比如坚果、乳制品、鸡蛋、小麦或海鲜。"
    if _has_safety_answer(raw):
        return None

    if _matches_any(haystack, FOOD_TERMS) and _is_broad_or_sensitive(raw, haystack):
        return "为了避免推荐不适合的食品，请问有没有过敏或忌口？是自己吃，还是给老人、小孩或孕妇？"
    if _matches_any(product_haystack, SKINCARE_TERMS) and _is_broad_or_sensitive(raw, haystack):
        return "为了避开刺激成分，请问你的肤质是干皮、油皮、敏感肌还是混合皮？是否需要避开酒精、香精或酸类？"
    if _matches_any(haystack, SPORT_TERMS) and _is_broad_or_sensitive(raw, haystack):
        return "为了减少磨脚或运动不适，请问主要用于跑步、篮球、通勤还是健身？有没有脚宽、足弓、膝盖不适或容易磨脚的情况？"
    if _matches_any(haystack, DIGITAL_WEARABLE_TERMS) and _has_wearable_safety_risk(raw, haystack):
        return "为了避免佩戴不适，请问是长时间佩戴或给孩子使用吗？更在意降噪、续航、护眼、重量还是通话？"
    if _matches_any(haystack, PET_TERMS) and _is_broad_or_sensitive(raw, haystack):
        return "为了避免宠物不适，请问是猫还是狗？年龄和体重大概多少？有没有过敏、肠胃敏感或医生建议避开的成分？"
    return None


def _constraint_text(raw: str, constraints: TurnConstraints) -> str:
    parts = [
        raw,
        *constraints.categories,
        *constraints.subcategories,
        *constraints.required_terms,
        *constraints.attributes_include,
        *constraints.scene_terms,
    ]
    return " ".join(part for part in parts if part)


def _product_text(raw: str, constraints: TurnConstraints) -> str:
    parts = [
        raw,
        *constraints.subcategories,
        *constraints.required_terms,
        *constraints.attributes_include,
        *constraints.scene_terms,
    ]
    return " ".join(part for part in parts if part)


def _has_safety_answer(raw: str) -> bool:
    return any(term in raw for term in SAFETY_ANSWER_TERMS)


def _has_vague_allergy(raw: str) -> bool:
    if "过敏" not in raw:
        return False
    vague_terms = ("某些", "有些", "东西", "食物", "不确定", "不知道", "容易", "有点", "过敏体质")
    specific_terms = ("坚果", "花生", "乳制品", "牛奶", "乳糖", "鸡蛋", "蛋", "小麦", "麸质", "海鲜", "虾", "蟹", "鱼", "大豆", "黄豆")
    return any(term in raw for term in vague_terms) or not any(term in raw for term in specific_terms)


def _matches_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _is_broad_or_sensitive(raw: str, haystack: str) -> bool:
    broad_terms = ("推荐", "买", "想要", "有没有", "哪些", "清单", "一套", "适合")
    sensitive_audience = ("老人", "小孩", "孩子", "宝宝", "孕妇", "宠物", "猫", "狗")
    return any(term in raw for term in broad_terms) or any(term in haystack for term in sensitive_audience)


def _has_wearable_safety_risk(raw: str, haystack: str) -> bool:
    sensitive_audience = ("老人", "小孩", "孩子", "宝宝", "孕妇")
    wearable_risk = ("长时间佩戴", "久戴", "入耳不适", "耳朵疼", "耳压", "护眼", "重量轻")
    return any(term in haystack for term in sensitive_audience) or any(term in raw for term in wearable_risk)
