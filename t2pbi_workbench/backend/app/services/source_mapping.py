from __future__ import annotations
from pathlib import Path
from app.core.name_sanitizer import clean_name
from app.models.schemas import MigrationProject, SourceMapping

CONNECTOR_MAP = {
    "textscan": "CSV",
    "csv": "CSV",
    "text": "Text",
    "excel": "Excel",
    "exceldirect": "Excel",
    "json": "JSON",
    "xml": "XML",
    "sqlserver": "SQL Server",
    "sqlserverlegacy": "SQL Server",
    "mysql": "MySQL",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "oracle": "Oracle",
    "snowflake": "Snowflake",
    "bigquery": "BigQuery",
    "databricks": "Databricks",
    "hyper": "Manual source placeholder",
    "dataengine": "Manual source placeholder",
    "federated": "Manual source placeholder",
    "sqlproxy": "Manual source placeholder",
    "odbc": "Manual source placeholder",
    "oledb": "Manual source placeholder",
    "web": "Web API",
    "odata": "OData",
}

LOCAL_CONNECTORS = {"CSV", "Text", "Excel", "JSON", "XML", "Parquet"}
LOCAL_FILE_EXT_TO_CONNECTOR = {
    ".csv": "CSV",
    ".txt": "Text",
    ".tsv": "Text",
    ".xlsx": "Excel",
    ".xls": "Excel",
    ".json": "JSON",
    ".xml": "XML",
    ".parquet": "Parquet",
}


def detect_connector(connection_type: str | None, local_path: str | None) -> str:
    if local_path:
        ext = Path(str(local_path).replace("\\", "/")).suffix.lower()
        if ext in LOCAL_FILE_EXT_TO_CONNECTOR:
            return LOCAL_FILE_EXT_TO_CONNECTOR[ext]
        if ext in {".hyper", ".tde"}:
            return "Manual source placeholder"
    c = (connection_type or "").lower().replace("-", "").replace("_", "")
    for key, value in CONNECTOR_MAP.items():
        if key.replace("-", "").replace("_", "") in c:
            return value
    return "Manual source placeholder"


def _path_from_inventory_item(item) -> str:
    if item.folder_path and item.folder_path not in {".", ""}:
        parts = Path(item.folder_path).parts
        # Strip runtime/extracted/package prefix and keep the business path where possible.
        for idx, part in enumerate(parts):
            if part.lower() in {"data", "datasources", "extracts", "sql", "prep", "assets"}:
                return str(Path(*parts[idx:]) / item.file_name)
    return item.file_name


def _inventory_file_map(project: MigrationProject) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in project.inventory:
        if item.extension.lower() not in (set(LOCAL_FILE_EXT_TO_CONNECTOR) | {".hyper", ".tde", ".sql"}):
            continue
        rel = _path_from_inventory_item(item)
        result[item.file_name.lower()] = rel
        result[rel.replace("\\", "/").lower()] = rel
    return result


def _resolve_inventory_path(local_path: str | None, inventory_map: dict[str, str]) -> str | None:
    if not local_path:
        return None
    normal = str(local_path).replace("\\", "/").strip()
    if not normal:
        return None
    key = normal.lower()
    if key in inventory_map:
        return inventory_map[key]
    name = Path(normal).name.lower()
    if name in inventory_map:
        return inventory_map[name]
    # Tableau often stores paths like ../data/orders.csv. Resolve by suffix match.
    for k, v in inventory_map.items():
        if k.endswith("/" + name) or k == name:
            return v
    return normal


def _mapping_key(m: SourceMapping) -> tuple[str, str, str]:
    source_path = (m.target_file_path or m.detected_source_path or "").replace("\\", "/").lower()
    if source_path:
        return (m.target_connector.lower(), source_path, (m.table_name or "").lower())
    return (m.target_connector.lower(), clean_name(m.datasource).lower(), m.original_connection_type.lower())


