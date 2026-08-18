import { NextRequest, NextResponse } from "next/server";
import { getUserFromRequest } from "@/lib/auth";
import { unauthorized } from "@/lib/rbac";
import { nextDocumentNumber } from "@/lib/numbering";

export async function GET(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const number = await nextDocumentNumber("invoice", "F");
  return NextResponse.json({ number });
}
