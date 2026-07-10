import { Card, Metric } from '../components/Cards';
import DataTable from '../components/DataTable';
import { MigrationProject } from '../types/project';

export default function FinalTables({ project }: {project: MigrationProject}) {
  return <div className="page">
    {project.semantic_tables.map(t => <Card key={t.name} title={`Final Table Review - ${t.name}`}>
      <div className="metricsGrid"><Metric label="Columns" value={t.columns.length}/><Metric label="Measures" value={t.measures.length}/><Metric label="Included in export" value={t.include_in_export ? 'Yes' : 'No'}/><Metric label="Source" value={t.source_id || '-'}/></div>
      <h4>Lineage</h4><ul>{t.lineage.map(l => <li key={l}>{l}</li>)}</ul>
      <h4>Columns</h4><DataTable rows={t.columns as Record<string, unknown>[]}/>
      <h4>Measures</h4><DataTable rows={t.measures as Record<string, unknown>[]}/>
    </Card>)}
  </div>;
}
