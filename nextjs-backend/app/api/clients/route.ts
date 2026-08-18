import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";

const ClientSchema = z.object({
  name: z.string().min(1),
  type: z.string().default("particulier"),
  email: z.string().email().or(z.literal("")).default(""),
  phone: z.string().default(""),
  city: z.string().default(""),
  segment: z.string().default(""),
  accountCode: z.string().optional(),
  creditLimit: z.number().default(0),
  paymentTermsDays: z.number().int().default(30),
  defaultDiscountPct: z.number().default(0),
  defaultVatPct: z.number().default(0),
  defaultCommissionPct: z.number().default(0),
  notes: z.string().default(""),
});

export async function GET(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const { searchParams } = new URL(req.url);
  const limit = Math.min(Number(searchParams.get("limit") || 200), 1000);
  const offset = Number(searchParams.get("offset") || 0);
  const search = searchParams.get("search") || "";
  const includeArchived = searchParams.get("include_archived") === "true";

  const clients = await prisma.client.findMany({
    where: {
      ...(includeArchived ? {} : { isArchived: false }),
      ...(search ? { name: { contains: search, mode: "insensitive" } } : {}),
    },
    orderBy: { name: "asc" },
    take: limit,
    skip: offset,
  });

  return NextResponse.json(clients);
}

export async function POST(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "create")) return forbidden();

  const body = await req.json().catch(() => null);
  const parsed = ClientSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: parsed.error.flatten() }, { status: 422 });
  }

  const client = await prisma.client.create({
    data: { ...parsed.data, companyId: user.companyId },
  });

  return NextResponse.json(client, { status: 201 });
}
