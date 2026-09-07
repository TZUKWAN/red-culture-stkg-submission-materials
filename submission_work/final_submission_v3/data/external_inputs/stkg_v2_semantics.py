"""Deterministic labeling and fusion rules for the STKG V2 semantic layer."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable


SPECIALIZED_TYPES = {
    "CreativeWork", "Document", "Artifact", "CulturalSite", "Spirit", "ValueFacet"
}

TYPE_PARENT = {
    "AdministrativeRegion": "Place",
    "BasinSection": "Place",
    "CulturalSite": "Place",
    "Organization": "SocialGroup",
    "Institution": "Organization",
    "Spirit": "Concept",
    "ValueFacet": "Concept",
    "Position": "Concept",
    "EvolutionStage": "TimePeriod",
}

TYPE_FAMILY = {
    "Person": "Agent",
    "SocialGroup": "CollectiveAgent",
    "Organization": "CollectiveAgent",
    "Institution": "CollectiveAgent",
    "Event": "Event",
    "Place": "SpatialEntity",
    "AdministrativeRegion": "SpatialEntity",
    "BasinSection": "SpatialEntity",
    "CulturalSite": "SpatialEntity",
    "TimePeriod": "TemporalEntity",
    "EvolutionStage": "TemporalEntity",
    "Document": "InformationObject",
    "CreativeWork": "InformationObject",
    "Artifact": "PhysicalObject",
    "Spirit": "AbstractConcept",
    "ValueFacet": "AbstractConcept",
    "Position": "AbstractConcept",
    "Concept": "AbstractConcept",
}

V2_ORGANIZATION_SUFFIXES = (
    "先锋队", "游击队", "工作队", "宣传队", "民兵队", "武工队", "救国会", "抗敌会",
    "互济会", "农会", "工会", "农协", "学联", "青年团", "儿童团",
    "党委", "支部", "党支部", "党组织", "政府", "军团", "军区", "纵队", "支队",
    "部队", "委员会", "委会", "省委", "市委", "县委", "特委", "工委", "协会",
    "学会", "学生会", "自治会", "参议会", "办事处", "指挥部", "集团", "代表团",
    "书记处", "城工部", "报社", "出版社", "营业部", "分处", "书报部", "行动队",
    "军分区", "军委", "道委", "地委", "区委", "团地委", "分局", "剧团", "办公室",
    "纠察队", "政训处", "指导处", "行营", "工作组",
)

V2_ROLE_SUFFIXES = ("党员", "书记", "领导", "干部", "群众", "工人", "学生", "战士", "代表")
V2_ACTION_PREFIXES = (
    "建立", "成立", "组建", "创建", "发展", "恢复", "改组", "撤销", "解散", "发动",
    "参加", "加入", "领导", "组织", "创建于", "建立于", "修建", "建设", "重建",
    "参观", "保护", "迁建", "创办", "开办", "兴办", "筹办", "创立", "打入",
    "选举", "任命", "推选", "接管", "围攻",
)
V2_ACTION_SUFFIXES = (
    "建立", "成立", "组建", "创建", "发展", "恢复", "改组", "撤销", "解散", "发动",
    "参加", "加入", "创建于", "建立于",
)
V2_DOCUMENT_SUFFIXES = (
    "医书", "教材", "手册", "信件", "日记", "读后感", "决议案", "文件包",
)
V2_DOCUMENT_SUFFIXES += (
    "日报", "报纸", "刊物", "杂志", "文集", "文件", "决议", "宣言", "报告", "回忆录",
    "大纲", "统计表", "纲领", "公报", "通告", "布告", "战史", "斗争史", "革命史",
    "救亡史", "史稿", "史料汇编",
)
V2_ADMIN_SUFFIXES = ("省", "市", "县", "区", "镇", "乡", "村", "地区", "根据地", "苏区")
V2_HISTORICAL_ADMIN_SUFFIXES = ("租界",)
V2_INSTITUTION_SUFFIXES = (
    "学校", "大学", "中学", "学院", "纪念馆", "博物馆", "讲习所", "粮站",
    "小学", "女中", "师范", "女师", "团校", "图书馆", "书店", "印字馆", "宾馆",
    "机械厂", "铁矿", "农讲所", "夜校",
)
V2_GENERIC_INSTITUTION_NAMES = frozenset({
    "学校", "小学", "中小学", "中学", "大学", "夜校", "书店", "图书馆", "报社",
    "师范", "女中", "博物馆", "纪念馆", "宾馆", "农讲所", "讲习所",
})
V2_FIXED_MEMORIAL_ARTIFACT_SUFFIXES = ("纪念碑", "纪念塔", "雕像", "墓碑")
V2_CULTURAL_SITE_SUFFIXES = (
    "旧址", "遗址", "故居", "陵园", "会址", "纪念地", "烈士墓", "墓园",
)
V2_POSITION_SUFFIXES = (
    "书记", "委员", "主席", "主任", "部长", "局长", "队长", "校长", "处长", "科长",
)
V2_STRICT_EVENT_SUFFIXES = (
    "起义", "会议", "战役", "会战", "暴动", "谈判", "事变", "长征", "战争", "围剿",
    "行动", "惨案", "罢工", "示威", "游行", "战斗", "大会", "全会", "会师", "事件",
)
V2_STRICT_PLACE_DESCRIPTOR_SUFFIXES = (
    "解放区", "革命根据地", "根据地", "苏区", "核心区域", "战斗区域", "活动区域",
    "路线", "途经地", "途经地点", "发生地", "举办地", "作战地点", "牺牲地",
    "重要起点", "山坡", "交界处", "一带", "寨",
)
V2_GENERIC_EVENT_CONCEPTS = {
    "武装斗争", "阶级斗争", "革命斗争", "政治斗争", "游击战争", "群众运动", "土地改革",
    "战略会师",
}
V2_KNOWN_RIVERS = {
    "长江", "金沙江", "乌江", "湘江", "赣江", "嘉陵江", "岷江", "雅砻江", "大渡河", "赤水河",
}
V2_NUMBERED_UNIT_RE = re.compile(
    r"第?[一二三四五六七八九十百〇零0-9]+(?:大队|中队|小队)"
)
V2_FORMATION_EVENT_RE = re.compile(
    r".{3,}(?:第[一二三四五六七八九十百〇零0-9]+次|首次|重新)?成立"
)

RELATION_ROLES = {
    "participated_in": ("participant", "event"),
    "led": ("leader", "led_subject"),
    "organized": ("organizer", "organized_subject"),
    "commanded": ("commander", "commanded_subject"),
    "carried_out": ("executor", "event"),
    "occurred_at": ("event", "occurrence_place"),
    "occurred_during": ("event", "occurrence_time"),
    "member_of": ("member", "organization"),
    "held_position_in": ("office_holder", "institution"),
    "worked_at": ("worker", "workplace"),
    "studied_at": ("student", "educational_place"),
    "authored": ("creator", "created_work"),
    "edited": ("editor", "edited_work"),
    "created": ("creator", "created_subject"),
    "created_at": ("created_subject", "creation_place"),
    "created_during": ("created_subject", "creation_time"),
    "published_by": ("published_work", "publisher"),
    "commemorates": ("memorial_carrier", "commemorated_subject"),
    "disseminates": ("transmission_carrier", "transmitted_semantics"),
    "depicts": ("creative_work", "depicted_subject"),
    "documents": ("document", "documented_subject"),
    "mentioned_in": ("mentioned_subject", "source_document"),
    "documented_in": ("documented_semantics", "source_document"),
    "part_of": ("component", "parent"),
    "active_at": ("active_actor", "activity_place"),
    "active_during": ("active_actor", "activity_time"),
    "stationed_at": ("stationed_actor", "station_place"),
    "fought_at": ("combatant", "combat_place"),
    "born_at": ("person", "birth_place"),
    "born_during": ("person", "birth_time"),
    "died_at": ("person", "death_place"),
    "died_during": ("person", "death_time"),
    "arrested_at": ("person", "arrest_place"),
    "imprisoned_at": ("person", "imprisonment_place"),
}

OCCURRENCE_PREDICATES = {"occurred_at", "occurred_during"}
BIOGRAPHICAL_PREDICATES = {
    "born_at", "born_during", "died_at", "died_during", "arrested_at", "imprisoned_at"
}
CREATION_PREDICATES = {"authored", "edited", "created_at", "created_during", "published_by", "adapted_from"}
COMMEMORATION_PREDICATES = {"commemorates", "disseminates", "depicts"}
SOURCE_DOCUMENT_PREDICATES = {"mentioned_in", "documents", "documented_in"}

RAW_EVENT_TIME_CUES = ("发生时间", "事件时间", "时间-事件", "事件-时间")
RAW_BIO_TIME_CUES = ("出生时间", "生于", "牺牲时间", "逝世时间", "遇害时间", "被捕时间")
RAW_CREATION_TIME_CUES = ("创作时间", "出版时间", "首映时间", "发行时间")
RAW_MEMORY_TIME_CUES = ("纪念时间", "改编时间", "展陈时间")

RAW_EVENT_PLACE_CUES = ("发生于", "发生地", "事件地点", "事件-地点", "事件发生地点", "举办地")
RAW_BIO_PLACE_CUES = ("出生地", "牺牲于", "遇害地点", "被捕于", "就义地")
RAW_CREATION_PLACE_CUES = ("创作地", "出版地", "首映地")
RAW_MEMORY_PLACE_CUES = ("纪念地", "展陈地", "传播地")


@dataclass(frozen=True)
class EntityFusion:
    final_type: str | None
    status: str
    confidence: float | None
    risk_tier: str
    decision_sources: tuple[str, ...]
    risk_flags: tuple[str, ...]


@dataclass(frozen=True)
class ScopeLabel:
    role: str
    owner_id: str | None
    confidence: float
    risk_tier: str
    rationale: str


def strict_v2_entity_type_hint(name: str, source_type: str = "") -> str:
    """Return structure-based V2 hints; substring-only matches intentionally abstain."""
    text = str(name).strip()
    if not text:
        return ""
    if text.endswith("精神") and not re.search(r"(?:与传达|宣传|学习|贯彻).+精神$", text):
        return "Spirit"
    if re.search(r"[/／,，;；:：、]", text):
        return ""
    if (
        source_type not in {"Place", "AdministrativeRegion", "CulturalSite"}
        and V2_NUMBERED_UNIT_RE.fullmatch(text)
    ):
        return "Organization"
    if not text.startswith("成立") and V2_FORMATION_EVENT_RE.fullmatch(text):
        return "Event"
    if text.startswith(V2_ACTION_PREFIXES) or text.endswith(V2_ACTION_SUFFIXES):
        return ""
    if (
        re.search(
            r"(?:^办.*(?:小学|中学|夜校|学校)$|打入|创立|创办|开办|兴办|筹办|参加|慰问|(?:北上)?联系)",
            text,
        )
        and text.endswith(V2_ORGANIZATION_SUFFIXES + V2_INSTITUTION_SUFFIXES)
    ):
        return ""
    if text.endswith(V2_POSITION_SUFFIXES) or text.endswith(V2_ROLE_SUFFIXES):
        return "Position" if text.endswith(V2_POSITION_SUFFIXES) else ""
    military = re.fullmatch(
        r"(?:第?[一二三四五六七八九十百〇零0-9]+|红[一二三四五六七八九十百〇零0-9]+|新四|八路|解放|方面|纵队|支队|独立|游击|工农|(?:中国)?人民).*(?:军|师|团|营|连|部)",
        text,
    )
    named_corps = re.fullmatch(r"(?:.{1,8}(?:护|卫|救|工|农|青|儿童|少年)|还乡)团", text)
    if text.endswith(V2_ORGANIZATION_SUFFIXES) or military or named_corps:
        return "Organization"
    if text in {"旧址", "遗址", "故居", "陵园", "会址", "纪念地", "烈士墓", "墓园"}:
        return ""
    if text.endswith(V2_CULTURAL_SITE_SUFFIXES):
        return "CulturalSite"
    if text in V2_GENERIC_INSTITUTION_NAMES:
        return ""
    if text.endswith(V2_INSTITUTION_SUFFIXES):
        return "Institution"
    if re.search(
        r"(?:修建|修筑|建立|建造|重建).*(?:纪念碑|纪念塔|雕像|墓碑)$", text
    ):
        return "Event"
    if text.endswith(V2_FIXED_MEMORIAL_ARTIFACT_SUFFIXES):
        return "Artifact"
    if text.endswith("文件包"):
        return "Artifact"
    if re.search(r"(?:传达|听取|讨论|审议).*(?:报告|文件|决议)$", text):
        return ""
    if (
        re.search(
            r"(?:编纂|撰写|出版|学习|印刷|发行|阅读|宣传|制定|颁布|发布|起草|张贴|传递|珍藏)",
            text,
        )
        or (not text.startswith("《") and re.search(r"[及与]", text))
    ) and text.endswith(V2_DOCUMENT_SUFFIXES):
        return ""
    if text.endswith(V2_DOCUMENT_SUFFIXES):
        return "Document"
    if re.search(r"(?:话|忆|颂|歌|赞|看|写).*(?:长征|战争|战斗|起义|会师)$", text):
        return ""
    if text in {"过草地"}:
        return "Event"
    if source_type == "Place" and text.endswith(V2_STRICT_PLACE_DESCRIPTOR_SUFFIXES):
        return "Place"
    if text not in V2_GENERIC_EVENT_CONCEPTS and text.endswith(V2_STRICT_EVENT_SUFFIXES):
        return "Event"
    if source_type == "AdministrativeRegion" and text.endswith(V2_ADMIN_SUFFIXES):
        return "AdministrativeRegion"
    if re.search(r"(?:收回|收复|接管|撤销).*租界$", text):
        return "Event"
    if text.endswith(V2_HISTORICAL_ADMIN_SUFFIXES):
        return "AdministrativeRegion"
    if text in V2_KNOWN_RIVERS:
        return "Place"
    if text.endswith(V2_ADMIN_SUFFIXES):
        return "Place"
    if source_type == "Place" and len(text) >= 3 and text.endswith(("铁路", "公路", "大道", "街")):
        return "Place"
    if source_type == "Place" and text in {"红军路"}:
        return "Place"
    return ""


def spatial_model_contraindication(name: str, final_type: str) -> str:
    """Return a reason when a model's spatial type conflicts with name structure."""
    text = str(name or "").strip()
    if not text:
        return ""
    if final_type not in {"Place", "AdministrativeRegion", "CulturalSite"}:
        return ""
    hint = strict_v2_entity_type_hint(text, "Place")
    if hint and hint not in {"Place", "AdministrativeRegion", "CulturalSite"}:
        return "strict_nonspatial_name_conflicts_with_spatial_type"
    if final_type == "Place" and text.endswith("调查"):
        return "action_nominalization_cannot_be_accepted_as_place"
    if final_type == "AdministrativeRegion" and re.search(r"[、,，;；/／]", text):
        return "composite_place_cannot_be_single_administrative_region"
    if (
        final_type == "AdministrativeRegion"
        and strict_v2_entity_type_hint(text, "Place") != "AdministrativeRegion"
    ):
        return "administrative_region_requires_explicit_admin_structure"
    return ""


