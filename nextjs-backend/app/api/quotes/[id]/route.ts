import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";
import { withTotals } from "@/lib/serialize";

const LineSchema = z.object({
  description: z.string().min(1),
  reference: z.string().default(""),
  unit: z.string().default(""),
  quantity: z.number().default(1),
  unitPrice: z.number().default(0),
  vatRate: z.number().default(0),
  discountAmount: z.number().default(0),
  accountCode: z.string().optional(),
});

const QuoteUpdateSchema = z.object({
  clientId: z.number().int().optional(),
  status: z.string().optional(),
  date: z.string().optional(),
  validUntil: z.string().optional(),
  discountPct: z.number().optional(),
  discountAmount: z.number().optional(),
  notes: z.string().optional(),
  lines: z.array(LineSchema).optional(),
});

async function loadQuote(id: number, companyId: number | null) {
  return prisma.quote.findFirst({
    where: { id, ...(companyId ? { companyId } : {}) },
    include: { lines: true, client: { select: { id: true, name: true } } },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const quote = await loadQuote(Number(id), user.companyId);
  if (!quote) return NextResponse.json({ detail: "Devis introuvable" }, { status: 404 });
  return NextResponse.json(withTotals(quote));
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "update")) return forbidden();

  const existing = await loadQuote(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Devis introuvable" }, { status: 404 });

  const body = await req.json().catch(() => null);
  const parsed = QuoteUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: parsed.error.flatten() }, { status: 422 });
  }
  const data = parsed.data;

  const quote = await prisma.$transaction(async (tx) => {
    if (data.lines) {
      await tx.quoteLine.deleteMany({ where: { quoteId: existing.id } });
    }
    return tx.quote.update({
      where: { id: existing.id },
      data: {
        ...(data.clientId !== undefined ? { clientId: data.clientId } : {}),
        ...(data.status !== undefined ? { status: data.status as never } : {}),
        ...(data.date !== undefined ? { date: new Date(data.date) } : {}),
        ...(data.validUntil !== undefined ? { validUntil: new Date(data.validUntil) } : {}),
        ...(data.discountPct !== undefined ? { discountPct: data.discountPct } : {}),
        ...(data.discountAmount !== undefined ? { discountAmount: data.discountAmount } : {}),
        ...(data.notes !== undefined ? { notes: data.notes } : {}),
        ...(data.lines
          ? { lines: { create: data.lines.map((line, position) => ({ ...line, position })) } }
          : {}),
      },
      include: { lines: true, client: { select: { id: true, name: true } } },
    });
  });

  return NextResponse.json(withTotals(quote));
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "delete")) return forbidden();

  const existing = await loadQuote(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Devis introuvable" }, { status: 404 });

  await prisma.quote.delete({ where: { id: existing.id } });
  return NextResponse.json({ ok: true });
}
