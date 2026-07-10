from __future__ import annotations
import re
from collections import defaultdict
from app.models.schemas import MigrationProject, ValidationIssue


def _add(issues, severity, category, object_name, message, fix=None, auto=False):
    issues.append(ValidationIssue(severity=severity, category=category, object_name=object_name, message=message, recommended_fix=fix, auto_fixable=auto))


def validate_project(project: MigrationProject) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not project.inventory:
        _add(issues, "error", "Upload", project.project_name, "No files were inventoried.", "Upload a .twb/.twbx/.tds/.tdsx/.zip package.")
    if not any(i.role in {"Workbook", "Data source", "Packaged workbook", "Packaged data source"} for i in project.inventory):
        _add(issues, "warning", "Inventory", project.project_name, "No Tableau workbook or data-source XML was found.", "Upload primary .twb or .tds metadata, or package file.")
    if any(i.extension.lower() in {".zip", ".twbx", ".tdsx", ".tflx"} for i in project.inventory) and len(project.inventory) <= 1:
        _add(issues, "error", "Package Extraction", project.project_name, "Package content was not extracted; inventory contains only the uploaded package row.", "Restart V6 backend, confirm health shows version 6.x and workspace C:\\T2PBI_RUNTIME\\workspace, then upload again.", True)

    for item in project.inventory:
        if item.errors:
            _add(issues, "warning", "Inventory", item.file_name, "; ".join(item.errors), "Review package file integrity or upload the file separately.")

    for m in project.source_mappings:
        mapping_text = " ".join(str(x or "") for x in [m.original_connection_type, m.detected_source_path, m.target_file_path, m.datasource]).lower()
        is_tde = ".tde" in mapping_text or "tableau extract .tde" in mapping_text
        if is_tde:
            _add(issues, "warning", "TDE Strategy", m.datasource, "Legacy .tde mapping must not be used as refreshable production source.", "Recover original source systems and transformation logic; use TDE only as validation baseline or temporary static export.")
        elif m.target_connector == "Manual source placeholder":
            _add(issues, "warning", "Source Mapping", m.datasource, "Source requires manual Power BI connector mapping.", "Open Source Mapping and select a target connector/source path.")
        if m.target_connector in {"SQL Server", "Oracle", "PostgreSQL", "MySQL", "Snowflake", "Databricks", "BigQuery", "Azure SQL"} and not (m.server_name or m.sql_query):
            _add(issues, "warning", "Source Mapping", m.datasource, "Database source has no server or native SQL target configured.", "Enter target server/database/schema/table or confirm native SQL mapping.")
        if m.sql_query and not m.sql_query.strip():
            _add(issues, "warning", "Source Mapping", m.datasource, "SQL query mapping is empty.", "Provide SQL text or replace with table mapping.")

    for t in project.semantic_tables:
        if not t.m_query or not re.search(r"(?is)\blet\b.+\bin\b", t.m_query or ""):
            _add(issues, "error", "Power Query", t.name, "Generated M query does not have a valid let/in structure.", "Regenerate M after updating source mapping.", True)
        if t.m_query and re.search(r"\b(SUM|AVG|COUNTD|WINDOW_|RUNNING_|LOOKUP|RANK)\s*\(\s*\[", t.m_query, flags=re.I):
            _add(issues, "error", "Power Query", t.name, "Tableau aggregate/table-calculation expression appears in Power Query M.", "Move aggregation/table calculation logic to DAX/manual review.", True)
        if t.m_query and re.search(r"\b(FIXED|INCLUDE|EXCLUDE|WINDOW_|RUNNING_|LOOKUP|PREVIOUS_VALUE)\b", t.m_query, flags=re.I):
            _add(issues, "error", "Power Query", t.name, "Tableau-only calculation syntax appears in M query.", "Regenerate M and keep Tableau-specific calculation in DAX/manual-review artifacts.", True)

    table_columns = {(t.name, c.get("name")) for t in project.semantic_tables for c in t.columns}
    active_pairs = defaultdict(list)
    for r in project.relationships:
        if (r.from_table, r.from_column) not in table_columns:
            _add(issues, "warning", "Relationship", r.id, f"From column {r.from_table}[{r.from_column}] was not found in semantic model.", "Edit or remove the relationship in Relationship Designer.", True)
        if (r.to_table, r.to_column) not in table_columns:
            _add(issues, "warning", "Relationship", r.id, f"To column {r.to_table}[{r.to_column}] was not found in semantic model.", "Edit or remove the relationship in Relationship Designer.", True)
        if r.active and not r.manual_review:
            key = tuple(sorted([(r.from_table, r.to_table), (r.from_column, r.to_column)]))
            active_pairs[key].append(r.id)
        if r.active and r.manual_review:
            _add(issues, "warning", "Relationship", r.id, "Relationship is active but marked manual review.", "Deactivate until cardinality/filter direction is confirmed.", True)
    for key, ids in active_pairs.items():
        if len(ids) > 1:
            _add(issues, "warning", "Relationship", ", ".join(ids), "Duplicate active relationship candidates may create ambiguity.", "Deactivate duplicates and keep only the validated relationship.", True)

    for calc in project.calculations:
        if calc.confidence_score < 0.7:
            _add(issues, "warning", "DAX", calc.name, "Calculation requires manual review due to low conversion confidence.", "Validate generated expression against Tableau output.")
        if calc.target_object_type in {"measure_manual_review", "manual_review"}:
            _add(issues, "info", "DAX Safe Mode", calc.name, "Calculation is preserved in manual review and excluded from safe semantic export.", "Review manually before adding to Power BI model.")

    if not project.reconciliation_plan:
        _add(issues, "warning", "Reconciliation", project.project_name, "No reconciliation plan was generated.", "Run validation again or reload project.")
    return issues


def health_from_issues(issues: list[ValidationIssue]) -> str:
    if any(i.severity == "error" for i in issues):
        return "Blocked"
    if any(i.severity == "warning" for i in issues):
        return "Ready with warnings"
    return "Ready"
