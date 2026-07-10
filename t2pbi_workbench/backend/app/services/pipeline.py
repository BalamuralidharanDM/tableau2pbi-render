from __future__ import annotations
from pathlib import Path
from app.core.name_sanitizer import clean_name
from app.models.schemas import MigrationProject, SemanticTable, ValidationIssue
from app.services.data_profiler import preview_mapping
from app.services.inventory_engine import build_inventory, extract_package, list_zip_members_as_inventory
from app.services.relationship_builder import infer_relationships
from app.services.source_mapping import build_source_mappings
from app.services.tableau_parser import parse_workbook_or_datasource
from app.services.visual_planner import build_visual_plan
from app.services.migration_strategy import build_migration_decisions, build_reconciliation_plan, add_strategy_validation_issues, add_tde_validation_issues, build_tde_analysis, is_tableau_generated_field
from app.translators.dax_translator import classify_and_translate
from app.translators.m_generator import generate_m_query
from app.validators.rules import validate_project, health_from_issues


def _summary(project: MigrationProject, workbook_meta: dict | None = None) -> dict:
    joins = sum(1 for ds in project.datasources for r in ds.relations if "join" in (r.relation_type or "").lower())
    unions = sum(1 for ds in project.datasources for r in ds.relations if "union" in (r.relation_type or "").lower())
    custom_sql = sum(1 for ds in project.datasources for r in ds.relations if r.custom_sql)
    relationships = len(project.relationships)
    unsupported = sum(1 for c in project.calculations if c.confidence_score < 0.7)
    blocked = len([i for i in project.validation_issues if i.severity == "error"])
    manual_sources = len([m for m in project.source_mappings if m.target_connector == "Manual source placeholder"])
    score = 100
    score -= min(40, unsupported * 5)
    score -= min(20, manual_sources * 3)
    score -= min(20, blocked * 10)
    workbook_count = len([i for i in project.inventory if i.extension.lower() == ".twb"])
    manual_review_items = sum(1 for d in project.migration_decisions if d.get("manual_review"))
    return {
        "Workbook name": (workbook_meta or {}).get("workbook_name", project.project_name),
        "Tableau version": (workbook_meta or {}).get("version", "Unknown"),
        "Inventory files": len(project.inventory),
        "Workbook files": workbook_count,
        "Dashboards": len(project.dashboards),
        "Worksheets": len(project.worksheets),
        "Stories": len(project.stories),
        "Data sources": len(project.datasources),
        "Source mappings": len(project.source_mappings),
        "Connections": sum(len(ds.connections) for ds in project.datasources),
        "Logical tables": len(project.datasources),
        "Physical tables": sum(len(ds.relations) for ds in project.datasources),
        "Joins": joins,
        "Relationships": relationships,
        "Unions": unions,
        "Custom SQL queries": custom_sql,
        "Calculated fields": len(project.calculations),
        "Parameters": len(project.parameters),
        "Filters": sum(len(ds.filters) for ds in project.datasources) + sum(len(w.filters) for w in project.worksheets),
        "Sets/groups/bins": "Inventory/manual review",
        "Extract files": len([i for i in project.inventory if i.role in {"Hyper extract", "Legacy TDE extract"}]),
        "Unsupported objects": unsupported,
        "Migration readiness score": max(score, 0),
        "Manual review decisions": manual_review_items,
        "TDE strategy scenario": (project.tde_analysis[0].get("scenario") if project.tde_analysis else "No legacy TDE detected"),
        "TDE source-of-truth rule": ("TDE is validation/fallback only" if project.tde_analysis else "N/A"),
        "Reconciliation checkpoints": len(project.reconciliation_plan),
        "Power BI export readiness": project.health_status,
    }


