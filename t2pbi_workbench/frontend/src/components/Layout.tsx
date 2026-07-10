import { ReactNode } from 'react';
import { DatabaseZap, ShieldCheck } from 'lucide-react';

type Props = { children: ReactNode; active: string; onNav: (tab: string) => void; hasProject: boolean };

const tabs = [
  'Landing', 'Upload', '360 Summary', 'TDE Source Recovery', 'Source Overview', 'Source Mapping', 'Preview & Types', 'Relationships',
  'Calculations', 'M Query', 'Final Tables', 'Visual Plan', 'Validation', 'Export'
];

export default function Layout({ children, active, onNav, hasProject }: Props) {
  return <div className="appShell">
    <aside className="sideNav">
      <div className="brand"><DatabaseZap size={28}/><div><b>TABLEAU2PBI</b><span>Enterprise Workbench</span></div></div>
      <nav>{tabs.map(tab => <button key={tab} disabled={!hasProject && !['Landing','Upload'].includes(tab)} className={active === tab ? 'active' : ''} onClick={() => onNav(tab)}>{tab}</button>)}</nav>
      <div className="safe"><ShieldCheck size={18}/><span>Safe Openable Mode default</span></div>
    </aside>
    <main className="mainPanel">{children}</main>
  </div>;
}
