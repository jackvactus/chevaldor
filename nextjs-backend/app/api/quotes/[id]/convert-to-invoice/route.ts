import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";
import { nextDocumentNumber } from "@/lib/numbering";
import { withTotals } from "@/lib/serialize";

export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "create")) return forbidden();

  const quote = await prisma.quote.findFirst({
    where: { id: Number(id), ...(user.companyId ? { companyId: user.companyId } : {}) },
    include: { lines: true },
  });
  if (!quote) return NextResponse.json({ detail: "Devis introuvable" }, { status: 404 });

  const number = await nextDocumentNumber("invoice", "F");

  const invoice = await prisma.invoice.create({
    data: {
      number,
      clientId: quote.clientId,
      quoteId: quote.id,
      status: "BROUILLON",
      discountPct: quote.discountPct,
      discountAmount: quote.discountAmount,
      notes: quote.notes,
      companyId: quote.companyId,
      lines: {
        create: quote.lines.map((l, position) => ({
          description: l.description,
          reference: l.reference,
          unit: l.unit,
          quantity: l.quantity,
          unitPrice: l.unitPrice,
          vatRate: l.vatRate,
          discountAmount: l.discountAmount,
          accountCode: l.accountCode,
          position,
        })),
      },
    },
    include: { lines: true, client: { select: { id: true, name: true } } },
  });

  await prisma.quote.update({ where: { id: quote.id }, data: { status: "FACTURE" } });

  return NextResponse.json(withTotals(invoice), { status: 201 });
}