GENERIC_SOCIAL_GROUP_NAMES = frozenset({
    "群众", "人民群众", "农民群众", "工人群众", "干部群众",
    "民兵", "敌军", "敌人", "土匪", "匪特", "战士", "士兵", "红军战士",
})


def entity_model_contraindication(
    name: str,
    source_type: str,
    final_type: str,
    cluster_source_types: Iterable[str] = (),
) -> str:
    """Reject high-confidence model labels that contradict strict entity semantics."""
    text = str(name or "").strip()
    if not text or final_type not in TYPE_FAMILY:
        return ""
    spatial = spatial_model_contraindication(text, final_type)
    if spatial:
        return spatial

    strict_hint = strict_v2_entity_type_hint(text, source_type)
    if strict_hint and semantic_family(strict_hint) != semantic_family(final_type):
        return "strict_name_type_family_conflict"
    if (
        strict_hint
        and strict_hint != final_type
        and final_type in type_facets(strict_hint)
    ):
        return "strict_name_subtype_cannot_be_downgraded"

    exact_allowed_types = {
        "三大纪律八项注意": {"Concept", "Document", "CreativeWork"},
        "苏维埃": {"Concept", "Organization", "Institution"},
        "群众力量": {"Concept", "Spirit", "ValueFacet"},
    }
    if text in exact_allowed_types and final_type not in exact_allowed_types[text]:
        return "known_name_semantic_family_conflict"
    if text in {"电台"}:
        return "polysemous_bare_name_requires_scoped_split"
    
    if text in GENERIC_SOCIAL_GROUP_NAMES and final_type in {"Person", "Organization"}:
        return "generic_collective_requires_social_group_or_concept"
    if text.endswith(V2_ROLE_SUFFIXES) and final_type == "Person":
        return "generic_role_cannot_be_concrete_person"
    if final_type == "Artifact" and re.match(r"^(?:缴获|查获|没收|收缴|征集)", text):
        return "action_result_phrase_cannot_be_artifact"

    source_types = {str(value) for value in cluster_source_types}
    person_like = bool(re.fullmatch(r"[\u4e00-\u9fff]{2,4}", text))
    event_hint = strict_v2_entity_type_hint(text, "Event") == "Event"
    if (
        final_type == "Event"
        and "Person" in source_types
        and person_like
        and not event_hint
    ):
        return "person_name_collision_cannot_auto_confirm_event"
    if (
        final_type == "SocialGroup"
        and "Person" in source_types
        and person_like
        and not re.search(
            r"(?:群众|群体|工人|农民|中农|贫农|学生|妇女|壮士|战士|民兵|队员|军|队|团|会)$",
            text,
        )
    ):
        return "person_name_collision_cannot_auto_confirm_social_group"
    return ""


