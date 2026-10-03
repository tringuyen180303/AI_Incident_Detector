import { listNotifications } from "@/lib/incidents";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await listNotifications());
  } catch (error) {
    const text = error instanceof Error ? error.message : "Alerts are not ready.";
    return NextResponse.json({ error: text }, { status: 503 });
  }
}
