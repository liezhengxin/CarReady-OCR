/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Required by infra/docker/web.Dockerfile's runner stage.
  output: 'standalone',

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'DENY' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          // The inspector app needs the camera. It must never need the
          // gallery, and it has no business with the microphone - intake
          // capture is camera-only by design (§4.2).
          {
            key: 'Permissions-Policy',
            value: 'camera=(self), geolocation=(self), microphone=(), payment=()',
          },
        ],
      },
      {
        // The service worker must not be cached, or an offline-capable client
        // can be pinned to a stale queue implementation indefinitely.
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, no-store, must-revalidate' },
          { key: 'Service-Worker-Allowed', value: '/' },
        ],
      },
    ];
  },
};

export default nextConfig;
