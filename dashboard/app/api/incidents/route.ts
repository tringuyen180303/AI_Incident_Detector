import { listIncidents } from "@/lib/incidents";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await listIncidents());
  } catch (error) {
    return NextResponse.json({ error: message(error) }, { status: 503 });
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : "The incident store is not ready.";
}
