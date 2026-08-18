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

const InvoiceUpdateSchema = z.object({
  clientId: z.number().int().optional(),
  status: z.string().optional(),
  date: z.string().optional(),
  dueDate: z.string().optional(),
  discountPct: z.number().optional(),
  discountAmount: z.number().optional(),
  notes: z.string().optional(),
  lines: z.array(LineSchema).optional(),
});

async function loadInvoice(id: number, companyId: number | null) {
  return prisma.invoice.findFirst({
    where: { id, ...(companyId ? { companyId } : {}) },
    include: { lines: true, client: { select: { id: true, name: true } } },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const invoice = await loadInvoice(Number(id), user.companyId);
  if (!invoice) return NextResponse.json({ detail: "Facture introuvable" }, { status: 404 });
  return NextResponse.json(withTotals(invoice));
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "update")) return forbidden();

  const existing = await loadInvoice(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Facture introuvable" }, { status: 404 });

  const body = await req.json().catch(() => null);
  const parsed = InvoiceUpdateSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: parsed.error.flatten() }, { status: 422 });
  }
  const data = parsed.data;

  const invoice = await prisma.$transaction(async (tx) => {
    if (data.lines) {
      await tx.invoiceLine.deleteMany({ where: { invoiceId: existing.id } });
    }
    return tx.invoice.update({
      where: { id: existing.id },
      data: {
        ...(data.clientId !== undefined ? { clientId: data.clientId } : {}),
        ...(data.status !== undefined ? { status: data.status as never } : {}),
        ...(data.date !== undefined ? { date: new Date(data.date) } : {}),
        ...(data.dueDate !== undefined ? { dueDate: new Date(data.dueDate) } : {}),
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

  return NextResponse.json(withTotals(invoice));
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "delete")) return forbidden();

  const existing = await loadInvoice(Number(id), user.companyId);
  if (!existing) return NextResponse.json({ detail: "Facture introuvable" }, { status: 404 });

  await prisma.invoice.delete({ where: { id: existing.id } });
  return NextResponse.json({ ok: true });
}
