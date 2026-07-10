import { useState } from 'react';
import { UploadCloud } from 'lucide-react';
import { Card, Badge } from '../components/Cards';
import DataTable from '../components/DataTable';
import { MigrationProject } from '../types/project';
import { loadDemo, uploadProject } from '../services/api';

export default function Upload({ project, setProject, onLoaded }: {project?: MigrationProject; setProject: (p: MigrationProject | undefined) => void; onLoaded: () => void}) {
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  async function submit() {
    setBusy(true); setError(undefined); setProject(undefined);
    try { const p = await uploadProject(files); setProject(p); onLoaded(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function demo() {
    setBusy(true); setError(undefined); setProject(undefined);
    try { const p = await loadDemo(); setProject(p); onLoaded(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const inventoryRows = project?.inventory.map(i => ({
    folder_path: i.folder_path,
    file_name: i.file_name,
    extension: i.extension,
    role: i.role,
    status: i.parsed_status,
    size_bytes: i.size_bytes,
    associated_workbook: i.associated_workbook || '',
    associated_data_source: i.associated_data_source || '',
    associated_extract_or_source: i.associated_extract_or_source || '',
    warnings: i.warnings.join('; '),
    errors: i.errors.join('; ')
  })) || [];

  return <div className="page">
    <Card title="Upload Workspace" right={project ? <Badge tone={project.health_status === 'Blocked' ? 'bad' : 'good'}>{project.project_name}</Badge> : undefined}>
      <div className="uploadBox">
        <UploadCloud size={36}/>
        <h3>Upload Tableau files or package ZIP</h3>
        <p>Supported: .twb, .twbx, .tds, .tdsx, .hyper, .tfl, .tflx, .csv, .xlsx, .json, .xml, .zip</p>
        <input type="file" multiple onChange={e => setFiles(Array.from(e.target.files || []))}/>
        <div className="actions"><button className="primary" disabled={!files.length || busy} onClick={submit}>{busy ? 'Processing full pipeline...' : 'Upload & Parse'}</button><button onClick={demo} disabled={busy}>Load Demo Project</button></div>
        {error && <div className="error">{error}</div>}
        <div className="note">For full testing, choose the complex Tableau ZIP file and click Upload & Parse. The demo project intentionally contains only two files.</div>
      </div>
    </Card>
    {project && <Card title={`File Inventory - ${project.project_name} (${project.inventory.length} files)`}>
      <DataTable rows={inventoryRows}/>
    </Card>}
  </div>;
}
