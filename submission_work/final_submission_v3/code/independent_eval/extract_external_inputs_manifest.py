"""生成 EXTERNAL_INPUTS_MANIFEST.json：记录复制进 v3 的包外输入文件 sha256/size/来源路径。"""
import hashlib, json, os
from datetime import datetime, timezone

ROOT = r"D:\REDCULTUREDATA\投稿材料_代码数据整理包"
DEST_DIR = os.path.join(ROOT, "submission_work", "final_submission_v3", "data", "external_inputs")

SOURCES = {
    "AI_GOLD_LABELS.csv": r"D:\REDCULTUREDATA\dual_paper_project\paper_A_method\04_results\AI_GOLD_LABELS.csv",
    "llm_predictions.csv": r"D:\REDCULTUREDATA\dual_paper_project\paper_A_method\04_results\llm_predictions.csv",
    "stkg_contract.py": r"D:\REDCULTUREDATA\scripts\stkg_contract.py",
    "stkg_v2_semantics.py": r"D:\REDCULTUREDATA\scripts\stkg_v2_semantics.py",
    # 传递依赖：stkg_contract.py 第 11 行 from stkg_normalization import ...
    "stkg_normalization.py": r"D:\REDCULTUREDATA\scripts\stkg_normalization.py",
}

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

entries = []
for name, src in SOURCES.items():
    dst = os.path.join(DEST_DIR, name)
    entry = {
        "file": name,
        "relative_path": f"submission_work/final_submission_v3/data/external_inputs/{name}",
        "source_path": src,
        "size_bytes": os.path.getsize(dst),
        "sha256": sha256_of(dst),
    }
    entry["source_sha256_match"] = (sha256_of(src) == entry["sha256"])
    entries.append(entry)

manifest = {
    "manifest_id": "EXTERNAL_INPUTS_MANIFEST",
    "created_at_utc": datetime.now(timezone.utc).isoformat(),
    "master_seed": 20260907,
    "description": "Phase 数据准备：从包外复制进 v3 的输入文件清单（只读引用，原名保留）",
    "files": entries,
}
out = os.path.join(DEST_DIR, "EXTERNAL_INPUTS_MANIFEST.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, ensure_ascii=False, indent=2)
print(json.dumps(entries, ensure_ascii=False, indent=2))
