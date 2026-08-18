import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";

const ClientUpdateSchema = z.object({
  name: z.string().min(1).optional(),
  type: z.string().optional(),
  email: z.string().email().or(z.literal("")).optional(),
  phone: z.string().optional(),
  city: z.string().optional(),
  segment: z.string().optional(),
  accountCode: z.string().optional(),
  creditLimit: z.number().optional(),
  paymentTermsDays: z.number().int().optional(),
  defaultDiscountPct: z.number().optional(),
  defaultVatPct: z.number().optional(),
  defaultCommissionPct: z.number().optional(),
  notes: z.string().optional(),
  isArchived: z.boolean().optional(),
});

async function loadClient(id: number, companyId: number | null) {
  return prisma.client.findFirst({
    where: { id, ...(companyId ? { companyId } : {}) },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const client = await loadClient(Number(id), user.companyId);
  if (!client) return NextResponse.json({ detail: "Client introuvable" }, { status: 404 });
  return NextResponse.json(client);
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "update")) return forbidden();

  const existing = await loadClient(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Client introuvable" }, { status: 404 });

  const body = await req.json().catch(() => null);
  const parsed = ClientUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: parsed.error.flatten() }, { status: 422 });
  }

  const client = await prisma.client.update({
    where: { id: existing.id },
    data: parsed.data,
  });

  return NextResponse.json(client);
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "delete")) return forbidden();

  const existing = await loadClient(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Client introuvable" }, { status: 404 });

  const linkedQuotes = await prisma.quote.count({ where: { clientId: existing.id } });
  const linkedInvoices = await prisma.invoice.count({ where: { clientId: existing.id } });

  if (linkedQuotes > 0 || linkedInvoices > 0) {
    // Cohérent avec la version Python : on archive plutôt que de casser
    // l'intégrité référentielle (devis/factures liés).
    const client = await prisma.client.update({
      where: { id: existing.id },
      data: { isArchived: true },
    });
    return NextResponse.json({ ok: true, archived: true, client });
  }

  await prisma.client.delete({ where: { id: existing.id } });
  return NextResponse.json({ ok: true, archived: false });
}
