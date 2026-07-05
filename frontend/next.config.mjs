/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Same-origin proxy: the browser calls /api/* on the Next server, which forwards to the
  // FastAPI backend. Eliminates CORS and the host-vs-compose DNS mismatch (api:8000 vs localhost).
  async rewrites() {
    const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
