import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.ADMIN_API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";
const ADMIN_API_TOKEN = process.env.ADMIN_API_TOKEN || "";
const MP_API_PREFIX = "/api/v1/wechat-mp";

function normalizedApiBase() {
  return API_BASE.replace(/\/$/, "").replace(/\/api\/v1\/wechat-mp$/, "");
}

async function proxyAdmin(request: NextRequest, context: { params: { path?: string[] } }) {
  if (!ADMIN_API_TOKEN) {
    return NextResponse.json({ error: "missing_admin_api_token" }, { status: 500 });
  }

  const path = (context.params.path || []).join("/");
  const targetUrl = new URL(`${normalizedApiBase()}${MP_API_PREFIX}/admin/${path}`);
  targetUrl.search = request.nextUrl.search;

  const headers = new Headers();
  headers.set("X-Admin-Token", ADMIN_API_TOKEN);
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  const method = request.method;
  const body = method === "GET" || method === "HEAD" ? undefined : await request.text();
  const response = await fetch(targetUrl, {
    method,
    headers,
    body,
    cache: "no-store"
  });

  const responseHeaders = new Headers(response.headers);
  responseHeaders.delete("content-encoding");
  return new NextResponse(response.body, {
    status: response.status,
    headers: responseHeaders
  });
}

export const GET = proxyAdmin;
export const POST = proxyAdmin;
export const PATCH = proxyAdmin;
