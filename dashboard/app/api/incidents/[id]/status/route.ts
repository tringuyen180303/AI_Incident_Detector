import { setStatus } from "@/lib/incidents";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  try {
    const body = (await request.json()) as { status?: string };
    if (!body.status) {
      return NextResponse.json({ error: "status is required" }, { status: 400 });
    }
    return NextResponse.json(await setStatus(id, body.status));
  } catch (error) {
    const text = error instanceof Error ? error.message : "Could not update the incident.";
    const status = text === "incident not found" ? 404 : text.startsWith("status must") ? 400 : 503;
    return NextResponse.json({ error: text }, { status });
  }
}
