// frontend/next.config.mjs
/** @type {import('next').NextConfig} */
const nextConfig = {
  // 核心修复：配置反向代理，彻底绕过浏览器的 CORS 拦截
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*' // 将所有发往 /api 的请求，悄悄转发给 FastAPI
      }
    ]
  }
};

export default nextConfig;
