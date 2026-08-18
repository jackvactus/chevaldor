import { NextRequest, NextResponse } from "next/server";
import { getUserFromRequest } from "@/lib/auth";
import { unauthorized } from "@/lib/rbac";
import { prisma } from "@/lib/prisma";

export async function GET(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const dbUser = await prisma.user.findUnique({ where: { id: user.id } });
  if (!dbUser) return unauthorized();

  return NextResponse.json({
    id: dbUser.id,
    email: dbUser.email,
    full_name: dbUser.fullName,
    role: dbUser.role,
    company_id: dbUser.companyId,
  });
}
