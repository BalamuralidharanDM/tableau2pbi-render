import { useState } from 'react';
import { Card, Badge } from '../components/Cards';
import { MigrationProject, Relationship } from '../types/project';
import { saveRelationships } from '../services/api';

export default function Relationships({ project, setProject }: {project: MigrationProject; setProject: (p: MigrationProject) => void}) {
  const [rels, setRels] = useState<Relationship[]>(project.relationships);
  const [busy, setBusy] = useState(false);
  function update(i: number, key: keyof Relationship, value: string | boolean) { const copy = [...rels]; copy[i] = {...copy[i], [key]: value}; setRels(copy); }
  function add() { setRels([...rels, {id: `manual_${Date.now()}`, from_table: '', from_column: '', to_table: '', to_column: '', cardinality: 'Many-to-one', cross_filter_direction: 'Single', active: false, confidence_score: 0, reason: 'User-created', manual_review: true}]); }
  async function save() { setBusy(true); try { setProject(await saveRelationships(project.project_id, rels)); } finally { setBusy(false); } }
  return <div className="page">
    <div className="grid2">
      <Card title="Existing Tableau Data Model"><div className="modelList">{project.datasources.map(ds => <div className="modelNode" key={String(ds.id)}><b>{String(ds.name)}</b><span>{String(ds.relations?.length || 0)} relation(s)</span><span>{String(ds.fields?.length || 0)} field(s)</span></div>)}</div></Card>
      <Card title="Equivalent Power BI Model"><div className="modelList">{project.semantic_tables.map(t => <div className="modelNode" key={t.name}><b>{t.name}</b><span>{t.columns.length} column(s)</span><span>{t.measures.length} measure(s)</span></div>)}</div></Card>
    </div>
    <Card title="Relationship Designer" right={<div className="actions"><button onClick={add}>Create relationship</button><button className="primary" onClick={save} disabled={busy}>{busy ? 'Saving...' : 'Apply relationships'}</button></div>}>
      <div className="relationshipGrid">{rels.map((r, i) => <div className="relationshipCard" key={r.id}>
        <div className="rowBetween"><b>{r.id}</b>{r.manual_review ? <Badge tone="warn">Manual review</Badge> : <Badge tone="good">Inferred</Badge>}</div>
        <label>From table<input value={r.from_table} onChange={e => update(i, 'from_table', e.target.value)}/></label>
        <label>From column<input value={r.from_column} onChange={e => update(i, 'from_column', e.target.value)}/></label>
        <label>To table<input value={r.to_table} onChange={e => update(i, 'to_table', e.target.value)}/></label>
        <label>To column<input value={r.to_column} onChange={e => update(i, 'to_column', e.target.value)}/></label>
        <label>Cardinality<select value={r.cardinality} onChange={e => update(i, 'cardinality', e.target.value)}><option>Many-to-one</option><option>One-to-one</option><option>One-to-many</option><option>Many-to-many</option></select></label>
        <label>Filter direction<select value={r.cross_filter_direction} onChange={e => update(i, 'cross_filter_direction', e.target.value)}><option>Single</option><option>Both</option></select></label>
        <label className="check"><input type="checkbox" checked={r.active} onChange={e => update(i, 'active', e.target.checked)}/> Active</label>
        <label className="check"><input type="checkbox" checked={r.manual_review} onChange={e => update(i, 'manual_review', e.target.checked)}/> Manual review</label>
        <p className="hint">Confidence {r.confidence_score}. {r.reason}</p>
      </div>)}</div>
    </Card>
  </div>;
}
