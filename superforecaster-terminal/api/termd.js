const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

export default async function handler(req, res) {
  const baseUrl = process.env.TERMD_API_BASE_URL;
  const token = process.env.TERMD_API_TOKEN;

  if (!baseUrl) {
    res.status(500).json({ error: "TERMD_API_BASE_URL is not configured" });
    return;
  }

  if (req.method === "OPTIONS") {
    res.setHeader("access-control-allow-methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS");
    res.setHeader("access-control-allow-headers", "authorization,content-type,if-none-match");
    res.status(204).end();
    return;
  }

  const incoming = new URL(req.url, `https://${req.headers.host ?? "localhost"}`);
  const rewrittenPath = incoming.searchParams.get("path");
  incoming.searchParams.delete("path");

  const fallbackPath = incoming.pathname.replace(/^\/api\/termd\/?/, "/");
  const targetPath = normalizeTargetPath(rewrittenPath ?? fallbackPath);
  const target = new URL(`${targetPath}${incoming.search}`, baseUrl);
  const headers = new Headers();

  for (const [key, value] of Object.entries(req.headers)) {
    if (!value || HOP_BY_HOP_HEADERS.has(key.toLowerCase())) continue;
    if (Array.isArray(value)) {
      for (const entry of value) headers.append(key, entry);
    } else {
      headers.set(key, value);
    }
  }
  if (token) headers.set("authorization", `Bearer ${token}`);
  headers.set("accept", headers.get("accept") ?? "application/json");

  const upstream = await fetch(target, {
    method: req.method,
    headers,
    body: req.method === "GET" || req.method === "HEAD" ? undefined : await readRequestBody(req),
  });

  for (const [key, value] of upstream.headers.entries()) {
    if (!HOP_BY_HOP_HEADERS.has(key.toLowerCase())) res.setHeader(key, value);
  }

  res.status(upstream.status);
  const body = Buffer.from(await upstream.arrayBuffer());
  res.end(body);
}

function normalizeTargetPath(path) {
  if (!path || path === "/") return "/";
  return `/${path.replace(/^\/+/, "")}`;
}

function readRequestBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}
