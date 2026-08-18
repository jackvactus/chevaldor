import { NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  try {
    await prisma.$queryRaw`SELECT 1`;
    return NextResponse.json({ status: "ok", db: "ok" });
  } catch (err) {
    return NextResponse.json(
      { status: "error", db: "unreachable", message: (err as Error).message },
      { status: 503 }
    );
  }
}