def entity_context_contraindication(
    name: str,
    source_type: str,
    final_type: str,
    contexts: Iterable[dict] = (),
) -> str:
    """Reject model types contradicted by controlled relation endpoint roles."""
    del name
    normalized = [dict(item) for item in contexts]
    subject_predicates = {
        str(item.get("predicate") or "")
        for item in normalized
        if str(item.get("endpoint_role") or "") == "subject"
    }
    object_predicates = {
        str(item.get("predicate") or "")
        for item in normalized
        if str(item.get("endpoint_role") or "") == "object"
    }
    spatial_object_predicates = {
        "occurred_at", "active_at", "stationed_at", "fought_at", "born_at", "died_at",
        "arrested_at", "imprisoned_at",
    }
    raw_spatial_object_predicates = {
        "raw:active_at", "raw:stationed_at", "raw:fought_at", "raw:born_at", "raw:died_at",
        "raw:arrested_at", "raw:imprisoned_at", "raw:发生地", "raw:事件发生地",
        "raw:发生地点", "raw:行动地点", "raw:被俘地点", "raw:转移路径",
    }
    raw_spatial_object_hits = sum(
        1
        for item in normalized
        if str(item.get("endpoint_role") or "") == "object"
        and str(item.get("predicate") or "") in raw_spatial_object_predicates
    )
    actor_subject_predicates = {
        "participated_in", "led", "organized", "commanded", "carried_out",
        "member_of", "held_position_in", "worked_at", "studied_at", "active_at",
        "stationed_at", "fought_at", "born_at", "died_at", "arrested_at",
        "imprisoned_at",
    }
    if (
        final_type in {"Place", "AdministrativeRegion", "CulturalSite"}
        and not object_predicates.intersection(spatial_object_predicates)
        and raw_spatial_object_hits < 2
        and subject_predicates & actor_subject_predicates
    ):
        return "controlled_relation_domain_conflicts_with_spatial_type"
    if (
        source_type == "Person"
        and final_type in {"CreativeWork", "Document"}
        and "depicts" in object_predicates
    ):
        return "depicted_person_cannot_be_retyped_as_information_object"
    return ""


