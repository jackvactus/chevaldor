import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";
import { nextDocumentNumber } from "@/lib/numbering";
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

const InvoiceSchema = z.object({
  number: z.string().optional(),
  clientId: z.number().int(),
  quoteId: z.number().int().optional(),
  status: z.string().default("BROUILLON"),
  date: z.string().optional(),
  dueDate: z.string().optional(),
  discountPct: z.number().default(0),
  discountAmount: z.number().default(0),
  notes: z.string().default(""),
  lines: z.array(LineSchema).default([]),
});

export async function GET(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();

  const { searchParams } = new URL(req.url);
  const limit = Math.min(Number(searchParams.get("limit") || 200), 1000);
  const clientId = searchParams.get("client_id");
  const status = searchParams.get("status");

  const invoices = await prisma.invoice.findMany({
    where: {
      ...(user.companyId ? { companyId: user.companyId } : {}),
      ...(clientId ? { clientId: Number(clientId) } : {}),
      ...(status ? { status: status as never } : {}),
    },
    include: { lines: true, client: { select: { id: true, name: true } } },
    orderBy: { id: "desc" },
    take: limit,
  });

  return NextResponse.json(invoices.map(withTotals));
}

export async function POST(req: NextRequest) {
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "create")) return forbidden();

  const body = await req.json().catch(() => null);
  const parsed = InvoiceSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: parsed.error.flatten() }, { status: 422 });
  }
  const data = parsed.data;

  const client = await prisma.client.findUnique({ where: { id: data.clientId } });
  if (!client) return NextResponse.json({ detail: "Client introuvable" }, { status: 404 });

  let number = data.number?.trim();
  if (!number || (await prisma.invoice.findUnique({ where: { number } }))) {
    number = await nextDocumentNumber("invoice", "F");
  }

  const invoice = await prisma.invoice.create({
    data: {
      number,
      clientId: data.clientId,
      quoteId: data.quoteId,
      status: data.status as never,
      date: data.date ? new Date(data.date) : new Date(),
      dueDate: data.dueDate ? new Date(data.dueDate) : null,
      discountPct: data.discountPct,
      discountAmount: data.discountAmount,
      notes: data.notes,
      companyId: user.companyId,
      lines: {
        create: data.lines.map((line, position) => ({ ...line, position })),
      },
    },
    include: { lines: true, client: { select: { id: true, name: true } } },
  });

  return NextResponse.json(withTotals(invoice), { status: 201 });
}
