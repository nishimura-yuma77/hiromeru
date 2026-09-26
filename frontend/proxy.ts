import { type NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-hiromeru-path", `${request.nextUrl.pathname}${request.nextUrl.search}`);
  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  matcher: [
    "/chat/:path*",
    "/campaigns/:path*",
    "/posts/:path*",
    "/metrics/:path*",
    "/memories/:path*",
  ],
};