def refine_lexical_hint(name: str, source_type: str, base_hint: str) -> str:
    """Use only strict V2 hints; base_hint is retained for API compatibility."""
    del base_hint
    return strict_v2_entity_type_hint(name, source_type)


def unique_endpoint(types_and_ids: Iterable[tuple[str, str]], accepted_types: set[str]) -> str | None:
    matches = [entity_id for entity_type, entity_id in types_and_ids if entity_type in accepted_types]
    return matches[0] if len(set(matches)) == 1 else None


def semantic_family(entity_type: str) -> str:
    return TYPE_FAMILY[entity_type]


def type_facets(entity_type: str) -> tuple[str, ...]:
    facets = [entity_type]
    current = entity_type
    while current in TYPE_PARENT:
        current = TYPE_PARENT[current]
        facets.append(current)
    facets.append(semantic_family(entity_type))
    return tuple(dict.fromkeys(facets))


def preserve_specialized_source_in_name_collision(
    source_type: str, lexical_hint: str, schema_votes: Counter[str]
) -> bool:
    if source_type not in TYPE_PARENT or lexical_hint:
        return False
    if not schema_votes:
        return True
    ordered = schema_votes.most_common()
    top_schema, top_count = ordered[0]
    second_count = ordered[1][1] if len(ordered) > 1 else 0
    schema_decisive = top_count >= 2 and top_count - second_count >= 2
    return not schema_decisive or top_schema in {source_type, TYPE_PARENT[source_type]}