def build_source_mappings(project: MigrationProject) -> list[SourceMapping]:
    mappings: list[SourceMapping] = []
    inv_map = _inventory_file_map(project)

    # 1) Primary mappings from Tableau XML connection metadata.
    for ds in project.datasources:
        if not ds.connections and ds.relations:
            custom_sql = next((r.custom_sql for r in ds.relations if r.custom_sql), None)
            table_name = next((r.table or r.name for r in ds.relations if r.table or r.name), None)
            mappings.append(SourceMapping(
                source_id=ds.id,
                datasource=ds.name,
                original_connection_type="Logical/physical relation metadata",
                target_connector="Manual source placeholder" if not custom_sql else "SQL Server",
                sql_query=custom_sql,
                table_name=clean_name(table_name or ds.name),
                gateway_requirement="Review required",
                import_or_directquery="Import recommended; DirectQuery optional if connector supports it",
                credential_notes="No explicit Tableau connection node found; review relationship, join, union, extract, or custom SQL metadata.",
                parameter_values={"source": "tableau_relation_fallback"},
            ))
        for c in ds.connections:
            resolved = _resolve_inventory_path(c.local_file_path, inv_map)
            connector = detect_connector(c.connection_type, resolved or c.local_file_path)
            is_local = connector in LOCAL_CONNECTORS
            resolved_path = resolved or c.local_file_path
            lower_path = str(resolved_path or "").lower()
            mapping_status = "Detected"
            credential_notes = "Detected from Tableau metadata. Replace with Power BI gateway or credential configuration before refresh."
            import_or_directquery = "Import" if is_local else "Import recommended; DirectQuery optional if connector supports it"
            if lower_path.endswith(".tde") or ".tde" in lower_path:
                mapping_status = "Legacy TDE - validation/fallback only"
                credential_notes = "Legacy Tableau .tde detected from Tableau metadata. Ignore it as the Power BI production source; recover and use original upstream sources instead. Use TDE only as validation baseline or temporary static export fallback."
                import_or_directquery = "Do not use for production refresh; fallback static import only after Tableau export"
            mappings.append(SourceMapping(
                source_id=c.id,
                datasource=ds.name,
                original_connection_type=c.connection_type,
                detected_source_path=resolved_path,
                target_connector=connector,
                target_file_path=(resolved_path) if is_local else None,
                server_name=c.server,
                database_name=c.database,
                schema_name=c.schema_name,
                table_name=clean_name(c.table_name or Path(str(resolved_path or ds.name)).stem),
                sql_query=c.custom_sql,
                gateway_requirement="Optional / depends on location" if is_local else "Required / review",
                import_or_directquery=import_or_directquery,
                credential_notes=credential_notes,
                mapping_status=mapping_status,
                parameter_values={"source": "tableau_connection", "raw_local_file_path": c.local_file_path, "source_of_truth": "false" if mapping_status.startswith("Legacy TDE") else "true"},
            ))

    # 2) Always add physical data files from inventory if missing from XML.
    existing_paths = {
        (m.target_file_path or m.detected_source_path or "").replace("\\", "/").lower()
        for m in mappings
        if (m.target_file_path or m.detected_source_path)
    }
    for item in project.inventory:
        ext = item.extension.lower()
        folder_parts = {p.lower() for p in Path(item.folder_path).parts}
        if folder_parts & {"metadata", "docs"}:
            continue
        rel_path = _path_from_inventory_item(item)
        rel_key = rel_path.replace("\\", "/").lower()
        if ext in LOCAL_FILE_EXT_TO_CONNECTOR and rel_key not in existing_paths:
            connector = LOCAL_FILE_EXT_TO_CONNECTOR[ext]
            mappings.append(SourceMapping(
                source_id=f"inventory_{clean_name(rel_path)}",
                datasource=clean_name(Path(item.file_name).stem),
                original_connection_type=f"Inventory file {ext}",
                detected_source_path=rel_path,
                target_connector=connector,
                target_file_path=rel_path,
                table_name=clean_name(Path(item.file_name).stem),
                gateway_requirement="Optional / depends on location",
                import_or_directquery="Import",
                credential_notes="Detected from uploaded package inventory; confirm the final Power BI-readable path.",
                parameter_values={"source": "inventory_fallback", "absolute_path": item.absolute_path},
            ))
            existing_paths.add(rel_key)
        elif ext in {".hyper", ".tde"} and rel_key not in existing_paths:
            if ext == ".tde":
                notes = (
                    "Legacy Tableau .tde detected. Do not use as the Power BI production source. "
                    "Recover original sources/transformation logic from TWB/TDS metadata where possible; use TDE only as validation baseline or temporary exported snapshot."
                )
                mapping_status = "Legacy TDE - validation/fallback only"
                import_mode = "Fallback static import only after Tableau export; production should refresh from original sources"
            else:
                notes = "Tableau Hyper extract detected. Prefer original sources for production; Hyper metadata/preview may be used for validation if Tableau Hyper API is configured."
                mapping_status = "Extract - review original source"
                import_mode = "Import after replacing extract with original source or validated Hyper export"
            mappings.append(SourceMapping(
                source_id=f"extract_{clean_name(rel_path)}",
                datasource=clean_name(Path(item.file_name).stem),
                original_connection_type=f"Tableau extract {ext}",
                detected_source_path=rel_path,
                target_connector="Manual source placeholder",
                target_file_path=None,
                table_name=clean_name(Path(item.file_name).stem),
                gateway_requirement="Review required",
                import_or_directquery=import_mode,
                credential_notes=notes,
                mapping_status=mapping_status,
                parameter_values={"source": "extract_inventory", "absolute_path": item.absolute_path, "source_of_truth": "false", "validation_baseline": "true"},
            ))
            existing_paths.add(rel_key)
        elif ext == ".sql" and rel_key not in existing_paths:
            sql_text = ""
            try:
                sql_text = Path(item.absolute_path).read_text(encoding="utf-8", errors="ignore")[:20000]
            except Exception:
                pass
            mappings.append(SourceMapping(
                source_id=f"sql_{clean_name(rel_path)}",
                datasource=clean_name(Path(item.file_name).stem),
                original_connection_type="Custom SQL file",
                detected_source_path=rel_path,
                target_connector="SQL Server",
                table_name=clean_name(Path(item.file_name).stem),
                sql_query=sql_text,
                gateway_requirement="Required",
                import_or_directquery="Import recommended; DirectQuery optional if connector supports it",
                credential_notes="Custom SQL file detected from uploaded package. Confirm target server/database before generating production M.",
                parameter_values={"source": "sql_file_inventory", "absolute_path": item.absolute_path},
            ))
            existing_paths.add(rel_key)

    # 3) Deduplicate while preserving useful provenance notes.
    dedup: dict[tuple[str, str, str], SourceMapping] = {}
    for m in mappings:
        key = _mapping_key(m)
        if key not in dedup:
            dedup[key] = m
        else:
            existing = dedup[key]
            sources = set(str(existing.parameter_values.get("source", "")).split(","))
            sources.add(str(m.parameter_values.get("source", "")))
            existing.parameter_values["source"] = ",".join(sorted(s for s in sources if s))
            note = existing.credential_notes or ""
            if m.datasource and m.datasource not in note:
                existing.credential_notes = (note + f" Also referenced by {m.datasource}.").strip()
    return list(dedup.values())