def _build_semantic_tables(project: MigrationProject) -> list[SemanticTable]:
    tables: list[SemanticTable] = []
    preview_by_source = {p.source_id: p for p in project.previews}
    for mapping in project.source_mappings:
        mapping_text = " ".join(str(x or "") for x in [mapping.original_connection_type, mapping.detected_source_path, mapping.target_file_path, mapping.mapping_status]).lower()
        if ".tde" in mapping_text or mapping.mapping_status.lower().startswith("legacy tde"):
            # Legacy TDE must not become a production Power BI table. It remains visible in source mapping,
            # TDE strategy, lineage, and validation artifacts only.
            continue
        table_name = clean_name(mapping.table_name or mapping.datasource)
        preview = preview_by_source.get(mapping.source_id)
        cols = []
        if preview and preview.columns:
            cols = [
                {
                    "name": clean_name(c.column_name),
                    "source_name": c.column_name,
                    "data_type": c.override_type or c.detected_type,
                    "possible_key": c.possible_key,
                    "role": c.dimension_or_measure,
                }
                for c in preview.columns
            ]
        else:
            ds = next((d for d in project.datasources if d.name == mapping.datasource), None)
            if ds:
                cols = [
                    {"name": clean_name(f.name), "source_name": f.name, "data_type": f.datatype or "Text", "possible_key": False, "role": f.role or "dimension"}
                    for f in ds.fields
                    if not f.is_calculated and not f.is_parameter and not is_tableau_generated_field(f.name)
                ]
        try:
            m_query = generate_m_query(table_name, mapping, preview)
        except Exception as exc:
            m_query = f"let\n    Source = #table({{}}, {{}})\nin\n    Source"
            project.validation_issues.append(ValidationIssue(
                severity="warning",
                category="M Query Generation",
                object_name=table_name,
                message=f"M generation fallback used: {exc}",
                recommended_fix="Review source mapping and datatype overrides, then regenerate M.",
            ))
        table = SemanticTable(
            name=table_name,
            source_id=mapping.source_id,
            columns=cols,
            m_query=m_query,
            lineage=[f"Datasource: {mapping.datasource}", f"Connector: {mapping.target_connector}", f"Detected path: {mapping.detected_source_path or mapping.target_file_path or 'N/A'}"],
        )
        tables.append(table)
    by_ds = {t.name: t for t in tables}
    for calc in project.calculations:
        target_name = clean_name(calc.datasource or (tables[0].name if tables else "MigratedTable"))
        if target_name not in by_ds and tables:
            target_name = tables[0].name
        if target_name in by_ds:
            if calc.target_object_type == "measure" and calc.confidence_score >= 0.70:
                by_ds[target_name].measures.append({"name": clean_name(calc.name), "expression": calc.generated_expression, "description": f"Converted from Tableau: {calc.formula}", "confidence": calc.confidence_score})
            elif calc.target_object_type == "calculated_column" and calc.confidence_score >= 0.70:
                by_ds[target_name].columns.append({"name": clean_name(calc.name), "data_type": calc.return_type or "Text", "calculated": True, "expression": calc.generated_expression, "confidence": calc.confidence_score})
    return tables


def _merge_datasources_by_name(datasources):
    merged = {}
    for ds in datasources:
        key = clean_name(ds.name).lower()
        if key not in merged:
            merged[key] = ds
            continue
        target = merged[key]
        existing_conn = {(c.connection_type, c.local_file_path, c.server, c.database, c.table_name) for c in target.connections}
        for c in ds.connections:
            ckey = (c.connection_type, c.local_file_path, c.server, c.database, c.table_name)
            if ckey not in existing_conn:
                target.connections.append(c)
                existing_conn.add(ckey)
        existing_fields = {clean_name(f.name).lower() for f in target.fields}
        for f in ds.fields:
            fkey = clean_name(f.name).lower()
            if fkey not in existing_fields:
                target.fields.append(f)
                existing_fields.add(fkey)
        existing_rel = {(r.name, r.relation_type, r.table, r.custom_sql) for r in target.relations}
        for r in ds.relations:
            rkey = (r.name, r.relation_type, r.table, r.custom_sql)
            if rkey not in existing_rel:
                target.relations.append(r)
                existing_rel.add(rkey)
        target.filters.extend([f for f in ds.filters if f not in target.filters])
        target.warnings.extend([w for w in ds.warnings if w not in target.warnings])
    return list(merged.values())


def _dedupe_by_key(items, key_fn):
    out = {}
    for item in items:
        out[key_fn(item)] = item
    return list(out.values())


def _safe_stage(project: MigrationProject, category: str, object_name: str, exc: Exception) -> None:
    project.validation_issues.append(ValidationIssue(
        severity="warning",
        category=category,
        object_name=object_name,
        message=str(exc),
        recommended_fix="The item was skipped so the rest of the migration can continue. Review the inventory/validation report.",
    ))


