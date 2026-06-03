from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .rag import extract_max_price


CATEGORY_TERMS = {
    "手机": ["手机", "智能手机", "iphone"],
    "耳机": ["耳机", "蓝牙", "无线耳机", "降噪"],
    "电脑": ["电脑", "笔记本", "平板", "办公", "游戏本"],
    "家居": ["家居", "床品", "家具", "杯具", "窗帘", "灯具"],
    "宠物": ["宠物", "猫", "狗", "猫砂", "牵引"],
    "办公文具": ["办公", "文具", "白板", "马克笔", "文件", "打印"],
    "旅行户外": ["旅行", "户外", "背包", "行李箱", "登机箱", "徒步"],
    "美妆护肤": ["护肤", "洁面", "洗面奶", "精华", "口红", "防晒"],
    "服饰运动": ["外套", "鞋", "运动", "衣", "跑步"],
    "食品饮料": ["食品", "饮料", "零食", "咖啡", "茶"],
}

FEATURE_TERMS = {
    "降噪": ["降噪", "主动降噪", "通话清晰"],
    "续航": ["续航", "电池", "持久"],
    "快充": ["快充", "充电快"],
    "拍照": ["拍照", "影像", "摄像", "夜景"],
    "护眼": ["护眼", "低蓝光"],
    "轻薄": ["轻薄", "便携"],
    "高刷": ["高刷", "刷新率"],
    "控油": ["控油", "油皮", "清爽"],
    "防滑": ["防滑", "稳定"],
    "防水": ["防水", "防雨"],
}

SCENARIO_TERMS = {
    "学生党": ["学生党", "学生", "上学"],
    "办公": ["办公", "会议", "工作", "通勤"],
    "游戏": ["游戏", "电竞"],
    "送礼": ["送礼", "礼物", "女朋友", "男朋友"],
    "运动": ["运动", "跑步", "训练"],
    "旅行": ["旅行", "出差", "户外", "徒步"],
    "宠物家庭": ["养猫", "养狗", "宠物"],
}

COMPARISON_TERMS = ["更好", "更适合", "相似", "类似", "对比", "哪个", "替代", "同款", "续航更好", "更便宜"]
RELATION_TERMS = ["兼容", "适合", "同类", "替代", "相似", "搭配", "人群"]
BRAND_TERMS = ["apple", "苹果", "华为", "huawei", "小米", "redmi", "亚马逊", "amazon", "sony", "索尼", "umi", "eono"]


@dataclass
class ParsedConstraints:
    budget_max: float | None = None
    categories: list[str] = field(default_factory=list)
    brands: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    comparison: bool = False
    relationship: bool = False
    image_query: bool = False
    mode: str = "ai_guide"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryRoute:
    strategy: str
    complexity: int
    parsed_constraints: ParsedConstraints
    reason: str

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "complexity": self.complexity,
            "reason": self.reason,
            "parsed_constraints": self.parsed_constraints.to_dict(),
        }


class IntelligentQueryRouter:
    def route(self, query: str, image_hint: str | None = None, mode: str = "ai_guide") -> QueryRoute:
        normalized = f"{query or ''} {image_hint or ''}".strip().lower()
        parsed = ParsedConstraints(
            budget_max=extract_max_price(normalized),
            categories=self._find_terms(normalized, CATEGORY_TERMS),
            brands=self._find_brands(normalized),
            features=self._find_terms(normalized, FEATURE_TERMS),
            scenarios=self._find_terms(normalized, SCENARIO_TERMS),
            comparison=any(term in normalized for term in COMPARISON_TERMS),
            relationship=any(term in normalized for term in RELATION_TERMS),
            image_query=bool(image_hint),
            mode=mode,
        )
        complexity = 0
        if parsed.budget_max is not None:
            complexity += 1
        complexity += min(len(parsed.categories), 2)
        complexity += min(len(parsed.features), 3)
        complexity += min(len(parsed.scenarios), 2)
        if parsed.comparison:
            complexity += 2
        if parsed.relationship:
            complexity += 2
        if parsed.image_query:
            complexity += 1

        if mode == "user_search":
            return QueryRoute("hybrid", complexity, parsed, "用户检索模式优先使用结构化混合检索")
        if parsed.comparison or parsed.relationship:
            if complexity >= 5:
                return QueryRoute("graph", complexity, parsed, "关系、相似或对比意图较强，优先使用图谱推理")
            return QueryRoute("graph_hybrid", complexity, parsed, "存在关系约束，组合图谱与语义检索")
        if complexity >= 4:
            return QueryRoute("graph_hybrid", complexity, parsed, "多条件中等复杂查询，组合检索更稳妥")
        return QueryRoute("hybrid", complexity, parsed, "简单导购查询，使用混合检索")

    @staticmethod
    def _find_terms(text: str, groups: dict[str, list[str]]) -> list[str]:
        found: list[str] = []
        for label, terms in groups.items():
            if any(term.lower() in text for term in terms):
                found.append(label)
        return found

    @staticmethod
    def _find_brands(text: str) -> list[str]:
        return [brand for brand in BRAND_TERMS if brand in text]