def fuse_entity_type(
    source_type: str,
    lexical_hint: str,
    schema_votes: Counter[str],
    cross_type_name: bool,
) -> EntityFusion:
    flags: list[str] = []
    sources = ["source_type_prior"]
    top_schema = ""
    top_count = 0
    second_count = 0
    if schema_votes:
        ordered = schema_votes.most_common()
        top_schema, top_count = ordered[0]
        second_count = ordered[1][1] if len(ordered) > 1 else 0
    schema_decisive = bool(top_schema and top_count >= 2 and top_count - second_count >= 2)
    if lexical_hint:
        sources.append("strong_lexical_hint")
        if lexical_hint != source_type:
            flags.append("lexical_source_type_conflict")
    if schema_votes:
        sources.append("controlled_schema_votes")
        if schema_decisive and top_schema != source_type:
            flags.append("schema_source_type_conflict")
    if cross_type_name:
        flags.append("same_name_multiple_source_types")

    if cross_type_name:
        if preserve_specialized_source_in_name_collision(source_type, lexical_hint, schema_votes):
            sources.append("compatible_subtype_preservation")
            flags.append("compatible_subtype_name_collision")
            return EntityFusion(source_type, "auto_accepted", 0.98, "B", tuple(sources), tuple(flags))
        if schema_decisive and (not lexical_hint or lexical_hint == top_schema):
            return EntityFusion(top_schema, "auto_accepted", 0.97, "B", tuple(sources), tuple(flags))
        return EntityFusion(None, "model_review", None, "C", tuple(sources), tuple(flags))

    if lexical_hint and lexical_hint != source_type:
        if source_type in SPECIALIZED_TYPES and lexical_hint == "Event" and not schema_decisive:
            flags.append("specialized_type_requires_context")
            return EntityFusion(None, "model_review", None, "C", tuple(sources), tuple(flags))
        if schema_decisive and top_schema not in {lexical_hint, source_type}:
            flags.append("lexical_schema_conflict")
            return EntityFusion(None, "model_review", None, "C", tuple(sources), tuple(flags))
        return EntityFusion(lexical_hint, "auto_accepted", 0.98, "B", tuple(sources), tuple(flags))

    if schema_decisive and top_schema != source_type:
        return EntityFusion(top_schema, "auto_accepted", 0.96, "B", tuple(sources), tuple(flags))
    if lexical_hint == source_type or (schema_decisive and top_schema == source_type):
        return EntityFusion(source_type, "auto_accepted", 0.98, "A", tuple(sources), tuple(flags))
    return EntityFusion(source_type, "auto_accepted", 0.92, "B", tuple(sources), tuple(flags))


