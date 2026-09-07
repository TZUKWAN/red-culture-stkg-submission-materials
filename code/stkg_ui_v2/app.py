"""Read-only Chinese research UI for the isolated STKG V2 Neo4j graph."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from neo4j import GraphDatabase


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path(__file__).resolve().parent / "static"
PASSWORD_FILE = ROOT / ".codex" / "runtime" / "neo4j_stkg_v2_password.txt"
NEO4J_URI = os.environ.get("STKG_V2_NEO4J_URI", "bolt://127.0.0.1:7690")
NEO4J_USER = os.environ.get("STKG_V2_NEO4J_USER", "neo4j")

app = FastAPI(title="长江流域红色文化演进时空知识图谱", docs_url=None, redoc_url=None)
_driver = None
_driver_lock = Lock()


def get_driver():
    global _driver
    if _driver is None:
        with _driver_lock:
            if _driver is None:
                password = PASSWORD_FILE.read_text(encoding="utf-8").strip()
                _driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, password))
                _driver.verify_connectivity()
    return _driver


def parse_properties_json(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def node_data(node) -> dict:
    props = dict(node)
    nested = parse_properties_json(props.pop("properties_json", None))
    return {
        "id": str(props.get("stable_id") or props.get("graph_id") or node.element_id),
        "label": str(props.get("caption") or props.get("name") or "未命名实体"),
        "kind": str(props.get("node_kind") or next(iter(node.labels), "Entity")),
        "entityType": str(props.get("entity_type") or ""),
        "status": str(props.get("status") or ""),
        "properties": {**nested, **props},
    }


def relationship_data(rel, source_id: str, target_id: str, fallback_label: str = "") -> dict:
    props = dict(rel)
    nested = parse_properties_json(props.pop("properties_json", None))
    label = str(props.get("relation_label_zh") or props.get("role_code") or props.get("predicate") or fallback_label or rel.type)
    return {
        "id": str(props.get("relationship_id") or rel.element_id),
        "source": source_id,
        "target": target_id,
        "label": label,
        "type": rel.type,
        "status": str(props.get("status") or ""),
        "properties": {**nested, **props},
    }


def merge_graph(nodes: list[dict], edges: list[dict]) -> dict:
    unique_nodes = {node["id"]: node for node in nodes}
    unique_edges = {edge["id"]: edge for edge in edges if edge["source"] in unique_nodes and edge["target"] in unique_nodes}
    return {"nodes": list(unique_nodes.values()), "edges": list(unique_edges.values())}


def entity_links(session, ids: list[str], limit: int = 220) -> list[dict]:
    if not ids:
        return []
    rows = session.run(
        "MATCH (a:Entity)-[r:SEMANTIC_RELATION|EVENT_ROLE|EVENT_RELATION]->(b:Entity) "
        "WHERE a.stable_id IN $ids AND b.stable_id IN $ids "
        "RETURN a.stable_id AS source,b.stable_id AS target,r LIMIT $limit",
        ids=ids, limit=limit,
    )
    return [relationship_data(row["r"], str(row["source"]), str(row["target"])) for row in rows]


@app.get("/api/health")
def health():
    queries = {
        "总节点": "MATCH (n) RETURN count(n) AS value",
        "实体": "MATCH (n:Entity) RETURN count(n) AS value",
        "语义关系": "MATCH ()-[r:SEMANTIC_RELATION]->() RETURN count(r) AS value",
        "事件角色": "MATCH ()-[r:EVENT_ROLE]->() RETURN count(r) AS value",
        "文化状态": "MATCH (n:CultureState) RETURN count(n) AS value",
        "可信状态": "MATCH (n:CultureState {observation_tier:'trusted_event_spacetime'}) RETURN count(n) AS value",
        "演进候选": "MATCH (n:TransitionCandidate) RETURN count(n) AS value",
        "发布演进": "MATCH (n:EvolutionTransition) RETURN count(n) AS value",
        "文艺作品": "MATCH (n:CreativeWork) RETURN count(n) AS value",
        "作品媒介已标注": "MATCH (n:CreativeWork) WHERE n.media_type IS NOT NULL RETURN count(n) AS value",
    }
    driver = get_driver()
    with driver.session(database="neo4j") as session:
        values = {label: int(session.run(query).single(strict=True)["value"]) for label, query in queries.items()}
    return {"status": "ok", "neo4j": NEO4J_URI, "counts": values}


@app.get("/api/meta")
def meta():
    driver = get_driver()
    with driver.session(database="neo4j") as session:
        stages = [dict(row) for row in session.run(
            "MATCH (n:HistoricalStage) RETURN n.stage_code AS value,n.name AS label,"
            "n.properties_json AS properties_json"
        )]
        for stage in stages:
            stage["stageOrder"] = int(
                parse_properties_json(stage.pop("properties_json", None)).get("stage_order", 999)
            )
        stages.sort(key=lambda item: (item["stageOrder"], item["label"]))
        regions = [dict(row) for row in session.run(
            "MATCH (n:StudyRegion) RETURN n.region_id AS value,n.name AS label ORDER BY n.name"
        )]
        forms = [dict(row) for row in session.run(
            "MATCH (n:CultureForm) RETURN n.culture_form_code AS value,n.name AS label ORDER BY n.name"
        )]
        media_types = [dict(row) for row in session.run(
            "MATCH (n:CreativeWork) WHERE n.media_type IS NOT NULL "
            "RETURN n.media_type AS value,n.media_type AS label,count(*) AS count ORDER BY count DESC,n.media_type"
        )]
    return {"stages": stages, "regions": regions, "forms": forms, "mediaTypes": media_types,
            "tiers": [{"value": "trusted_event_spacetime", "label": "可信事件时空"},
                      {"value": "asserted_event_spacetime", "label": "单条时间候选"},
                      {"value": "relation_context", "label": "关系上下文"}]}


@app.get("/api/overview")
def overview():
    driver = get_driver()
    nodes: list[dict] = []
    edges: list[dict] = []
    with driver.session(database="neo4j") as session:
        for row in session.run(
            "MATCH (s:CultureState {observation_tier:'trusted_event_spacetime'})-[:STATE_OF]->(e:Entity) "
            "WITH e,count(*) AS score ORDER BY score DESC,e.name LIMIT 38 RETURN e,score"
        ):
            item = node_data(row["e"])
            item["score"] = int(row["score"])
            nodes.append(item)
        for row in session.run(
            "MATCH (s:CultureState {observation_tier:'trusted_event_spacetime'})-[:STATE_EVENT]->(e:Entity) "
            "WITH e,count(*) AS score ORDER BY score DESC,e.name LIMIT 32 RETURN e,score"
        ):
            item = node_data(row["e"])
            item["score"] = int(row["score"])
            nodes.append(item)
        ids = list({node["id"] for node in nodes})[:60]
        nodes = [node for node in nodes if node["id"] in ids]
        edges.extend(entity_links(session, ids))
        for row in session.run(
            "MATCH (t:EvolutionTransition)-[:TRANSITION_FROM_STATE]->(fs:CultureState)-[:STATE_OF]->(a:Entity),"
            "(t)-[:TRANSITION_TO_STATE]->(ts:CultureState)-[:STATE_OF]->(b:Entity),"
            "(t)-[:TRANSITION_HAS_TYPE]->(tt:TransitionType) RETURN t,a,b,tt"
        ):
            left, right = node_data(row["a"]), node_data(row["b"])
            nodes.extend((left, right))
            tprops = dict(row["t"])
            edges.append({"id": str(tprops["stable_id"]), "source": left["id"], "target": right["id"],
                          "label": str(dict(row["tt"]).get("name") or "演进"), "type": "PUBLISHED_EVOLUTION",
                          "status": "published", "properties": tprops})
    return merge_graph(nodes, edges)


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=80)):
    driver = get_driver()
    with driver.session(database="neo4j") as session:
        rows = session.run(
            "CALL db.index.fulltext.queryNodes('entity_name_fulltext_v2',$q,{limit:20}) "
            "YIELD node,score RETURN node,score ORDER BY score DESC", q=q,
        )
        results = []
        for row in rows:
            item = node_data(row["node"])
            results.append({"id": item["id"], "name": item["label"], "entityType": item["entityType"],
                            "mediaType": item["properties"].get("media_type", ""),
                            "score": round(float(row["score"]), 4)})
    return {"results": results}


@app.get("/api/explore")
def explore(
    stage: str = "", region: str = "", form: str = "", media: str = "",
    tier: str = "trusted_event_spacetime",
):
    allowed_tiers = {"trusted_event_spacetime", "asserted_event_spacetime", "relation_context"}
    if tier not in allowed_tiers:
        raise HTTPException(400, "无效可信层级")
    driver = get_driver()
    nodes, edges = [], []
    with driver.session(database="neo4j") as session:
        rows = list(session.run(
            "MATCH (s:CultureState)-[:STATE_OF]->(focus:Entity),"
            "(s)-[:STATE_EVENT]->(event:Entity) "
            "WHERE s.observation_tier=$tier AND ($stage='' OR s.stage_code=$stage) "
            "AND ($region='' OR s.region_id=$region) AND ($form='' OR s.culture_form_code=$form) "
            "AND ($media='' OR focus.media_type=$media) "
            "RETURN s,focus,event ORDER BY s.fact_count DESC,s.name LIMIT 90",
            tier=tier, stage=stage, region=region, form=form, media=media,
        ))
        for row in rows:
            focus, event, state = node_data(row["focus"]), node_data(row["event"]), dict(row["s"])
            nodes.extend((focus, event))
            edge_id = f"state-event:{state['stable_id']}:{focus['id']}:{event['id']}"
            edges.append({"id": edge_id, "source": focus["id"], "target": event["id"], "label": "关联事件",
                          "type": "STATE_EVENT", "status": state.get("observation_tier", ""),
                          "properties": {"state": state.get("name"), "stage": state.get("stage_label_zh"),
                                         "province": state.get("province_name"), "form": state.get("culture_form_label_zh")}})
        ids = list({node["id"] for node in nodes})[:120]
        nodes = [node for node in nodes if node["id"] in ids]
        edges.extend(entity_links(session, ids, 260))
    return merge_graph(nodes, edges)


@app.get("/api/entity/{stable_id}")
def entity(stable_id: str):
    driver = get_driver()
    nodes, edges = [], []
    with driver.session(database="neo4j") as session:
        record = session.run("MATCH (n:Entity {stable_id:$id}) RETURN n", id=stable_id).single()
        if record is None:
            raise HTTPException(404, "实体不存在")
        center = node_data(record["n"])
        nodes.append(center)
        rows = session.run(
            "MATCH (n:Entity {stable_id:$id})-[r:SEMANTIC_RELATION|EVENT_ROLE|EVENT_RELATION|HAS_CULTURE_FORM]-(m) "
            "WHERE m:Entity OR m:CultureForm RETURN n,r,m,startNode(r).stable_id AS source,endNode(r).stable_id AS target "
            "ORDER BY type(r),m.name LIMIT 120", id=stable_id,
        )
        relations = []
        for row in rows:
            neighbor = node_data(row["m"])
            nodes.append(neighbor)
            source = str(row["source"])
            target = str(row["target"])
            edge = relationship_data(row["r"], source, target)
            edges.append(edge)
            relations.append({"direction": "out" if source == stable_id else "in", "name": neighbor["label"],
                              "entityType": neighbor["entityType"] or neighbor["kind"], "label": edge["label"]})
        timeline = [dict(row) for row in session.run(
            "MATCH (s:CultureState)-[:STATE_OF]->(n:Entity {stable_id:$id}) "
            "RETURN s.stage_label_zh AS stage,s.province_name AS province,s.culture_form_label_zh AS form,"
            "s.observation_tier AS tier,s.fact_count AS facts ORDER BY s.stage_code,s.province_name LIMIT 80", id=stable_id,
        )]
        counts = dict(session.run(
            "MATCH (n:Entity {stable_id:$id}) "
            "OPTIONAL MATCH (n)-[:SUBJECT_OF]->(a1:Assertion) WITH n,count(distinct a1) AS subjectFacts "
            "OPTIONAL MATCH (a2:Assertion)-[:OBJECT]->(n) RETURN subjectFacts,count(distinct a2) AS objectFacts", id=stable_id,
        ).single())
    return {"graph": merge_graph(nodes, edges), "entity": center, "relations": relations,
            "timeline": timeline, "factCounts": counts}


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
