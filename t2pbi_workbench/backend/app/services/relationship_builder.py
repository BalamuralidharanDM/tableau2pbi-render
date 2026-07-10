from __future__ import annotations
import itertools
import re
from app.core.name_sanitizer import clean_name
from app.models.schemas import MigrationProject, RelationshipCandidate

KEY_PATTERNS = ["id", "key", "code", "number", "num"]


def _is_likely_key(name: str, col: dict | None = None) -> bool:
    n = clean_name(name).lower().replace(" ", "_")
    return bool(col and col.get("possible_key")) or n.endswith("_id") or n.endswith("id") or any(n == p or n.endswith("_" + p) for p in KEY_PATTERNS)


def _score_pair(a: str, b: str, ac: dict | None = None, bc: dict | None = None) -> tuple[float, list[str]]:
    ca, cb = clean_name(a).lower(), clean_name(b).lower()
    reasons = []
    score = 0.0
    if ca == cb:
        score += 0.45
        reasons.append("same column name")
    if ca.replace("_", "").replace(" ", "") == cb.replace("_", "").replace(" ", ""):
        score += 0.15
        reasons.append("normalized name match")
    if _is_likely_key(ca, ac) and _is_likely_key(cb, bc):
        score += 0.25
        reasons.append("key/unique naming pattern")
    if ac and bc and (ac.get("data_type") == bc.get("data_type")):
        score += 0.05
        reasons.append("datatype match")
    return min(score, 0.95), reasons


def infer_relationships(project: MigrationProject) -> list[RelationshipCandidate]:
    rels: list[RelationshipCandidate] = []
    # Direct Tableau joins/relations become high-confidence candidates.
    for ds in project.datasources:
        for r in ds.relations:
            for clause in r.clauses:
                text = str(clause)
                fields = re.findall(r"\[([^\]]+)\]", text)
                if len(fields) >= 2:
                    rels.append(RelationshipCandidate(
                        id=f"rel_{len(rels)+1}",
                        from_table=clean_name(ds.name),
                        from_column=clean_name(fields[0]),
                        to_table=clean_name(ds.name),
                        to_column=clean_name(fields[1]),
                        confidence_score=0.86,
                        reason=f"Defined in Tableau relation/join: {r.name}",
                        manual_review=False,
                    ))
    # Profile and semantic matching. Keep only strong, key-like candidates to reduce false positives.
    tables = project.semantic_tables
    for left, right in itertools.combinations(tables, 2):
        table_candidates: list[RelationshipCandidate] = []
        for lc in left.columns:
            for rc in right.columns:
                lname = str(lc.get("name", ""))
                rname = str(rc.get("name", ""))
                if not (_is_likely_key(lname, lc) or _is_likely_key(rname, rc)):
                    continue
                score, reasons = _score_pair(lname, rname, lc, rc)
                if score >= 0.65:
                    table_candidates.append(RelationshipCandidate(
                        id="pending",
                        from_table=left.name,
                        from_column=clean_name(lname),
                        to_table=right.name,
                        to_column=clean_name(rname),
                        confidence_score=round(score, 2),
                        reason="Inferred by " + ", ".join(reasons),
                        manual_review=score < 0.8,
                    ))
        table_candidates.sort(key=lambda r: r.confidence_score, reverse=True)
        rels.extend(table_candidates[:3])
    # Deduplicate and re-number.
    seen = set()
    unique = []
    for r in rels:
        key = (r.from_table, r.from_column, r.to_table, r.to_column)
        rev = (r.to_table, r.to_column, r.from_table, r.from_column)
        if key not in seen and rev not in seen:
            seen.add(key)
            r.id = f"rel_{len(unique)+1}"
            unique.append(r)
    return unique[:100]
