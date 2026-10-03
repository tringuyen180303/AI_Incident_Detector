import { readStats } from "@/lib/incidents";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await readStats());
  } catch (error) {
    const text = error instanceof Error ? error.message : "The incident store is not ready.";
    return NextResponse.json({ error: text }, { status: 503 });
  }
}
