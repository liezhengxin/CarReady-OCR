import type { Metadata, Viewport } from 'next';
import './globals.css';
import { SystemBanners } from './components/SystemBanners';

export const metadata: Metadata = {
  title: 'Caready — Inspeksi & Harga Dasar Lelang',
  description: 'Sistem inspeksi kendaraan dan penentuan harga dasar lelang',
  manifest: '/manifest.webmanifest',
  applicationName: 'Caready',
  appleWebApp: { capable: true, statusBarStyle: 'default', title: 'Caready' },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  // Inspectors work one-handed in a yard. Locking zoom prevents accidental
  // pinch-zoom during capture, which is the most common way a guided overlay
  // gets misaligned.
  maximumScale: 1,
  userScalable: false,
  themeColor: '#0f172a',
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased">
        {/* Banners are driven by GET /api/meta/system, not by a client
            constant. A synthetic-data or placeholder-rubric deployment cannot
            be made to look like a production one by editing client code. */}
        <SystemBanners />
        <main className="mx-auto w-full max-w-5xl px-4 pb-16">{children}</main>
      </body>
    </html>
  );
}