def classify_time_scope(
    predicate: str,
    time_start: str | None,
    subject_id: str,
    subject_type: str,
    object_id: str,
    object_type: str,
) -> ScopeLabel:
    if not time_start:
        return ScopeLabel("unknown", None, 1.0, "A", "no_structured_time")
    endpoints = ((subject_type, subject_id), (object_type, object_id))
    raw_label = predicate[4:] if predicate.startswith("raw:") else ""
    if predicate in OCCURRENCE_PREDICATES:
        owner = unique_endpoint(endpoints, {"Event"})
        if owner:
            return ScopeLabel("event_occurrence", owner, 0.99, "A", "controlled_event_occurrence")
    if predicate in BIOGRAPHICAL_PREDICATES:
        owner = unique_endpoint(endpoints, {"Person"})
        return ScopeLabel("biographical", owner, 0.99 if owner else 0.8, "A" if owner else "C", "controlled_biographical")
    if predicate in CREATION_PREDICATES:
        owner = unique_endpoint(endpoints, {"CreativeWork", "Document", "Artifact"})
        if owner:
            return ScopeLabel("creation_or_publication", owner, 0.98, "A", "controlled_creation_or_publication")
    if predicate in COMMEMORATION_PREDICATES:
        owner = subject_id
        return ScopeLabel("commemoration_or_reception", owner, 0.97, "A", "controlled_commemoration_or_reception")
    if predicate in SOURCE_DOCUMENT_PREDICATES:
        owner = unique_endpoint(endpoints, {"Document"})
        return ScopeLabel("source_document_time", owner, 0.96 if owner else 0.8, "B" if owner else "C", "controlled_source_document")
    if raw_label:
        if any(cue in raw_label for cue in RAW_EVENT_TIME_CUES):
            owner = unique_endpoint(endpoints, {"Event"})
            if owner:
                return ScopeLabel("event_occurrence", owner, 0.85, "B", "raw_explicit_event_time")
        if any(cue in raw_label for cue in RAW_BIO_TIME_CUES):
            owner = unique_endpoint(endpoints, {"Person"})
            if owner:
                return ScopeLabel("biographical", owner, 0.85, "B", "raw_explicit_biographical_time")
        if any(cue in raw_label for cue in RAW_CREATION_TIME_CUES):
            owner = unique_endpoint(endpoints, {"CreativeWork", "Document", "Artifact"})
            if owner:
                return ScopeLabel("creation_or_publication", owner, 0.84, "B", "raw_explicit_creation_time")
        if any(cue in raw_label for cue in RAW_MEMORY_TIME_CUES):
            return ScopeLabel("commemoration_or_reception", subject_id, 0.84, "B", "raw_explicit_memory_time")
        return ScopeLabel("context_time", None, 0.99, "B", "raw_or_unscoped_time_excluded_from_event_time")
    return ScopeLabel("relation_validity", None, 0.96, "A", "controlled_relation_validity")


