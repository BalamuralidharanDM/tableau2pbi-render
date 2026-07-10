from __future__ import annotations
import csv
import hashlib
import shutil
import zipfile
from pathlib import Path
from app.core.json_utils import write_json
from app.core.name_sanitizer import clean_name
from app.models.schemas import MigrationProject


def _safe_file_stem(value: str | None, fallback: str = "Object", max_len: int = 72) -> str:
    cleaned = clean_name(value or fallback, fallback=fallback).replace(" ", "_")
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{cleaned[:max_len]}_{digest}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content or "", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys or ["message"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(row.get(k)) for k in keys})


def _csv_value(value):
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, ensure_ascii=False)
    return value


def _flatten_tde_rows(project: MigrationProject) -> list[dict]:
    rows = []
    for t in getattr(project, "tde_analysis", []) or []:
        for f in t.get("tde_files", []) or [{"file_name": t.get("tde_file")}]:
            rows.append({
                "tde_file": f.get("file_name") or t.get("tde_file"),
                "folder_path": f.get("folder_path"),
                "scenario": t.get("scenario"),
                "is_source_of_truth": t.get("is_source_of_truth"),
                "recommended_usage": t.get("recommended_usage"),
                "decision": t.get("decision"),
                "preferred_architecture": t.get("preferred_architecture"),
                "temporary_fallback": t.get("temporary_fallback"),
                "metadata_files_found": t.get("metadata_files_found"),
                "original_sources_detected": t.get("original_sources_detected"),
                "custom_sql_detected": bool(t.get("custom_sql_detected")),
                "multiple_upstream_sources_detected": t.get("multiple_upstream_sources_detected"),
            })
    return rows


def _tde_manual_review_rows(project: MigrationProject) -> list[dict]:
    rows = []
    for t in getattr(project, "tde_analysis", []) or []:
        for item in t.get("manual_review_required", []) or []:
            rows.append({
                "tde_file": t.get("tde_file"),
                "manual_review_item": item,
                "reason": "TDE migration must not silently convert uncertain Tableau behavior.",
                "recommended_action": "Validate with source owner and Tableau output before applying in Power BI.",
            })
        for filt in t.get("extract_filter_classification", []) or []:
            if str(filt.get("purpose", "")).startswith("Unknown"):
                rows.append({
                    "tde_file": t.get("tde_file"),
                    "manual_review_item": "Unknown extract filter purpose",
                    "object": filt.get("filter"),
                    "reason": filt.get("reason"),
                    "recommended_action": filt.get("powerbi_target"),
                })
    return rows


def _tde_column_validation_rows(project: MigrationProject) -> list[dict]:
    rows = []
    for t in getattr(project, "tde_analysis", []) or []:
        for v in t.get("source_column_validation", []) or []:
            rows.append({
                "tde_file": t.get("tde_file"),
                "source_name": v.get("source_name"),
                "source_id": v.get("source_id"),
                "target_connector": v.get("target_connector"),
                "source_path_or_table": v.get("source_path_or_table"),
                "preview_available": v.get("preview_available"),
                "source_column_count": v.get("source_column_count"),
                "source_columns": v.get("source_columns"),
                "matched_tableau_columns": v.get("matched_tableau_columns"),
                "missing_tableau_fields_for_review": v.get("missing_tableau_fields_for_review"),
                "status": v.get("status"),
                "warnings": v.get("warnings"),
            })
    return rows


