import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: "*",
      allow: "/",
      disallow: ["/account", "/login", "/paper", "/learning", "/admin", "/api/"],
    },
    sitemap: "https://www.earningsfollower.com/sitemap.xml",
    host: "https://www.earningsfollower.com",
  };
}
