/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  poweredByHeader: false,
  eslint: { ignoreDuringBuilds: false },
  async rewrites() {
    // When NEXT_PUBLIC_API_URL is unset the app proxies /api to a local backend,
    // so browser code can always use relative URLs (§37). In production the
    // frontend talks directly to the deployed API through the env var.
    const target = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000';
    return [{ source: '/api/:path*', destination: `${target}/api/:path*` }];
  },
};
export default nextConfig;
