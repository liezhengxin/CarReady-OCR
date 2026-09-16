'use client';

import { useEffect, useState } from 'react';

type Banner = {
  id: string;
  severity: 'info' | 'warning' | 'critical';
  title_id: string;
  body_id: string;
  dismissible: boolean;
};

type SystemMeta = {
  environment: string;
  synthetic_data_mode: boolean;
  grading_rubric_placeholder: boolean;
  banners: Banner[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

const SEVERITY_STYLES: Record<Banner['severity'], string> = {
  critical: 'bg-red-700 text-white border-red-900',
  warning: 'bg-amber-100 text-amber-950 border-amber-400',
  info: 'bg-sky-100 text-sky-950 border-sky-400',
};

/**
 * Renders the disclosure banners the API says apply to this deployment.
 *
 * Two deliberate choices:
 *
 *  - The banner list comes from the server. Whether output is synthetic, and
 *    whether the grading rubric is still a placeholder, are facts about the
 *    deployment — not client configuration someone can edit away.
 *
 *  - A non-dismissible banner stays non-dismissible. The synthetic-data notice
 *    is required by §9 and is precisely the thing that must still be visible
 *    to someone who dismissed it an hour ago.
 */
export function SystemBanners() {
  const [meta, setMeta] = useState<SystemMeta | null>(null);
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_URL}/api/meta/system`, { cache: 'no-store' })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: SystemMeta) => {
        if (!cancelled) setMeta(data);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Failing closed: if we cannot confirm this is a production deployment with
  // a signed-off rubric, we say so rather than render nothing. Silence here
  // would read as "everything is fine".
  if (failed) {
    return (
      <div className="border-b-4 border-red-900 bg-red-700 px-4 py-3 text-sm text-white">
        <strong className="block font-bold">Status sistem tidak dapat dipastikan</strong>
        Tidak dapat menghubungi API untuk memverifikasi status data. Jangan gunakan
        angka apa pun dari layar ini sebagai dasar keputusan.
      </div>
    );
  }

  if (!meta) return null;

  const visible = meta.banners.filter((b) => !b.dismissible || !dismissed.has(b.id));
  if (visible.length === 0) return null;

  return (
    <div className="sticky top-0 z-50">
      {visible.map((banner) => (
        <div
          key={banner.id}
          role={banner.severity === 'critical' ? 'alert' : 'status'}
          className={`border-b-4 px-4 py-3 text-sm ${SEVERITY_STYLES[banner.severity]}`}
        >
          <div className="mx-auto flex max-w-5xl items-start gap-3">
            <div className="flex-1">
              <strong className="block font-bold tracking-wide">{banner.title_id}</strong>
              <p className="mt-0.5 leading-snug">{banner.body_id}</p>
            </div>
            {banner.dismissible && (
              <button
                type="button"
                onClick={() => setDismissed((prev) => new Set(prev).add(banner.id))}
                className="shrink-0 rounded px-2 py-1 text-xs underline underline-offset-2"
                aria-label={`Tutup pemberitahuan ${banner.title_id}`}
              >
                Tutup
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
