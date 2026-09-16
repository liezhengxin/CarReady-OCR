/**
 * M0 landing page.
 *
 * A stack-status view, not a product screen. Its job is to make the M0
 * acceptance criterion visible: `docker compose up` gives a working stack with
 * seeded data. The inspector capture flow lands at M1 and the dashboard at M3.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

type SystemMeta = {
  environment: string;
  api_version: string;
  synthetic_data_mode: boolean;
  grading_rubric_placeholder: boolean;
  config_versions: Record<string, string>;
};

async function getMeta(): Promise<SystemMeta | null> {
  try {
    const res = await fetch(`${API_URL}/api/meta/system`, { cache: 'no-store' });
    if (!res.ok) return null;
    return (await res.json()) as SystemMeta;
  } catch {
    return null;
  }
}

const MILESTONES = [
  { id: 'M0', label: 'Monorepo, Compose, CI, migrasi, data sintetis', done: true },
  { id: 'M1', label: 'PWA inspektur — intake 4 foto, antrean offline', done: false },
  { id: 'M2', label: 'Pipeline ICR + cross-check', done: false },
  { id: 'M3', label: 'Dashboard inventaris + antrean review', done: false },
  { id: 'M4', label: 'Katalog varian + referensi harga', done: false },
  { id: 'M5', label: 'Mesin harga (AMP)', done: false },
  { id: 'M6', label: 'Grading eksterior', done: false },
  { id: 'M7', label: 'Harga dasar + alur persetujuan', done: false },
  { id: 'M8', label: 'Hardening', done: false },
];

export default async function Home() {
  const meta = await getMeta();

  return (
    <div className="py-10">
      <h1 className="text-2xl font-bold tracking-tight">Caready</h1>
      <p className="mt-1 text-slate-600">
        Sistem inspeksi kendaraan dan penentuan harga dasar lelang
      </p>

      <section className="mt-8 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Status sistem
        </h2>
        {meta ? (
          <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-slate-500">Environment</dt>
              <dd className="font-medium">{meta.environment}</dd>
            </div>
            <div>
              <dt className="text-slate-500">API</dt>
              <dd className="font-medium">v{meta.api_version}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Mode data</dt>
              <dd className="font-medium">
                {meta.synthetic_data_mode ? 'SINTETIS' : 'produksi'}
              </dd>
            </div>
            <div>
              <dt className="text-slate-500">Rubrik grading</dt>
              <dd className="font-medium">
                {meta.grading_rubric_placeholder ? 'placeholder' : 'aktif'}
              </dd>
            </div>
            {Object.entries(meta.config_versions).map(([name, version]) => (
              <div key={name}>
                <dt className="text-slate-500">config/{name}.yaml</dt>
                <dd className="font-mono text-xs font-medium">{version}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-3 text-sm text-red-700">
            API tidak dapat dihubungi di <code className="font-mono">{API_URL}</code>.
            Jalankan <code className="font-mono">docker compose up</code>.
          </p>
        )}
      </section>

      <section className="mt-6 rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Milestone
        </h2>
        <ul className="mt-3 space-y-1.5 text-sm">
          {MILESTONES.map((m) => (
            <li key={m.id} className="flex items-baseline gap-3">
              <span
                className={`w-8 shrink-0 font-mono text-xs font-bold ${
                  m.done ? 'text-emerald-700' : 'text-slate-400'
                }`}
              >
                {m.id}
              </span>
              <span className={m.done ? 'text-slate-900' : 'text-slate-500'}>{m.label}</span>
              {m.done && <span className="text-xs text-emerald-700">selesai</span>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