def _tde_rebuild_plan(project: MigrationProject) -> str:
    lines = [
        "# TDE Rebuild Plan",
        "",
        "A Tableau .tde extract is treated as a legacy output artifact and validation baseline, not as the Power BI source of truth.",
        "The default architecture is: Original source systems -> reusable transformation layer -> Power BI semantic model -> DAX measures -> reports.",
        "",
    ]
    if not getattr(project, "tde_analysis", []):
        lines.append("No .tde extract was detected in this project.")
        return "\n".join(lines)
    for t in project.tde_analysis:
        lines.extend([
            f"## {t.get('tde_file')}",
            f"- Scenario: {t.get('scenario')}",
            f"- Decision: {t.get('decision')}",
            f"- Preferred architecture: {t.get('preferred_architecture')}",
            f"- Temporary fallback: {t.get('temporary_fallback')}",
            "",
            "### Recovered sources",
        ])
        recovered_sources = t.get("recovered_sources") or []
        if recovered_sources:
            for s in recovered_sources:
                lines.append(f"- {s.get('source_name') or s.get('name')}: {s.get('source_type') or s.get('recommended_powerbi_connector') or 'Unknown'} -> {s.get('migration_target') or 'Power Query/Dataflow/SQL staging'}")
        else:
            lines.append("- No original source was deterministically recovered. Ask for TWB/TDS/TFL metadata or source-owner details before production migration.")
        lines.extend(["", "### Recovered logic flags"])
        for k, v in (t.get("recovered_logic") or {}).items():
            lines.append(f"- {k}: {v}")
        lines.extend(["", "### Validation baseline checkpoints"])
        for v in t.get("validation_checkpoints") or []:
            lines.append(f"- {v}")
        lines.extend(["", "### Do not migrate blindly"])
        for v in t.get("omit_rules") or []:
            lines.append(f"- {v}")
        lines.append("")
    return "\n".join(lines)


def _application_capability_guide() -> str:
    return """# TABLEAU2PBI Input Package Guide

## Recommended ZIP contents
Include as many of these as available:
- Tableau workbook: .twb or .twbx
- Tableau data source: .tds or .tdsx
- Tableau Prep flow: .tfl or .tflx
- Local source files: .csv, .xlsx/.xls, .txt, .json, .xml, .parquet
- SQL scripts or view definitions used by Tableau
- Extracts: .hyper and/or legacy .tde
- TDE metadata companion file if available: *.tde.meta.json or extract_lineage.json
- Images/backgrounds/custom shapes used by dashboards
- Optional validation baselines: row counts, totals, screenshots, Tableau summary exports

## What the application can do
- Inventory the full package and nested TWBX/TDSX/TFLX contents.
- Parse Tableau XML metadata from workbook/data-source/prep files.
- Detect data sources, joins, relationships, unions, filters, calculated fields, parameters, dashboards, sheets, and visual encodings.
- Detect TDE usage, recover likely source logic from Tableau metadata, and ignore TDE as production source when original sources are present.
- Generate source mapping, previews, datatype profiling, M review files, DAX review files, semantic-model metadata, visual build plan, validation report, and migration report.

## What the application cannot guarantee automatically
- Perfect Tableau-to-Power BI visual pixel layout.
- Business validation of every metric without source-owner sign-off.
- Exact automatic conversion of complex table calculations, external scripts/model extensions, ambiguous LOD context, credentials, or unknown extract-filter intent.
- Recovery of original upstream logic from a standalone .tde file with no Tableau metadata.

## TDE rule
Do not design Power BI as Tableau TDE -> Power BI. Recover original sources and transformation logic where possible. Use TDE only as validation baseline or temporary static fallback.
"""


