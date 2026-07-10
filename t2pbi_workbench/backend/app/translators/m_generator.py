from __future__ import annotations
from app.core.name_sanitizer import clean_name
from app.models.schemas import DataPreview, SourceMapping

PBI_TYPE = {
    "Text": "type text",
    "Whole Number": "Int64.Type",
    "Decimal Number": "type number",
    "Fixed Decimal / Currency": "Currency.Type",
    "Date": "type date",
    "DateTime": "type datetime",
    "Time": "type time",
    "True/False": "type logical",
    "Binary": "type binary",
    "Any": "type any",
}


def _m_text(value: str | None) -> str:
    return '"' + (value or "").replace('"', '""') + '"'


def _source_step(mapping: SourceMapping) -> str:
    connector = mapping.target_connector
    path = mapping.target_file_path or mapping.detected_source_path or "<provide path>"
    if connector == "CSV":
        return f"Source_Read = Csv.Document(File.Contents({_m_text(path)}), [Delimiter=\",\", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n    Promote_Source_Headers = Table.PromoteHeaders(Source_Read, [PromoteAllScalars=true])"
    if connector == "Text":
        return f"Source_Read = Csv.Document(File.Contents({_m_text(path)}), [Delimiter=\"\t\", Encoding=65001, QuoteStyle=QuoteStyle.None]),\n    Promote_Source_Headers = Table.PromoteHeaders(Source_Read, [PromoteAllScalars=true])"
    if connector == "Excel":
        return f"Source_Read = Excel.Workbook(File.Contents({_m_text(path)}), null, true),\n    Promote_Source_Headers = Source_Read /* Select required sheet/table in Source Mapping screen */"
    if connector == "JSON":
        return f"Source_Read = Json.Document(File.Contents({_m_text(path)})),\n    Promote_Source_Headers = try Table.FromRecords(Source_Read) otherwise Table.FromList(Source_Read, Splitter.SplitByNothing(), null, null, ExtraValues.Error)"
    if connector == "XML":
        return f"Source_Read = Xml.Tables(File.Contents({_m_text(path)})),\n    Promote_Source_Headers = Source_Read"
    if connector == "Parquet":
        return f"Source_Read = Parquet.Document(File.Contents({_m_text(path)})),\n    Promote_Source_Headers = Source_Read"
    if connector == "SQL Server":
        server = mapping.server_name or "<server>"
        db = mapping.database_name or "<database>"
        if mapping.sql_query:
            return f"Source_Read = Sql.Database({_m_text(server)}, {_m_text(db)}),\n    Promote_Source_Headers = Value.NativeQuery(Source_Read, {_m_text(mapping.sql_query)}, null, [EnableFolding=true])"
        schema = mapping.schema_name or "dbo"
        table = mapping.table_name or "<table>"
        return f"Source_Read = Sql.Database({_m_text(server)}, {_m_text(db)}),\n    Promote_Source_Headers = Source_Read{{[Schema={_m_text(schema)}, Item={_m_text(table)}]}}[Data]"
    if connector in {"PostgreSQL", "MySQL", "Oracle", "Snowflake", "Databricks", "BigQuery", "Azure SQL", "OData", "Web API", "SharePoint Folder", "OneLake/Fabric Lakehouse"}:
        return f"Source_Read = #table({{}}, {{}}),\n    Promote_Source_Headers = Source_Read /* Configure {connector} connector in Power BI. This placeholder is intentionally safe. */"
    return "Source_Read = #table({}, {}),\n    Promote_Source_Headers = Source_Read /* Manual source placeholder: update mapping before refresh. */"


def generate_m_query(table_name: str, mapping: SourceMapping, preview: DataPreview | None) -> str:
    cols = []
    if preview and preview.columns:
        for c in preview.columns:
            dtype = c.override_type or c.detected_type or "Text"
            cols.append(f"{{{_m_text(c.column_name)}, {PBI_TYPE.get(dtype, 'type any')}}}")
    type_pairs = ", ".join(cols)
    type_step = "ChangedType_EnforcedPowerBITypes_FINAL = Table.TransformColumnTypes(Promote_Source_Headers, {" + type_pairs + "}, \"en-US\")" if cols else "ChangedType_EnforcedPowerBITypes_FINAL = Promote_Source_Headers"
    return f"""let
    {_source_step(mapping)},
    Safe_Convert_Values_To_Selected_Types = try Promote_Source_Headers otherwise #table({{}}, {{}}),
    {type_step}
in
    ChangedType_EnforcedPowerBITypes_FINAL
"""
