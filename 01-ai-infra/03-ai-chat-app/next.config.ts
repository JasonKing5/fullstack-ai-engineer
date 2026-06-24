import type { NextConfig } from "next";

const nextConfig: NextConfig = {
rewrites: async () => [
  {
    source: "/api/:path*",
    destination: "http://127.0.0.1:8000/api/:path*",
  },
],
};
module.exports = nextConfig;