def _migration_report(project: MigrationProject) -> str:
    lines = [
        f"# Tableau to Power BI Migration Report - {project.project_name}",
        "",
        f"Health status: **{project.health_status}**",
        "",
        "## Executive Guidance",
        "This workbench migrates business logic, not Tableau mechanics. Safe Openable Mode keeps unsupported/ambiguous logic in lineage and manual-review artifacts instead of writing invalid Power BI objects.",
        "",
        "## Summary",
    ]
    for k, v in project.summary.items():
        lines.append(f"- {k}: {v}")
    lines.extend(["", "## Recommended ZIP Contents and Tool Scope", _application_capability_guide(), "", "## File Inventory"])
    for item in project.inventory:
        status = item.parsed_status
        warnings = f" | warnings: {'; '.join(item.warnings)}" if item.warnings else ""
        errors = f" | errors: {'; '.join(item.errors)}" if item.errors else ""
        lines.append(f"- {item.folder_path}/{item.file_name} ({item.role}) - {status}{warnings}{errors}")
    lines.extend(["", "## Data Sources"])
    for ds in project.datasources:
        lines.append(f"- {ds.name}: {len(ds.connections)} connection(s), {len(ds.fields)} field(s), {len(ds.relations)} relation(s), {len(ds.filters)} filter(s)")
    lines.extend(["", "## Source Mappings"])
    for m in project.source_mappings:
        lines.append(f"- {m.datasource}: {m.target_connector} | path={m.target_file_path or m.detected_source_path or 'N/A'} | table={m.table_name or 'N/A'} | status={m.mapping_status}")
    lines.extend(["", "## TDE Extract Analysis and Migration Strategy"])
    if not getattr(project, "tde_analysis", []):
        lines.append("No legacy Tableau .tde extracts detected.")
    for tde in getattr(project, "tde_analysis", []):
        lines.extend([
            f"### {tde.get('tde_file')}",
            f"- Scenario: {tde.get('scenario')}",
            f"- TDE role: {tde.get('tde_role')}",
            f"- Source of truth: {tde.get('is_source_of_truth')}",
            f"- Recommended usage: {tde.get('recommended_usage')}",
            f"- Decision: {tde.get('decision')}",
            f"- Preferred architecture: {tde.get('preferred_architecture')}",
            f"- Temporary fallback: {tde.get('temporary_fallback')}",
            "",
            "Recovered sources:",
        ])
        for s in tde.get("recovered_sources") or []:
            lines.append(f"- {s.get('source_name') or s.get('name')}: {s.get('source_type') or s.get('recommended_powerbi_connector') or 'Unknown'}")
        lines.append("Recovered logic flags:")
        for k, v in (tde.get("recovered_logic") or {}).items():
            lines.append(f"- {k}: {v}")
        lines.append("Extract filter classification:")
        for f in tde.get("extract_filter_classification") or []:
            lines.append(f"- {f.get('purpose')}: {f.get('powerbi_target')} | {f.get('reason')}")
    lines.extend(["", "## Visual Conversion Plan"])
    for v in project.visual_plan:
        lines.append(f"- {v.get('worksheet')}: Tableau mark {v.get('tableau_marks_type')} -> {v.get('recommended_powerbi_visual')} | fields={v.get('fields_used')}")
    lines.extend(["", "## Calculation Conversion"])
    for c in project.calculations:
        lines.append(f"- {c.name}: {c.target_object_type}, confidence {c.confidence_score}, used in {', '.join(c.used_in) if c.used_in else 'N/A'}")
        lines.append(f"  - Tableau formula: {c.formula}")
        if c.generated_expression:
            lines.append(f"  - Generated expression: {c.generated_expression}")
        if c.manual_review_notes:
            lines.append(f"  - Manual review: {'; '.join(c.manual_review_notes)}")
    lines.extend(["", "## Migration Strategy Decisions"])
    if not project.migration_decisions:
        lines.append("No migration strategy decisions were generated.")
    for d in project.migration_decisions[:500]:
        flag = "MANUAL REVIEW" if d.get("manual_review") else "AUTO/SAFE"
        lines.append(f"- [{flag}] {d.get('category')} / {d.get('object_name')}: {d.get('powerbi_target')} - {d.get('migration_decision')}")
    lines.extend(["", "## Reconciliation Plan"])
    for step in project.reconciliation_plan:
        lines.append(f"- Step {step.get('step')}: {step.get('checkpoint')} - {step.get('validation')}")
    lines.extend(["", "## Validation Issues"])
    if not project.validation_issues:
        lines.append("No validation issues detected.")
    for issue in project.validation_issues:
        lines.append(f"- [{issue.severity.upper()}] {issue.category} / {issue.object_name}: {issue.message}")
        if issue.recommended_fix:
            lines.append(f"  - Recommended fix: {issue.recommended_fix}")
    lines.append("\n## Safe Openable Mode\nUnsupported Tableau logic is preserved in lineage/review files and not forced into invalid Power BI objects.")
    return "\n".join(lines)