def run_pipeline(project: MigrationProject, uploaded_paths: list[Path]) -> MigrationProject:
    workspace = Path(project.workspace_path).resolve()
    project.workspace_path = str(workspace)
    discovered_files: list[Path] = []
    discovered_files.extend([Path(p).resolve() for p in uploaded_paths if Path(p).exists()])

    virtual_inventory = []
    for p in uploaded_paths:
        try:
            extracted = extract_package(Path(p), workspace / "extracted")
            discovered_files.extend(extracted)
            # If a package extracted to no files, make it visible as a package issue instead of silently continuing.
            if Path(p).suffix.lower() in {".zip", ".twbx", ".tdsx", ".tflx"} and not extracted:
                virtual_inventory.extend(list_zip_members_as_inventory(Path(p), workspace, "package extraction returned no files"))
        except Exception as exc:
            _safe_stage(project, "Package Extraction", Path(p).name, exc)
            if Path(p).suffix.lower() in {".zip", ".twbx", ".tdsx", ".tflx"}:
                virtual_inventory.extend(list_zip_members_as_inventory(Path(p), workspace, str(exc)))

    project.inventory = build_inventory(discovered_files, workspace) + virtual_inventory

    workbook_meta: dict | None = None
    for item in project.inventory:
        if str(item.absolute_path).startswith("zip://"):
            continue
        path = Path(item.absolute_path)
        if path.suffix.lower() in {".twb", ".tds", ".tfl"}:
            if not path.exists():
                item.parsed_status = "Skipped"
                item.errors.append("File was listed but no longer exists in workspace. Upload package again or clear workspace.")
                continue
            try:
                parsed = parse_workbook_or_datasource(path)
                workbook_meta = workbook_meta or {"workbook_name": parsed.get("workbook_name"), "version": parsed.get("version")}
                project.datasources.extend(parsed.get("datasources", []))
                project.worksheets.extend(parsed.get("worksheets", []))
                project.dashboards.extend(parsed.get("dashboards", []))
                project.stories.extend(parsed.get("stories", []))
                project.parameters.extend(parsed.get("parameters", []))
                project.calculations.extend(parsed.get("calculations", []))
                item.parsed_status = "Parsed"
            except Exception as exc:
                item.parsed_status = "Error"
                item.errors.append(str(exc))
                _safe_stage(project, "Tableau XML Parse", item.file_name, exc)

    project.datasources = _merge_datasources_by_name(project.datasources)
    project.worksheets = _dedupe_by_key(project.worksheets, lambda w: w.name)
    project.dashboards = _dedupe_by_key(project.dashboards, lambda d: d.name)
    project.stories = _dedupe_by_key(project.stories, lambda s: s.name)
    project.calculations = _dedupe_by_key(project.calculations, lambda c: (c.datasource, c.name, c.formula))
    project.parameters = _dedupe_by_key(project.parameters, lambda p: p.name)

    try:
        project.source_mappings = build_source_mappings(project)
    except Exception as exc:
        _safe_stage(project, "Source Mapping", project.project_name, exc)
        project.source_mappings = []

    previews = []
    for m in project.source_mappings:
        try:
            previews.append(preview_mapping(m, workspace))
        except Exception as exc:
            _safe_stage(project, "Data Preview", m.datasource, exc)
    project.previews = previews

    default_table = clean_name(project.source_mappings[0].datasource if project.source_mappings else project.project_name)
    converted_calcs = []
    for c in project.calculations:
        try:
            converted_calcs.append(classify_and_translate(c, clean_name(c.datasource or default_table)))
        except Exception as exc:
            c.warnings.append(f"Conversion failed and was moved to manual review: {exc}")
            c.target_object_type = "manual_review"
            c.confidence_score = 0.0
            converted_calcs.append(c)
    project.calculations = converted_calcs

    project.semantic_tables = _build_semantic_tables(project)
    try:
        project.relationships = infer_relationships(project)
    except Exception as exc:
        _safe_stage(project, "Relationship Inference", project.project_name, exc)
        project.relationships = []
    try:
        project.visual_plan = build_visual_plan(project.worksheets)
    except Exception as exc:
        _safe_stage(project, "Visual Planning", project.project_name, exc)
        project.visual_plan = []

    # Migration strategy is the compiler decision layer: migrate business logic, not Tableau mechanics.
    try:
        project.tde_analysis = build_tde_analysis(project)
        project.migration_decisions = build_migration_decisions(project)
        project.reconciliation_plan = build_reconciliation_plan(project)
        add_strategy_validation_issues(project, project.migration_decisions)
        add_tde_validation_issues(project, project.tde_analysis)
    except Exception as exc:
        _safe_stage(project, "Migration Strategy", project.project_name, exc)
        project.migration_decisions = []
        project.reconciliation_plan = []
        project.tde_analysis = []

    # Preserve warnings collected during resilient stages, then append normal validation output.
    resilient_issues = list(project.validation_issues)
    project.validation_issues = resilient_issues + validate_project(project)
    project.health_status = health_from_issues(project.validation_issues)
    project.summary = _summary(project, workbook_meta)
    return project
