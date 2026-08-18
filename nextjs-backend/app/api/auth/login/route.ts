import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { signToken, verifyPassword } from "@/lib/auth";

const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1),
});

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = LoginSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: "Email et mot de passe requis" }, { status: 422 });
  }

  const { email, password } = parsed.data;
  const user = await prisma.user.findUnique({ where: { email: email.toLowerCase() } });

  if (!user || !user.isActive || !(await verifyPassword(password, user.passwordHash))) {
    return NextResponse.json({ detail: "Identifiants invalides" }, { status: 401 });
  }

  const token = await signToken({
    id: user.id,
    email: user.email,
    role: user.role,
    companyId: user.companyId,
  });

  return NextResponse.json({
    access_token: token,
    token_type: "bearer",
    user: {
      id: user.id,
      email: user.email,
      full_name: user.fullName,
      role: user.role,
    },
  });
}