def _model_bim(project: MigrationProject) -> dict:
    tables = []
    for t in project.semantic_tables:
        table = {
            "name": t.name,
            "columns": [{"name": c.get("name"), "dataType": c.get("data_type", "string"), "sourceColumn": c.get("source_name") or c.get("name")} for c in t.columns],
            "measures": t.measures,
            "partitions": [{"name": f"{t.name} Partition", "source": {"type": "m", "expression": t.m_query or "let Source=#table({}, {}) in Source"}}],
        }
        tables.append(table)
    return {
        "compatibilityLevel": 1601,
        "model": {
            "culture": "en-US",
            "tables": tables,
            "relationships": [r.model_dump() for r in project.relationships if r.active and not r.manual_review],
        },
    }


def write_export(project: MigrationProject) -> Path:
    workspace = Path(project.workspace_path).resolve()
    export_root = (workspace / "exports" / f"{_safe_file_stem(project.project_name, 'TableauProject', 50)}_PowerBI_Migration_Package").resolve()
    if export_root.exists():
        shutil.rmtree(export_root, ignore_errors=True)
    export_root.mkdir(parents=True, exist_ok=True)

    write_json(export_root / "lineage" / "project_lineage.json", project.model_dump())
    write_json(export_root / "inventory" / "file_inventory.json", [i.model_dump() for i in project.inventory])
    write_json(export_root / "validation" / "validation_report.json", [i.model_dump() for i in project.validation_issues])
    write_json(export_root / "source_mapping" / "source_mapping.json", [m.model_dump() for m in project.source_mappings])
    write_json(export_root / "semantic_model" / "semantic_tables.json", [t.model_dump() for t in project.semantic_tables])
    write_json(export_root / "visuals" / "visual_build_plan.json", project.visual_plan)
    write_json(export_root / "migration_strategy" / "migration_decisions.json", project.migration_decisions)
    write_json(export_root / "migration_strategy" / "tde_extract_strategy.json", getattr(project, "tde_analysis", []))
    write_json(export_root / "migration_strategy" / "tde_recovered_logic.json", [t.get("recovered_logic_detail", {}) for t in getattr(project, "tde_analysis", [])])
    write_json(export_root / "lineage" / "tde_source_lineage.json", getattr(project, "tde_analysis", []))
    write_json(export_root / "validation" / "reconciliation_plan.json", project.reconciliation_plan)
    write_json(export_root / "validation" / "tde_reconciliation_plan.json", [p for p in project.reconciliation_plan if str(p.get("step", "")).upper() == "TDE"])
    write_json(export_root / "validation" / "tde_baseline_metrics.json", [t.get("baseline_metrics", {}) for t in getattr(project, "tde_analysis", [])])
    _write_csv(export_root / "manual_review" / "tde_manual_review_items.csv", _tde_manual_review_rows(project))
    _write_csv(export_root / "source_mapping" / "tde_source_mapping.csv", _flatten_tde_rows(project))
    _write_csv(export_root / "validation" / "tde_source_column_validation.csv", _tde_column_validation_rows(project))
    write_json(export_root / "validation" / "tde_source_column_validation.json", _tde_column_validation_rows(project))
    _write_text(export_root / "migration_strategy" / "tde_rebuild_plan.md", _tde_rebuild_plan(project))
    _write_text(export_root / "docs" / "APPLICATION_INPUT_GUIDE.md", _application_capability_guide())
    _write_text(export_root / "Migration_Report.md", _migration_report(project))

    used_names: set[str] = set()
    for idx, t in enumerate(project.semantic_tables, start=1):
        stem = _safe_file_stem(t.name or f"Table_{idx}")
        while stem.lower() in used_names:
            stem = _safe_file_stem(f"{t.name}_{idx}")
        used_names.add(stem.lower())
        _write_text(export_root / "m_queries" / f"{stem}.pq", t.m_query or "")

    used_dax: set[str] = set()
    for idx, c in enumerate(project.calculations, start=1):
        folder = "dax" if (c.target_object_type == "measure" or c.target_object_type == "calculated_column") and c.confidence_score >= 0.70 else "manual_review"
        stem = _safe_file_stem(c.name or f"Calculation_{idx}")
        while stem.lower() in used_dax:
            stem = _safe_file_stem(f"{c.name}_{idx}")
        used_dax.add(stem.lower())
        expression = c.generated_expression or "/* Manual review required */"
        _write_text(export_root / folder / f"{stem}.dax", f"// Tableau formula:\n// {c.formula}\n\n{clean_name(c.name)} = {expression}\n")

    project_stem = _safe_file_stem(project.project_name, "TableauProject", 50)
    pbip = export_root / "PowerBI_PBIP_SafeMode" / project_stem
    semantic_dir = pbip / f"{project_stem}.SemanticModel"
    report_dir = pbip / f"{project_stem}.Report"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_text(pbip / f"{project_stem}.pbip", '{"version":"1.0","artifacts":[{"report":{"path":"./' + f'{project_stem}.Report' + '"}}]}')
    _write_text(semantic_dir / "definition.pbism", '{"version":"1.0"}')
    write_json(semantic_dir / "model.bim", _model_bim(project))
    _write_text(report_dir / "definition.pbir", '{"version":"1.0","datasetReference":{"byPath":{"path":"../' + f'{project_stem}.SemanticModel' + '"}}}')
    _write_text(report_dir / "report.json", '{"sections":[]}')

    readme = f"""# Open First - TABLEAU2PBI Migration Package

Project: {project.project_name}
Health: {project.health_status}

## What is included
- Migration_Report.md
- docs/APPLICATION_INPUT_GUIDE.md
- inventory/file_inventory.json
- validation/validation_report.json
- validation/reconciliation_plan.json
- validation/tde_reconciliation_plan.json
- validation/tde_baseline_metrics.json
- source_mapping/source_mapping.json
- source_mapping/tde_source_mapping.csv
- semantic_model/semantic_tables.json
- m_queries/*.pq
- dax/*.dax
- manual_review/*.dax
- manual_review/tde_manual_review_items.csv
- visuals/visual_build_plan.json
- migration_strategy/migration_decisions.json
- migration_strategy/tde_extract_strategy.json
- migration_strategy/tde_rebuild_plan.md
- migration_strategy/tde_recovered_logic.json
- lineage/tde_source_lineage.json
- PowerBI_PBIP_SafeMode review skeleton

## Recommended Power BI workflow
1. Review validation warnings/errors first.
2. Review TDE strategy. If .tde exists, ignore it as production source and recover original sources.
3. Configure source mappings to Power BI-readable files, databases, dataflows, Fabric, or SQL views.
4. Copy M queries from m_queries into Power Query, or inspect the PBIP safe-mode semantic model.
5. Configure credentials and gateway settings in Power BI.
6. Validate generated DAX against Tableau business output using validation/reconciliation_plan.json.
7. Build visuals using the visual build plan.

Safe Openable Mode does not force unsupported Tableau visuals or ambiguous calculations into invalid Power BI artifacts.
"""
    _write_text(export_root / "README_OPEN_FIRST.txt", readme)
    _write_text(export_root / "OPEN_THIS_PBIP.cmd", f"@echo off\ncd /d %~dp0PowerBI_PBIP_SafeMode\\{project_stem}\nstart \"\" \"{project_stem}.pbip\"\n")

    zip_path = (workspace / "exports" / f"{project_stem}_PowerBI_Migration_Package.zip").resolve()
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(export_root.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(export_root.parent))
    return zip_path