def classify_space_scope(
    predicate: str,
    canonical_place_id: str | None,
    subject_id: str,
    subject_type: str,
    object_id: str,
    object_type: str,
) -> ScopeLabel:
    if not canonical_place_id:
        return ScopeLabel("unknown", None, 1.0, "A", "no_canonical_place")
    endpoints = ((subject_type, subject_id), (object_type, object_id))
    raw_label = predicate[4:] if predicate.startswith("raw:") else ""
    if predicate == "occurred_at":
        owner = unique_endpoint(endpoints, {"Event"})
        if owner:
            return ScopeLabel("event_location", owner, 0.99, "A", "controlled_event_location")
    if predicate in BIOGRAPHICAL_PREDICATES:
        owner = unique_endpoint(endpoints, {"Person"})
        return ScopeLabel("biographical_location", owner, 0.99 if owner else 0.8, "A" if owner else "C", "controlled_biographical_location")
    if predicate == "created_at":
        owner = unique_endpoint(endpoints, {"CreativeWork", "Document", "Artifact"})
        if owner:
            return ScopeLabel("creation_or_publication_location", owner, 0.98, "A", "controlled_creation_location")
    if predicate in COMMEMORATION_PREDICATES:
        return ScopeLabel("commemoration_or_reception_location", subject_id, 0.9, "B", "controlled_memory_context_location")
    if raw_label:
        if any(cue in raw_label for cue in RAW_EVENT_PLACE_CUES):
            owner = unique_endpoint(endpoints, {"Event"})
            if owner:
                return ScopeLabel("event_location", owner, 0.86, "B", "raw_explicit_event_location")
        if any(cue in raw_label for cue in RAW_BIO_PLACE_CUES):
            owner = unique_endpoint(endpoints, {"Person"})
            if owner:
                return ScopeLabel("biographical_location", owner, 0.85, "B", "raw_explicit_biographical_location")
        if any(cue in raw_label for cue in RAW_CREATION_PLACE_CUES):
            owner = unique_endpoint(endpoints, {"CreativeWork", "Document", "Artifact"})
            if owner:
                return ScopeLabel("creation_or_publication_location", owner, 0.84, "B", "raw_explicit_creation_location")
        if any(cue in raw_label for cue in RAW_MEMORY_PLACE_CUES):
            return ScopeLabel("commemoration_or_reception_location", subject_id, 0.84, "B", "raw_explicit_memory_location")
        return ScopeLabel("context_location", None, 0.99, "B", "raw_or_unscoped_place_excluded_from_event_location")
    return ScopeLabel("relation_location", None, 0.95, "A", "controlled_relation_location")


def relation_roles(predicate: str) -> tuple[str, str, str, str]:
    if predicate.startswith("raw:"):
        return "source_subject", "source_object", "raw_context", "unknown"
    subject_role, object_role = RELATION_ROLES.get(predicate, ("semantic_subject", "semantic_object"))
    return subject_role, object_role, predicate, "canonical"
