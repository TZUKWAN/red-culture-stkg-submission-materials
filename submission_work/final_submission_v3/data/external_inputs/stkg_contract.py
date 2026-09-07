"""Canonical schema contract shared by the STKG curation pipeline."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Iterable

from stkg_normalization import clean_text, normalize_time_fields


ENTITY_TYPES = {
    "Spirit",
    "ValueFacet",
    "Person",
    "SocialGroup",
    "Organization",
    "Event",
    "Place",
    "TimePeriod",
    "Document",
    "Artifact",
    "CreativeWork",
    "Institution",
    "AdministrativeRegion",
    "BasinSection",
    "EvolutionStage",
    "Position",
    "Concept",
}

CONTROLLED_RELATION_BLOCKLIST = {
    "关联", "相关", "关系", "need_review",
    "革命", "发展", "战争", "教育", "起义", "军事行动", "冲突",
    "目标", "对象", "内容", "结果", "原因", "背景", "意义", "作用",
    "方式", "范围", "地点", "区域", "主体", "客体", "人物", "事件",
    "组织", "物品", "时间", "关系类型",
    # Role, stage, target, and location labels that are not strictly equivalent
    # to the narrower controlled predicates proposed by the language model.
    "上下级", "上下级关系", "下辖", "主持", "主持者", "人物籍贯", "代表",
    "任务分配", "任务布置", "任务指派", "任职地", "任职地点", "任职地域", "任职地-人物",
    "作战对象", "作战目标", "军事行动-目标区域", "决策者", "决策者-事件", "决策机构",
    "动员", "办公地点", "依托", "依托关系", "依托地", "传播地点-内容", "决定", "决策",
    "决定根据地", "发布地", "地点归属", "开辟根据地区域", "被捕避难地", "被追捕地",
    "负责人-区域", "负责区域", "领导-区域", "领导-地点", "领导与地点", "领导区域", "领导地", "领导地点",
}


def normalized_raw_relation_label(value: object) -> str:
    return re.sub(r"^(?:raw|weak):", "", str(value or "").strip(), flags=re.I).strip()


def relation_label_blocks_controlled(value: object) -> bool:
    return normalized_raw_relation_label(value) in CONTROLLED_RELATION_BLOCKLIST


def relation_endpoint_types_preserved(
    original_subject_type: object,
    original_object_type: object,
    direction: object,
    canonical_subject_type: object,
    canonical_object_type: object,
) -> bool:
    source = normalize_type(original_subject_type)
    target = normalize_type(original_object_type)
    canonical_source = normalize_type(canonical_subject_type)
    canonical_target = normalize_type(canonical_object_type)
    if str(direction or "").strip().lower() == "swap":
        return canonical_source == target and canonical_target == source
    return canonical_source == source and canonical_target == target

TYPE_ALIASES = {
    "position": "Position",
    "role": "Position",
    "职务": "Position",
    "职位": "Position",
    "身份": "Position",
    "concept": "Concept",
    "思想概念": "Concept",
    "路线方针": "Concept",
    "政策主张": "Concept",
    "spirit": "Spirit",
    "红色精神": "Spirit",
    "精神": "Spirit",
    "革命精神": "Spirit",
    "valuefacet": "ValueFacet",
    "value_facet": "ValueFacet",
    "spiritfacet": "ValueFacet",
    "spirit_facet": "ValueFacet",
    "精神内涵": "ValueFacet",
    "精神特质": "ValueFacet",
    "精神维度": "ValueFacet",
    "person": "Person",
    "人物": "Person",
    "革命人物": "Person",
    "organization": "Organization",
    "组织": "Organization",
    "组织机构": "Organization",
    "机构": "Organization",
    "socialgroup": "SocialGroup",
    "social_group": "SocialGroup",
    "社会群体": "SocialGroup",
    "群体": "SocialGroup",
    "event": "Event",
    "事件": "Event",
    "事情": "Event",
    "历史事件": "Event",
    "革命事件": "Event",
    "place": "Place",
    "地点": "Place",
    "革命地点": "Place",
    "time": "TimePeriod",
    "timeperiod": "TimePeriod",
    "时间": "TimePeriod",
    "时期": "TimePeriod",
    "document": "Document",
    "文献": "Document",
    "历史文献": "Document",
    "党史文献": "Document",
    "artifact": "Artifact",
    "物品": "Artifact",
    "代表性物品": "Artifact",
    "creativework": "CreativeWork",
    "creative_work": "CreativeWork",
    "文艺作品": "CreativeWork",
    "红色文艺作品": "CreativeWork",
    "institution": "Institution",
    "纪念机构": "Institution",
    "纪念馆": "Institution",
    "旧址": "Institution",
    "administrativeregion": "AdministrativeRegion",
    "administrative_region": "AdministrativeRegion",
    "行政区": "AdministrativeRegion",
    "行政区划": "AdministrativeRegion",
    "basinsection": "BasinSection",
    "流域区段": "BasinSection",
    "evolutionstage": "EvolutionStage",
    "evolution_stage": "EvolutionStage",
    "演进阶段": "EvolutionStage",
}


@dataclass(frozen=True)
class RelationSpec:
    code: str
    label: str
    source_types: frozenset[str]
    target_types: frozenset[str]


def _types(*values: str) -> frozenset[str]:
    return frozenset(values)


RELATIONS = {
    "held_position": RelationSpec("held_position", "担任职务", _types("Person"), _types("Position")),
    "position_in": RelationSpec("position_in", "职务属于机构", _types("Position"), _types("Organization", "Institution")),
    "advocated": RelationSpec("advocated", "主张", _types("Person", "Organization"), _types("Concept")),
    "formulated": RelationSpec("formulated", "制定", _types("Person", "Organization"), _types("Concept")),
    "implemented": RelationSpec("implemented", "执行方针", _types("Person", "Organization"), _types("Concept")),
    "criticized": RelationSpec("criticized", "批评", _types("Person", "Organization"), _types("Concept", "Person", "Organization")),
    "used_artifact": RelationSpec("used_artifact", "使用物品", _types("Person", "Organization"), _types("Artifact")),
    "prototype_for": RelationSpec("prototype_for", "原型人物", _types("Person", "Event"), _types("CreativeWork")),
    "edited": RelationSpec("edited", "编辑审改", _types("Person", "Organization"), _types("Document", "CreativeWork")),
    "dispatched": RelationSpec("dispatched", "派遣", _types("Person", "Organization"), _types("Person", "Organization", "Event", "Place")),
    "carried_out": RelationSpec("carried_out", "执行", _types("Person", "Organization"), _types("Event")),
    "introduced": RelationSpec("introduced", "介绍", _types("Person"), _types("Person")),
    "colleague_of": RelationSpec("colleague_of", "同事", _types("Person"), _types("Person")),
    "recruited": RelationSpec("recruited", "发展吸收", _types("Person", "Organization"), _types("Person")),
    "captured": RelationSpec("captured", "攻占", _types("Person", "Organization"), _types("Place")),
    "imprisoned_at": RelationSpec("imprisoned_at", "关押于", _types("Person"), _types("Place", "Institution")),
    "reported_to": RelationSpec("reported_to", "汇报于", _types("Person", "Organization"), _types("Person", "Organization")),
    "governed": RelationSpec("governed", "管辖", _types("Person", "Organization", "Place"), _types("Place", "Organization")),
    "liberated": RelationSpec("liberated", "解放", _types("Person", "Organization", "Event"), _types("Place")),
    "appointed": RelationSpec("appointed", "任命", _types("Person", "Organization"), _types("Person")),
    "family_of": RelationSpec("family_of", "亲属", _types("Person"), _types("Person")),
    "spouse_of": RelationSpec("spouse_of", "配偶", _types("Person"), _types("Person")),
    "killed": RelationSpec("killed", "杀害", _types("Person", "Organization"), _types("Person")),
    "protected": RelationSpec("protected", "保护", _types("Person", "Organization"), _types("Person", "Organization", "Event")),
    "rescued": RelationSpec("rescued", "营救", _types("Person", "Organization"), _types("Person")),
    "escorted": RelationSpec("escorted", "护送", _types("Person", "Organization"), _types("Person")),
    "stationed_at": RelationSpec("stationed_at", "驻守于", _types("Person", "Organization"), _types("Place")),
    "has_value_facet": RelationSpec("has_value_facet", "价值关联", _types("Spirit"), _types("ValueFacet")),
    "originated_from_event": RelationSpec("originated_from_event", "孕育于", _types("Spirit", "ValueFacet"), _types("Event")),
    "embodied_in_event": RelationSpec("embodied_in_event", "体现于事件", _types("Spirit", "ValueFacet"), _types("Event")),
    "embodied_by_person": RelationSpec("embodied_by_person", "体现于人物", _types("Spirit", "ValueFacet"), _types("Person")),
    "embodied_by_organization": RelationSpec("embodied_by_organization", "体现于组织", _types("Spirit", "ValueFacet"), _types("Organization", "Institution")),
    "originated_at": RelationSpec("originated_at", "形成于地点", _types("Spirit", "ValueFacet"), _types("Place")),
    "disseminated_at": RelationSpec("disseminated_at", "传播于地点", _types("Spirit", "ValueFacet"), _types("Place", "Institution")),
    "documented_in": RelationSpec("documented_in", "记载于", _types("Spirit", "ValueFacet"), _types("Document")),
    "symbolized_by": RelationSpec("symbolized_by", "物化承载于", _types("Spirit", "ValueFacet"), _types("Artifact")),
    "represented_in": RelationSpec("represented_in", "表现于文艺作品", _types("Spirit", "ValueFacet"), _types("CreativeWork")),
    "formed_during": RelationSpec("formed_during", "形成于时间", _types("Spirit", "ValueFacet"), _types("TimePeriod")),
    "transmitted_by": RelationSpec("transmitted_by", "传承于", _types("Spirit", "ValueFacet"), _types("Organization", "Institution", "Document")),
    "inherited_from": RelationSpec("inherited_from", "继承发展", _types("Spirit"), _types("Spirit")),
    "participated_in": RelationSpec("participated_in", "参与", _types("Person", "Organization"), _types("Event")),
    "led": RelationSpec("led", "领导", _types("Person", "Organization"), _types("Event", "Organization")),
    "occurred_at": RelationSpec("occurred_at", "发生于地点", _types("Event"), _types("Place")),
    "occurred_during": RelationSpec("occurred_during", "发生于时间", _types("Event"), _types("TimePeriod")),
    "member_of": RelationSpec("member_of", "隶属于", _types("Person", "Organization"), _types("Organization")),
    "located_in": RelationSpec("located_in", "位于", _types("Place", "Organization", "Institution"), _types("Place", "AdministrativeRegion", "BasinSection")),
    "administratively_in": RelationSpec("administratively_in", "行政隶属", _types("Place"), _types("AdministrativeRegion", "Place")),
    "within_basin": RelationSpec("within_basin", "属于流域区段", _types("Place", "AdministrativeRegion"), _types("BasinSection")),
    "authored": RelationSpec("authored", "创作", _types("Person", "Organization"), _types("Document", "CreativeWork")),
    "created": RelationSpec("created", "创建", _types("Person", "Organization"), _types("Artifact", "CreativeWork", "Organization")),
    "active_at": RelationSpec("active_at", "活动于", _types("Person", "Organization"), _types("Place")),
    "active_during": RelationSpec("active_during", "活动于时间", _types("Person", "Organization"), _types("TimePeriod")),
    "used_in_event": RelationSpec("used_in_event", "用于事件", _types("Artifact"), _types("Event")),
    "preserved_at": RelationSpec("preserved_at", "保存于", _types("Artifact", "Document"), _types("Institution", "Place", "Organization")),
    "created_at": RelationSpec("created_at", "创作于地点", _types("Artifact", "CreativeWork", "Document"), _types("Place")),
    "created_during": RelationSpec("created_during", "创作于时间", _types("Artifact", "CreativeWork", "Document"), _types("TimePeriod")),
    "published_by": RelationSpec("published_by", "出版发行于", _types("Document", "CreativeWork"), _types("Organization")),
    "commemorates": RelationSpec("commemorates", "纪念", _types("Artifact", "Institution", "CreativeWork", "Document"), _types("Person", "Event", "Spirit")),
    "disseminates": RelationSpec("disseminates", "传播", _types("CreativeWork", "Document", "Institution", "Organization"), _types("Spirit", "ValueFacet")),
    "part_of": RelationSpec("part_of", "组成部分", _types("Event", "Document", "CreativeWork"), _types("Event", "Document", "CreativeWork")),
    "belongs_to_stage": RelationSpec("belongs_to_stage", "处于演进阶段", _types("Spirit", "Event", "CreativeWork", "Artifact"), _types("EvolutionStage")),
    "depicts": RelationSpec("depicts", "表现", _types("CreativeWork"), _types("Spirit", "ValueFacet", "Person", "Event", "Place")),
    "documents": RelationSpec("documents", "记载", _types("Document"), _types("Spirit", "ValueFacet", "Person", "Event", "Place", "Organization")),
    "mentioned_in": RelationSpec("mentioned_in", "关联文献", _types("Person", "Organization", "Event", "Place", "TimePeriod", "Artifact", "CreativeWork"), _types("Document")),
    "organized": RelationSpec("organized", "组织", _types("Person", "Organization"), _types("Event", "Organization")),
    "commanded": RelationSpec("commanded", "指挥", _types("Person", "Organization"), _types("Event", "Organization")),
    "guided": RelationSpec("guided", "指导", _types("Person", "Organization"), _types("Person", "Organization", "Event")),
    "held_position_in": RelationSpec("held_position_in", "任职于", _types("Person"), _types("Organization", "Institution")),
    "worked_at": RelationSpec("worked_at", "工作于", _types("Person"), _types("Organization", "Institution", "Place")),
    "studied_at": RelationSpec("studied_at", "学习于", _types("Person"), _types("Institution", "Place")),
    "traveled_to": RelationSpec("traveled_to", "前往", _types("Person", "Organization"), _types("Place")),
    "visited": RelationSpec("visited", "访问", _types("Person", "Organization"), _types("Place", "Organization", "Institution")),
    "met_with": RelationSpec("met_with", "会见", _types("Person", "Organization"), _types("Person", "Organization")),
    "collaborated_with": RelationSpec("collaborated_with", "合作", _types("Person", "Organization"), _types("Person", "Organization")),
    "contacted": RelationSpec("contacted", "联络", _types("Person", "Organization"), _types("Person", "Organization")),
    "supported": RelationSpec("supported", "支持", _types("Person", "Organization"), _types("Person", "Organization", "Event")),
    "opposed": RelationSpec("opposed", "反对", _types("Person", "Organization"), _types("Person", "Organization", "Event")),
    "trained": RelationSpec("trained", "培养", _types("Person", "Organization"), _types("Person")),
    "responsible_for": RelationSpec("responsible_for", "负责", _types("Person", "Organization"), _types("Organization", "Event", "Place")),
    "comrade_of": RelationSpec("comrade_of", "战友", _types("Person"), _types("Person")),
    "fought_at": RelationSpec("fought_at", "战斗于", _types("Person", "Organization"), _types("Place")),
    "arrested_at": RelationSpec("arrested_at", "被捕于", _types("Person"), _types("Place")),
    "born_at": RelationSpec("born_at", "出生于地点", _types("Person"), _types("Place")),
    "born_during": RelationSpec("born_during", "出生于时间", _types("Person"), _types("TimePeriod")),
    "died_at": RelationSpec("died_at", "牺牲逝世于地点", _types("Person"), _types("Place")),
    "died_during": RelationSpec("died_during", "牺牲逝世于时间", _types("Person"), _types("TimePeriod")),
    "influenced": RelationSpec("influenced", "影响", _types("Person", "Organization", "Event", "Spirit", "Document", "CreativeWork"), _types("Person", "Organization", "Event", "Spirit", "Place", "Document", "CreativeWork")),
    "adapted_from": RelationSpec("adapted_from", "改编自", _types("CreativeWork"), _types("CreativeWork", "Document")),
}


@dataclass(frozen=True)
class TaskSpec:
    dimension: str
    source_type: str
    target_type: str
    relation_codes: tuple[str, ...]
    label: str


_DIMENSION_TARGETS = {
    "event": ("Event", ("originated_from_event", "embodied_in_event"), "事件"),
    "person": ("Person", ("embodied_by_person",), "人物"),
    "place": ("Place", ("originated_at", "disseminated_at"), "地点"),
    "organization": ("Organization", ("embodied_by_organization", "transmitted_by"), "组织"),
    "document": ("Document", ("documented_in", "transmitted_by"), "文献"),
    "artifact": ("Artifact", ("symbolized_by",), "代表性物品"),
    "creative_work": ("CreativeWork", ("represented_in",), "红色文艺作品"),
    "time": ("TimePeriod", ("formed_during",), "时间"),
}

TASK_SPECS: dict[str, TaskSpec] = {}
for prefix, source_type in (("spirit", "Spirit"), ("facet", "ValueFacet")):
    for suffix, (target_type, relation_codes, label) in _DIMENSION_TARGETS.items():
        dimension = f"{prefix}_{suffix}"
        TASK_SPECS[dimension] = TaskSpec(dimension, source_type, target_type, relation_codes, label)


DIRECT_ALIASES = {
    "职位": "held_position",
    "职务": "held_position",
    "身份": "held_position",
    "兼任": "held_position",
    "主张": "advocated",
    "提出": "advocated",
    "制定": "formulated",
    "执行路线": "implemented",
    "批评": "criticized",
    "使用": "used_artifact",
    "利用": "used_artifact",
    "原型": "prototype_for",
    "生活原型": "prototype_for",
    "主编": "edited",
    "编辑": "edited",
    "审改者": "edited",
    "审阅者": "edited",
    "修改者": "edited",
    "派遣": "dispatched",
    "执行": "carried_out",
    "介绍": "introduced",
    "介绍人": "introduced",
    "同事": "colleague_of",
    "发展党员": "recruited",
    "发展关系": "recruited",
    "占领": "captured",
    "攻占": "captured",
    "攻克": "captured",
    "关押": "imprisoned_at",
    "关押地点": "imprisoned_at",
    "关押地": "imprisoned_at",
    "被关押": "imprisoned_at",
    "汇报": "reported_to",
    "管辖": "governed",
    "解放": "liberated",
    "任命": "appointed",
    "亲属关系": "family_of",
    "配偶": "spouse_of",
    "杀害": "killed",
    "处决": "killed",
    "保护": "protected",
    "保护关系": "protected",
    "营救": "rescued",
    "营救关系": "rescued",
    "护送": "escorted",
    "驻防": "stationed_at",
    "驻守": "stationed_at",
    "驻扎": "stationed_at",
    "驻扎地": "stationed_at",
    "价值关联": "has_value_facet",
    "核心内涵": "has_value_facet",
    "孕育于": "originated_from_event",
    "孕育": "originated_from_event",
    "源于历史事件": "originated_from_event",
    "体现于事件": "embodied_in_event",
    "关联事件": "embodied_in_event",
    "体现于人物": "embodied_by_person",
    "关联人物": "embodied_by_person",
    "由人物体现": "embodied_by_person",
    "代表人物": "embodied_by_person",
    "体现于组织": "embodied_by_organization",
    "关联组织": "embodied_by_organization",
    "由组织体现": "embodied_by_organization",
    "形成于地点": "originated_at",
    "发源于": "originated_at",
    "形成地": "originated_at",
    "关联地点": "originated_at",
    "传播于地点": "disseminated_at",
    "传播于": "disseminated_at",
    "记载于": "documented_in",
    "见于文献": "documented_in",
    "documented_in": "documented_in",
    "物化承载于": "symbolized_by",
    "承载": "symbolized_by",
    "承载于": "symbolized_by",
    "精神载体": "symbolized_by",
    "carried_by": "symbolized_by",
    "表现于文艺作品": "represented_in",
    "represented_by": "represented_in",
    "形成于时间": "formed_during",
    "形成时间": "formed_during",
    "关联时间": "formed_during",
    "formed_during": "formed_during",
    "传承于": "transmitted_by",
    "继承发展": "inherited_from",
    "参与": "participated_in",
    "领导": "led",
    "组织": "organized",
    "指挥": "commanded",
    "指导": "guided",
    "指示": "guided",
    "任职": "held_position_in",
    "任职于": "held_position_in",
    "担任": "held_position_in",
    "成员": "member_of",
    "工作地点": "worked_at",
    "工作于": "worked_at",
    "学习": "studied_at",
    "学习于": "studied_at",
    "前往": "traveled_to",
    "会见": "met_with",
    "会面": "met_with",
    "合作": "collaborated_with",
    "配合": "collaborated_with",
    "联系": "contacted",
    "联络": "contacted",
    "支持": "supported",
    "协助": "supported",
    "反对": "opposed",
    "培养": "trained",
    "负责": "responsible_for",
    "战友": "comrade_of",
    "战斗地点": "fought_at",
    "被捕地点": "arrested_at",
    "出生地": "born_at",
    "出生于地点": "born_at",
    "出生于时间": "born_during",
    "牺牲地点": "died_at",
    "逝世地点": "died_at",
    "牺牲逝世于时间": "died_during",
    "建立": "created",
    "影响": "influenced",
    "改编自": "adapted_from",
    "活动于": "active_at",
    "活动地点": "active_at",
    "活动区域": "active_at",
    "活动地": "active_at",
    "活动": "active_at",
    "活动时间": "active_during",
    "用于事件": "used_in_event",
    "使用于": "used_in_event",
    "保存于": "preserved_at",
    "收藏于": "preserved_at",
    "创作于地点": "created_at",
    "创作于时间": "created_during",
    "出版发行于": "published_by",
    "出版于": "published_by",
    "纪念": "commemorates",
    "传播": "disseminates",
    "组成部分": "part_of",
    "处于演进阶段": "belongs_to_stage",
    "行政隶属": "administratively_in",
    "属于流域区段": "within_basin",
    "隶属于": "member_of",
    "位于": "located_in",
    "创作": "authored",
    "创建": "created",
    "表现": "depicts",
    "记载": "documents",
}

WEAK_RELATIONS = {
    "关联",
    "相关",
    "associated_with",
    "related_to",
    "has_person",
    "has_place",
    "has_time",
    "has_document",
    "related_place",
}


RELATION_CUES: dict[str, tuple[str, ...]] = {
    "held_position": ("担任", "兼任", "任职", "当选为"),
    "position_in": ("属于", "隶属", "设于"),
    "advocated": ("主张", "提出", "倡导"),
    "formulated": ("制定", "拟定", "形成"),
    "implemented": ("执行", "推行", "贯彻"),
    "criticized": ("批评", "批判", "反对"),
    "used_artifact": ("使用", "利用", "持有"),
    "prototype_for": ("原型", "生活原型"),
    "edited": ("主编", "编辑", "修改", "审改", "审阅"),
    "dispatched": ("派遣", "指派", "派往", "调派"),
    "carried_out": ("执行", "实施", "落实"),
    "introduced": ("介绍", "介绍人", "引见"),
    "colleague_of": ("同事", "共事"),
    "recruited": ("发展党员", "发展为", "吸收为", "介绍入党"),
    "captured": ("攻占", "攻克", "占领", "夺取"),
    "imprisoned_at": ("关押", "囚禁", "监禁"),
    "reported_to": ("汇报", "报告"),
    "governed": ("管辖", "管理", "控制"),
    "liberated": ("解放",),
    "appointed": ("任命", "委任", "指派为"),
    "family_of": ("亲属", "父亲", "母亲", "兄弟", "姐妹", "子女"),
    "spouse_of": ("配偶", "丈夫", "妻子", "夫妻"),
    "killed": ("杀害", "处决", "枪杀"),
    "protected": ("保护", "掩护"),
    "rescued": ("营救", "解救"),
    "escorted": ("护送",),
    "stationed_at": ("驻防", "驻守", "驻扎"),
    "has_value_facet": ("内涵", "体现", "精神实质", "核心要义", "价值"),
    "originated_from_event": ("孕育", "形成", "产生", "源于", "发端"),
    "embodied_in_event": ("体现", "彰显", "凝结", "展现"),
    "embodied_by_person": ("体现", "代表人物", "践行", "彰显"),
    "embodied_by_organization": ("体现", "践行", "传承", "彰显"),
    "originated_at": ("形成于", "发源于", "诞生于", "起源于"),
    "disseminated_at": ("传播", "传入", "弘扬", "传承"),
    "documented_in": ("记载", "收录", "载于", "见于"),
    "symbolized_by": ("象征", "载体", "承载", "代表性物品"),
    "represented_in": ("表现", "改编", "创作", "艺术再现", "题材"),
    "formed_during": ("形成于", "产生于", "孕育于", "时期"),
    "transmitted_by": ("传播", "传承", "弘扬", "教育"),
    "inherited_from": ("继承", "发展", "一脉相承"),
    "participated_in": ("参加", "参与", "出席", "投身"),
    "led": ("领导", "率领", "指挥", "主持"),
    "organized": ("组织", "发起", "筹建", "主持"),
    "occurred_at": ("发生于", "发生在", "举行于", "位于"),
    "occurred_during": ("发生于", "发生在", "举行于", "期间"),
    "member_of": ("加入", "隶属", "任职", "成员"),
    "located_in": ("位于", "地处", "坐落", "隶属"),
    "administratively_in": ("隶属", "辖", "行政区划"),
    "within_basin": ("长江流域", "上游", "中游", "下游", "支流"),
    "authored": ("创作", "撰写", "著", "编写"),
    "created": ("创建", "创办", "建立", "创作"),
    "active_at": ("活动于", "活动在", "驻扎", "工作于"),
    "active_during": ("活动于", "期间", "任职于"),
    "used_in_event": ("使用", "用于", "遗物", "装备"),
    "preserved_at": ("保存于", "收藏于", "陈列于", "馆藏"),
    "created_at": ("创作于", "制作于", "写于", "摄制于"),
    "created_during": ("创作于", "制作于", "写于", "摄制于"),
    "published_by": ("出版", "发行", "刊载"),
    "commemorates": ("纪念", "缅怀", "追忆"),
    "disseminates": ("传播", "宣传", "弘扬", "传承"),
    "part_of": ("组成", "部分", "隶属于", "包括"),
    "belongs_to_stage": ("阶段", "时期", "演进"),
    "depicts": ("描写", "表现", "再现", "讲述"),
    "documents": ("记载", "记录", "收录", "反映"),
    "mentioned_in": ("记载", "提及", "收录", "载于"),
    "influenced": ("影响", "推动", "促进", "带动"),
    "adapted_from": ("改编自", "根据", "取材于"),
    "commanded": ("指挥", "命令", "部署"),
    "guided": ("指导", "指示", "帮助"),
    "held_position_in": ("任职", "担任", "书记", "负责人"),
    "worked_at": ("工作于", "工作地点", "任职于"),
    "studied_at": ("学习于", "就读", "求学"),
    "traveled_to": ("前往", "到达", "赴"),
    "visited": ("访问", "考察", "视察"),
    "met_with": ("会见", "会面", "接见"),
    "collaborated_with": ("合作", "配合", "共同"),
    "contacted": ("联系", "联络", "接洽"),
    "supported": ("支持", "协助", "支援"),
    "opposed": ("反对", "抵制", "斗争"),
    "trained": ("培养", "培训", "教育"),
    "responsible_for": ("负责", "主管", "分管"),
    "comrade_of": ("战友", "同志", "并肩"),
    "fought_at": ("战斗于", "战斗地点", "作战于"),
    "arrested_at": ("被捕于", "被捕地点", "逮捕于"),
    "born_at": ("出生于", "出生地", "诞生于"),
    "born_during": ("出生于", "生于"),
    "died_at": ("牺牲于", "逝世于", "遇难于"),
    "died_during": ("牺牲于", "逝世于", "遇难于"),
}


def stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    payload = "\x1f".join(clean_text(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def normalize_type(value: object) -> str:
    text = clean_text(value)
    if not text:
        return "Unknown"
    return TYPE_ALIASES.get(text.lower(), TYPE_ALIASES.get(text, text))


def task_spec(dimension: object) -> TaskSpec | None:
    return TASK_SPECS.get(clean_text(dimension))


def parse_json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    text = clean_text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = re.split(r"[,;；、\n]+", text)
    if not isinstance(parsed, list):
        parsed = [parsed]
    return [clean_text(item) for item in parsed if clean_text(item)]


def normalize_query(value: object) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[\"'“”‘’《》()（）\[\]{}]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def source_identity(spirit_name: object, facet_name: object = "") -> tuple[str, str]:
    facet = clean_text(facet_name)
    spirit = clean_text(spirit_name).split("::", 1)[0]
    return ("ValueFacet", facet) if facet else ("Spirit", spirit)


def canonicalize_relation(
    raw_relation: object,
    source_type: object,
    target_type: object,
    dimension: object = "",
) -> tuple[str, str]:
    """Return (canonical code, mapping strength). Empty code means unresolved."""
    raw = clean_text(raw_relation)
    src = normalize_type(source_type)
    dst = normalize_type(target_type)
    spec = task_spec(dimension)
    if raw in RELATIONS:
        code = raw
        strength = "canonical"
    elif raw in WEAK_RELATIONS:
        return "", "weak"
    elif raw in DIRECT_ALIASES:
        code = DIRECT_ALIASES[raw]
        strength = "alias"
    elif raw in {"体现于", "体现", "体现为", "embodies", "embodied_by", "manifested_in", "manifests_in"}:
        code = {
            "Event": "embodied_in_event",
            "Person": "embodied_by_person",
            "Organization": "embodied_by_organization",
            "Institution": "embodied_by_organization",
        }.get(dst, "")
        strength = "contextual"
    elif raw in {"形成于", "发源", "originates_from", "origin_place"}:
        code = {"Event": "originated_from_event", "Place": "originated_at", "TimePeriod": "formed_during"}.get(dst, "")
        strength = "contextual"
    elif raw in {"发生于", "发生地", "发生时间", "occurred_at", "occurred_in", "occurs_at"} and src == "Event":
        code = "occurred_at" if dst == "Place" else "occurred_during" if dst == "TimePeriod" else ""
        strength = "contextual"
    elif raw in {"关联文献", "文献记载", "相关文献"} and dst == "Document":
        code = "documented_in" if src in {"Spirit", "ValueFacet"} else "mentioned_in"
        strength = "contextual"
    elif raw in {"属于", "隶属", "所属组织"}:
        if dst == "Organization" and src in {"Person", "Organization"}:
            code = "member_of"
        elif src == "Place" and dst == "AdministrativeRegion":
            code = "administratively_in"
        elif src in {"Place", "AdministrativeRegion"} and dst == "BasinSection":
            code = "within_basin"
        elif dst == "Place" and src in {"Place", "Organization", "Institution"}:
            code = "located_in"
        else:
            code = ""
        strength = "contextual"
    elif raw in {"创作于", "撰写", "authored", "authored_by"} and src in {"Person", "Organization"} and dst in {"Document", "CreativeWork"}:
        code = "authored"
        strength = "contextual"
    elif raw in {"访问", "考察", "视察"}:
        if src in {"Person", "Organization"} and dst in {"Place", "Organization", "Institution"}:
            code = "visited"
        elif src in {"Person", "Organization"} and dst in {"Person", "Organization"}:
            code = "met_with"
        else:
            code = ""
        strength = "contextual"
    elif raw in {"出生于", "生于"} and src == "Person":
        code = "born_at" if dst == "Place" else "born_during" if dst == "TimePeriod" else ""
        strength = "contextual"
    elif raw in {"牺牲于", "逝世于", "遇难于"} and src == "Person":
        code = "died_at" if dst == "Place" else "died_during" if dst == "TimePeriod" else ""
        strength = "contextual"
    elif raw in {"主持", "主导"} and src in {"Person", "Organization"} and dst in {"Event", "Organization"}:
        code = "led"
        strength = "contextual"
    else:
        return "", "unmapped"
    if not code or code not in RELATIONS:
        return "", "unmapped"
    relation = RELATIONS[code]
    if not relation_type_allowed(src, relation.source_types) or not relation_type_allowed(
        dst, relation.target_types
    ):
        return "", "domain_range_mismatch"
    if spec and (src != spec.source_type or dst != spec.target_type or code not in spec.relation_codes):
        return code, "task_mismatch"
    return code, strength


def relation_type_allowed(actual_type: object, allowed_types: frozenset[str]) -> bool:
    actual = normalize_type(actual_type)
    return actual in allowed_types or (
        actual == "SocialGroup" and "Organization" in allowed_types
    )


def relation_domain_range_pass(code: object, source_type: object, target_type: object) -> bool:
    relation = RELATIONS.get(clean_text(code))
    return bool(
        relation
        and relation_type_allowed(source_type, relation.source_types)
        and relation_type_allowed(target_type, relation.target_types)
    )


def expected_dimension_pass(
    dimension: object,
    source_type: object,
    target_type: object,
    canonical_relation: object,
) -> bool:
    spec = task_spec(dimension)
    return bool(
        spec
        and normalize_type(source_type) == spec.source_type
        and normalize_type(target_type) == spec.target_type
        and clean_text(canonical_relation) in spec.relation_codes
    )


def normalize_entity_name(entity_type: object, name: object, time_value: object = "") -> tuple[str, list[str]]:
    typ = normalize_type(entity_type)
    raw = clean_text(name)
    if typ == "TimePeriod":
        normalized = normalize_time_fields(time_value or raw)
        return normalized.time_value, normalized.risk_flags
    text = re.sub(r"\s+", " ", raw).strip(" \t\r\n,，。;；:：")
    return text, [] if text else ["entity_name_missing"]


def canonical_entity_id(entity_type: object, name: object, *, spirit_id: object = "", facet_id: object = "") -> str:
    typ = normalize_type(entity_type)
    if typ == "Spirit" and clean_text(spirit_id):
        return f"SPIRIT::{clean_text(spirit_id)}"
    if typ == "ValueFacet" and clean_text(facet_id):
        return f"FACET::{clean_text(facet_id)}"
    normalized, _ = normalize_entity_name(typ, name)
    return stable_id("ENTITY", typ, normalized)


def relation_label(code: object) -> str:
    spec = RELATIONS.get(clean_text(code))
    return spec.label if spec else ""


def atomic_entity_name_pass(entity_type: object, name: object) -> bool:
    """Reject bundled endpoints that must be expanded into separate entities."""
    typ = normalize_type(entity_type)
    text = clean_text(name)
    if not text or typ not in {"Person", "Organization", "Place", "Institution", "Event"}:
        if typ == "TimePeriod":
            normalized = normalize_time_fields(text)
            return bool(
                normalized.time_start
                or (
                    re.search(r"(?:时期|阶段|期间|年代)$", text)
                    and any(token in text for token in ("革命", "战争", "建设", "改革", "抗战", "解放", "新时代"))
                )
            )
        return bool(text)
    generic_by_type = {
        "Place": {
            "县城", "城区", "市区", "当地", "该地", "此地", "此处", "这里", "那里",
            "一带", "附近", "途中", "前线", "后方", "原地", "驻地", "境内",
        },
        "Organization": {
            "支部", "党支部", "学生支部", "党组织", "地下党", "县委", "省委", "市委",
            "特委", "工委", "委员会", "工作团", "工作队", "游击队", "自卫军",
            "政府", "人民政府", "当地人民政府", "领导", "群众",
        },
        "Institution": {"学校", "中学", "大学", "学院", "纪念馆", "博物馆"},
        "Event": {"会议", "战斗", "战役", "起义", "运动", "斗争", "暴动", "事件"},
    }
    if text in generic_by_type.get(typ, set()):
        return False
    if typ == "Event":
        return True
    if re.search(r"[、，,；;]", text):
        return False
    if re.search(r"等(?:人|同志|单位|组织|部队|事件|地区|地点)?$", text):
        return False
    if typ == "Person" and re.search(r"[\u4e00-\u9fff]{2,6}(?:和|与)[\u4e00-\u9fff]{2,6}$", text):
        return False
    if typ == "Person" and re.search(r"(?:们|群众|工人|学生|战士|党员|干部|代表|民众)$", text):
        return False
    return True


_STRONG_EVENT_TOKENS = (
    "起义", "会议", "战役", "会战", "运动", "斗争", "暴动", "谈判", "解放", "事变", "长征",
    "战争", "围剿", "行动", "事件", "惨案", "罢工", "示威", "游行", "战斗", "改造", "改革",
    "大会", "全会", "会师",
)
_STRONG_ORG_TOKENS = (
    "中共", "共产党", "党委", "支部", "地下党", "党组织", "政府", "红军", "新四军", "八路军",
    "解放军", "军团", "军区", "纵队", "支队", "部队", "委员会", "委会", "省委", "市委",
    "县委", "特委", "工委", "协会", "学会", "学联", "学生会",
    "自治会", "参议会", "办事处", "指挥部", "集团", "代表团", "书记处", "城工部",
)
_STRONG_INSTITUTION_TOKENS = (
    "纪念馆", "博物馆", "旧址", "故居", "陵园", "纪念碑", "遗址", "粮站", "讲习所",
    "学校", "大学", "中学", "学院",
)
_STRONG_DOCUMENT_TOKENS = ("日报", "报纸", "刊物", "杂志", "文集", "文件", "决议", "宣言", "报告")
_STRONG_ARTIFACT_TOKENS = ("纪念塔", "纪念碑", "雕像", "遗物", "文物", "勋章", "旗帜")
_STRONG_PLACE_SUFFIXES = ("省", "市", "县", "区", "镇", "乡", "村", "山", "河", "湖", "路", "街", "地区", "根据地", "苏区")
_KNOWN_RIVERS = {"长江", "金沙江", "乌江", "湘江", "赣江", "嘉陵江", "岷江", "雅砻江", "大渡河", "赤水河"}


def strong_entity_type_hint(name: object) -> str:
    """Return only high-precision lexical type hints; empty means ambiguous."""
    text = clean_text(name)
    if not text:
        return ""
    if any(token in text for token in _STRONG_ARTIFACT_TOKENS):
        return "Artifact"
    if any(token in text for token in _STRONG_INSTITUTION_TOKENS):
        return "Institution"
    if any(token in text for token in _STRONG_DOCUMENT_TOKENS):
        return "Document"
    if text.endswith("精神"):
        return "Spirit"
    if re.fullmatch(r"[\u4e00-\u9fff]{2,4}将军", text):
        return "Person"
    if text.endswith(_STRONG_EVENT_TOKENS) or re.search(r"(?:中共)?[一二三四五六七八九十]+大$", text):
        return "Event"
    if any(token in text for token in _STRONG_ORG_TOKENS) or re.search(
        r"(?:第?[一二三四五六七八九十百0-9]+|红|新四|八路|解放|方面|纵队|支队|独立|游击|工农|人民).*(?:军|师|团|营|连|部)$",
        text,
    ) or re.search(r"(?:支部|党部|会社|学社|书社|协会|学会)$", text):
        return "Organization"
    if any(token in text for token in _STRONG_EVENT_TOKENS):
        return "Event"
    if text in _KNOWN_RIVERS:
        return "Place"
    if text.endswith(_STRONG_PLACE_SUFFIXES):
        return "Place"
    return ""


def relation_cue_pass(code: object, evidence_text: object) -> bool:
    text = clean_text(evidence_text)
    cues = RELATION_CUES.get(clean_text(code), ())
    return bool(text and cues and any(cue in text for cue in cues))


def claim_semantic_pattern_pass(
    code: object,
    evidence_text: object,
    source_name: object,
    target_name: object,
) -> bool:
    """Require directional local patterns for relations prone to reversal."""
    relation = clean_text(code)
    raw_text = clean_text(evidence_text)
    source_text = re.sub(r"\s+", "", clean_text(source_name))
    target_text = re.sub(r"\s+", "", clean_text(target_name))
    source = re.escape(source_text)
    target = re.escape(target_text)
    if not raw_text or not source or not target:
        return False
    # Context windows may contain several unrelated statements. A relation is
    # direct only when both endpoints and its directional expression occur in
    # the same sentence-like unit; joining the whole window creates false links.
    units = [
        re.sub(r"\s+", "", unit)
        for unit in re.split(r"[。！？!?；;\r\n]+", raw_text)
        if unit.strip()
    ]
    candidate_units = [
        unit for unit in units
        if re.search(source, unit) and re.search(target, unit)
    ]
    if not candidate_units:
        return False
    strict_patterns: dict[str, tuple[str, ...]] = {
        "held_position": (
            rf"{source}.{{0,25}}(?:担任|兼任|任职为|当选为).{{0,25}}{target}",
            rf"{source}.{{0,20}}(?:是|为){target}",
        ),
        "position_in": (rf"{source}.{{0,25}}(?:属于|隶属|设于).{{0,30}}{target}",),
        "advocated": (rf"{source}.{{0,25}}(?:主张|提出|倡导).{{0,35}}{target}",),
        "formulated": (rf"{source}.{{0,25}}(?:制定|拟定|形成).{{0,35}}{target}",),
        "implemented": (rf"{source}.{{0,25}}(?:执行|推行|贯彻).{{0,35}}{target}",),
        "criticized": (rf"{source}.{{0,25}}(?:批评|批判|反对).{{0,35}}{target}",),
        "used_artifact": (rf"{source}.{{0,25}}(?:使用|利用|持有).{{0,35}}{target}",),
        "prototype_for": (
            rf"{source}.{{0,25}}(?:是|为){target}.{{0,20}}(?:的)?(?:生活)?原型",
            rf"{target}.{{0,25}}(?:以|根据){source}.{{0,20}}(?:为)?(?:生活)?原型",
        ),
        "edited": (rf"{source}.{{0,25}}(?:主编|编辑|修改|审改|审阅).{{0,35}}{target}",),
        "dispatched": (rf"{source}.{{0,30}}(?:派遣|指派|派往|调派).{{0,35}}{target}",),
        "carried_out": (rf"{source}.{{0,30}}(?:执行|实施|落实).{{0,35}}{target}",),
        "introduced": (rf"{source}.{{0,30}}(?:介绍|引见).{{0,35}}{target}",),
        "colleague_of": (
            rf"{source}.{{0,25}}(?:与|和|同){target}.{{0,25}}(?:同事|共事)",
            rf"{target}.{{0,25}}(?:与|和|同){source}.{{0,25}}(?:同事|共事)",
        ),
        "recruited": (rf"{source}.{{0,30}}(?:发展|吸收|介绍).{{0,20}}{target}.{{0,15}}(?:入党|为党员|加入)",),
        "captured": (rf"{source}.{{0,18}}(?:攻占|攻克|占领|夺取).{{0,12}}{target}",),
        "imprisoned_at": (rf"{source}.{{0,35}}(?:被关押|被囚禁|被监禁|关押于|囚禁于|监禁于).{{0,30}}{target}",),
        "reported_to": (rf"{source}.{{0,30}}(?:向|给){target}.{{0,20}}(?:汇报|报告)",),
        "governed": (rf"{source}.{{0,30}}(?:管辖|管理|控制).{{0,35}}{target}",),
        "liberated": (rf"{source}.{{0,18}}解放.{{0,15}}{target}",),
        "appointed": (rf"{source}.{{0,30}}(?:任命|委任|指派){target}",),
        "family_of": (
            rf"{source}.{{0,20}}(?:是|为){target}.{{0,15}}(?:父亲|母亲|兄弟|姐妹|子女|亲属)",
            rf"{target}.{{0,20}}(?:是|为){source}.{{0,15}}(?:父亲|母亲|兄弟|姐妹|子女|亲属)",
        ),
        "spouse_of": (
            rf"{source}.{{0,20}}(?:是|为){target}.{{0,15}}(?:丈夫|妻子|配偶)",
            rf"{target}.{{0,20}}(?:是|为){source}.{{0,15}}(?:丈夫|妻子|配偶)",
        ),
        "killed": (rf"{source}.{{0,30}}(?:杀害|处决|枪杀).{{0,35}}{target}",),
        "protected": (rf"{source}.{{0,30}}(?:保护|掩护).{{0,35}}{target}",),
        "rescued": (rf"{source}.{{0,30}}(?:营救|解救).{{0,35}}{target}",),
        "escorted": (rf"{source}.{{0,30}}护送.{{0,35}}{target}",),
        "stationed_at": (rf"{source}.{{0,30}}(?:驻防|驻守|驻扎)(?:于|在)?.{{0,30}}{target}",),
        "originated_from_event": (
            rf"{source}.{{0,35}}(?:孕育于|形成于|产生于|源于|发端于).{{0,45}}{target}",
            rf"{target}.{{0,45}}(?:孕育|形成|产生|催生).{{0,35}}{source}",
        ),
        "embodied_in_event": (
            rf"{target}.{{0,45}}(?:体现|彰显|凝结|展现).{{0,35}}{source}",
            rf"{source}.{{0,35}}(?:体现于|彰显于|凝结于).{{0,45}}{target}",
        ),
        "embodied_by_person": (
            rf"{target}.{{0,35}}(?:体现|践行|彰显|秉持|坚持).{{0,45}}{source}",
            rf"{source}.{{0,35}}(?:由|在).{{0,20}}{target}.{{0,20}}(?:体现|践行|彰显)",
            rf"{target}.{{0,25}}(?:是|作为).{{0,30}}{source}.{{0,20}}(?:代表人物|践行者)",
        ),
        "embodied_by_organization": (
            rf"{target}.{{0,35}}(?:体现|践行|彰显|传承|弘扬).{{0,45}}{source}",
            rf"{source}.{{0,35}}(?:由|在).{{0,20}}{target}.{{0,20}}(?:体现|践行|彰显|传承)",
        ),
        "originated_at": (
            rf"{source}.{{0,30}}(?:形成于|发源于|诞生于|起源于).{{0,35}}{target}",
        ),
        "disseminated_at": (
            rf"{source}.{{0,30}}(?:传播至|传入|弘扬于|传承于).{{0,35}}{target}",
        ),
        "symbolized_by": (
            rf"{target}.{{0,35}}(?:象征|承载|体现).{{0,45}}{source}",
            rf"{source}.{{0,35}}(?:以|由).{{0,20}}{target}.{{0,20}}(?:为象征|为载体|承载)",
        ),
        "represented_in": (
            rf"{target}.{{0,45}}(?:表现|再现|描写|讲述|以).{{0,45}}{source}",
            rf"{source}.{{0,35}}(?:表现于|再现于|被改编为).{{0,45}}{target}",
        ),
        "formed_during": (
            rf"{source}.{{0,35}}(?:形成于|产生于|孕育于).{{0,35}}{target}",
            rf"{target}.{{0,35}}(?:形成|产生|孕育).{{0,35}}{source}",
        ),
        "transmitted_by": (
            rf"{target}.{{0,35}}(?:传播|传承|弘扬|宣传|教育).{{0,45}}{source}",
            rf"{source}.{{0,35}}(?:由|通过).{{0,20}}{target}.{{0,20}}(?:传播|传承|弘扬)",
        ),
        "participated_in": (
            rf"{source}.{{0,35}}(?:参与举办|参与组织|参与筹办).{{0,20}}{target}",
            rf"{source}.{{0,12}}(?:参加了?|参与了?|出席了?|投身).{{0,20}}{target}",
            rf"{source}.{{0,8}}(?:随|率)(?:部|队|军).{{0,8}}参加了?.{{0,15}}{target}",
            rf"{target}.{{0,30}}(?:参加者|参与者|出席者)(?:包括|有).{{0,12}}{source}",
        ),
        "led": (
            rf"{source}(?:同志)?(?:、[\u4e00-\u9fff]{{2,6}}){{0,2}}(?:等|同志)?(?:直接|亲自)?(?:领导了?|率领|指挥)(?:的)?.{{0,6}}{target}",
            rf"{source}(?:同志)?(?:、[\u4e00-\u9fff]{{2,6}}){{0,2}}(?:等|同志)?主持(?:召开|举行)?.{{0,4}}{target}",
            rf"{target}.{{0,12}}(?:由|在).{{0,8}}{source}(?:同志)?(?:、[\u4e00-\u9fff]{{2,6}}){{0,2}}(?:等|同志)?(?:直接|亲自)?(?:领导|率领|指挥|主持)",
        ),
        "organized": (
            rf"{source}.{{0,18}}(?:组织|发起|筹建|成立|组建|主办).{{0,24}}{target}",
            rf"{target}.{{0,30}}(?:由).{{0,15}}{source}.{{0,10}}(?:组织|发起|筹建|成立|组建|举办)",
        ),
        "member_of": (
            rf"{source}.{{0,30}}(?:加入|隶属|任职于|是).{{0,35}}{target}",
            rf"{source}.{{0,25}}(?:参加|加入).{{0,25}}{target}.{{0,20}}(?:成员|骨干|干部)?",
            rf"{source}.{{0,20}}是{target}.{{0,20}}(?:成员|骨干|干部)",
            rf"{target}.{{0,40}}(?:成员|党员|干部).{{0,15}}{source}",
        ),
        "authored": (
            rf"{source}.{{0,25}}(?:创作|撰写|著|编写).{{0,35}}{target}",
            rf"{target}.{{0,30}}(?:作者|编者).{{0,15}}{source}",
        ),
        "created": (
            rf"{source}.{{0,30}}(?:创建|创办|建立|创作).{{0,40}}{target}",
            rf"{target}.{{0,35}}(?:由).{{0,20}}{source}.{{0,15}}(?:创建|创办|建立|创作)",
        ),
        "occurred_at": (
            rf"{source}(?!部队|队伍|军队|人员|代表|参加者).{{0,20}}(?:发生于|发生在|爆发于|爆发在|举行于|举行在|会师于|会师在).{{0,20}}{target}",
            rf"{source}(?!部队|队伍|军队|人员|代表|参加者).{{0,15}}(?:在|于){target}.{{0,10}}(?:发生|爆发|举行|会师)",
            rf"{source}.{{0,15}}(?:的)?(?:发生地|爆发地|举行地|会址)(?:是|为|位于).{{0,12}}{target}",
            rf"{target}.{{0,12}}(?:是|为){source}(?:的)?(?:发生地|爆发地|举行地|会址)",
        ),
        "occurred_during": (
            rf"{source}.{{0,20}}(?:发生于|发生在|爆发于|爆发在|举行于|始于|结束于).{{0,20}}{target}",
            rf"{source}.{{0,15}}(?:在|于){target}.{{0,10}}(?:发生|爆发|举行|开始|结束)",
        ),
        "located_in": (
            rf"{source}.{{0,20}}(?:位于|地处|坐落于|坐落在|隶属于).{{0,20}}{target}",
            rf"{target}.{{0,20}}(?:下辖|包括|包含).{{0,20}}{source}",
        ),
        "part_of": (
            rf"{source}.{{0,25}}(?:是|作为|属于).{{0,25}}{target}.{{0,15}}(?:的)?(?:组成部分|重要部分|一部分)",
            rf"{target}.{{0,35}}(?:包括|包含|由).{{0,35}}{source}",
        ),
        "commanded": (
            rf"{source}.{{0,30}}(?:指挥|命令|部署).{{0,45}}{target}",
            rf"{target}.{{0,45}}(?:由).{{0,20}}{source}.{{0,15}}(?:指挥|部署)",
        ),
        "guided": (
            rf"{source}.{{0,12}}(?:指导|帮助).{{0,15}}{target}",
            rf"{target}.{{0,18}}(?:在|得到).{{0,12}}{source}.{{0,10}}(?:指导|帮助)",
        ),
        "held_position_in": (
            rf"{source}.{{0,20}}(?:任职于|担任).{{0,35}}{target}",
            rf"{source}(?:同志)?任(?!命).{{0,25}}{target}",
            rf"{source}.{{0,25}}在.{{0,25}}{target}.{{0,15}}(?:兼任|任|担任).{{0,20}}(?:教员|教师|负责人|书记|委员|主席|司令员|政委)",
            rf"{target}.{{0,45}}{source}.{{0,15}}(?:任|担任).{{0,20}}(?:书记|负责人|司令员|政委|主席|委员)",
            rf"{target}.{{0,45}}{source}.{{0,15}}(?:被选为|当选为|兼任).{{0,20}}(?:书记|负责人|教员|教师|司令员|政委|主席|委员)",
            rf"{target}.{{0,45}}(?:以|由){source}(?:同志)?(?:为|任).{{0,18}}(?:书记|负责人|教员|教师|司令|司令员|政委|主任|主席|委员)",
        ),
        "mentioned_in": (
            rf"{source}.{{0,25}}(?:记载于|载于|收录于|见于|被报道于|被刊登于).{{0,20}}{target}",
            rf"{target}.{{0,25}}(?:记载|提及|收录|报道|刊登|写有|载有).{{0,35}}{source}",
        ),
        "documented_in": (
            rf"{source}.{{0,25}}(?:记载于|载于|收录于|见于).{{0,20}}{target}",
            rf"{target}.{{0,25}}(?:记载|阐释|定义|收录|写有|载有).{{0,35}}{source}",
        ),
        "worked_at": (rf"{source}.{{0,30}}(?:工作于|工作地点|任职于).{{0,40}}{target}",),
        "studied_at": (
            rf"{source}.{{0,25}}(?:学习于|就读于|求学于|毕业于).{{0,25}}{target}",
            rf"{source}.{{0,20}}(?:在|于){target}.{{0,12}}(?:学习|就读|求学|毕业)",
        ),
        "traveled_to": (rf"{source}.{{0,25}}(?:前往|到达|赴).{{0,35}}{target}",),
        "visited": (rf"{source}.{{0,25}}(?:访问|考察|视察).{{0,35}}{target}",),
        "met_with": (rf"{source}.{{0,10}}(?:会见|会面|接见).{{0,15}}{target}",),
        "contacted": (rf"{source}.{{0,18}}(?:联系|联络|接洽).{{0,20}}{target}",),
        "collaborated_with": (
            rf"{source}.{{0,15}}(?:与|同|和).{{0,15}}{target}.{{0,20}}(?:合作|配合|协作|共同)",
            rf"{target}.{{0,15}}(?:与|同|和).{{0,15}}{source}.{{0,20}}(?:合作|配合|协作|共同)",
            rf"{source}.{{0,20}}(?:配合|协作).{{0,25}}{target}",
        ),
        "influenced": (
            rf"{source}.{{0,25}}(?:(?<!受)(?<!到)影响了?|感召了?|带动了?).{{0,35}}{target}",
            rf"{target}.{{0,25}}(?:在|受到).{{0,20}}{source}.{{0,15}}(?:影响|感召|带动)",
            rf"{source}.{{0,80}}(?:使|令).{{0,30}}{target}.{{0,10}}(?:深受|受到).{{0,6}}影响",
            rf"{target}.{{0,40}}从{source}.{{0,25}}(?:受到启示|深受影响)",
            rf"{target}.{{0,120}}在(?:党的教育和)?{source}(?:的)?影响下",
            rf"在{source}.{{0,12}}(?:影响|感召|带动)下.{{0,25}}{target}",
        ),
        "active_at": (
            rf"{source}.{{0,30}}(?:活动|驻扎|工作|战斗|生活)(?:于|在).{{0,30}}{target}",
            rf"{source}.{{0,20}}(?:在).{{0,25}}{target}.{{0,10}}(?:活动|驻扎|工作|战斗|生活)",
        ),
        "supported": (rf"{source}.{{0,30}}(?:支持|协助|支援).{{0,40}}{target}",),
        "opposed": (rf"{source}.{{0,30}}(?:反对|抵制|斗争).{{0,40}}{target}",),
        "trained": (rf"{source}.{{0,30}}(?:培养|培训|教育).{{0,40}}{target}",),
        "responsible_for": (rf"{source}.{{0,25}}(?:负责(?!人)|主管|分管).{{0,40}}{target}",),
        "comrade_of": (
            rf"{source}.{{0,15}}(?:与|同|和).{{0,15}}{target}.{{0,25}}(?:结为|成为|是).{{0,10}}(?:亲密|革命)?战友",
            rf"{target}.{{0,15}}(?:与|同|和).{{0,15}}{source}.{{0,25}}(?:结为|成为|是).{{0,10}}(?:亲密|革命)?战友",
            rf"{source}.{{0,12}}是{target}.{{0,12}}(?:的)?(?:亲密|革命)?战友",
            rf"{target}.{{0,12}}是{source}.{{0,12}}(?:的)?(?:亲密|革命)?战友",
            rf"{source}.{{0,40}}{target}.{{0,10}}等(?:革命)?战友",
            rf"{target}.{{0,35}}{source}.{{0,30}}(?:悼念|追忆).{{0,8}}战友",
        ),
        "fought_at": (rf"{source}.{{0,35}}(?:战斗于|作战于|在).{{0,40}}{target}.{{0,10}}(?:战斗|作战)",),
        "arrested_at": (rf"{source}.{{0,35}}(?:在).{{0,30}}{target}.{{0,10}}(?:被捕|遭逮捕)",),
        "born_at": (
            rf"{source}.{{0,25}}(?:出生于|生于|诞生于).{{0,25}}{target}",
            rf"{source}.{{0,20}}(?:在|于){target}.{{0,10}}出生",
        ),
        "died_at": (
            rf"{source}.{{0,35}}(?:在|于).{{0,30}}{target}.{{0,25}}(?:牺牲|逝世|去世|遇难)",
            rf"{source}.{{0,160}}(?:牺牲|逝世|去世|遇难)(?:于|在).{{0,25}}{target}",
        ),
    }
    patterns = strict_patterns.get(relation)
    if patterns:
        cue_values = RELATION_CUES.get(relation, ())

        def blocked(unit: str) -> bool:
            cue_alt = "|".join(re.escape(value) for value in cue_values)
            if cue_alt and re.search(
                rf"{source}.{{0,25}}(?:未|没有|并未|未能|不能|从未).{{0,8}}(?:{cue_alt}).{{0,25}}{target}", unit
            ):
                return True
            if relation == "participated_in" and re.search(
                rf"{source}.{{0,20}}(?:镇压|反对|阻止|破坏).{{0,20}}{target}", unit
            ):
                return True
            if relation in {"captured", "liberated", "created", "organized"} and re.search(
                rf"(?:决定|计划|准备|拟|意图|打算).{{0,25}}{source}.{{0,20}}(?:攻占|攻克|占领|夺取|解放|创建|建立|组织)", unit
            ) and not re.search(r"(?:随后|最终|后来|已经|成功|遂|一举)", unit):
                return True
            return False

        return any(
            re.search(pattern, unit)
            for unit in candidate_units if not blocked(unit)
            for pattern in patterns
        )
    # Unknown or newly introduced relations fail closed until an explicit
    # directional contract is added and tested.
    return False


def compact_relation_catalog(codes: Iterable[str]) -> list[dict[str, object]]:
    result = []
    for code in codes:
        spec = RELATIONS[code]
        result.append(
            {
                "code": code,
                "label": spec.label,
                "source_types": sorted(spec.source_types),
                "target_types": sorted(spec.target_types),
            }
        )
    return result
