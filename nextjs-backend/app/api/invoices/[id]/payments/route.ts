import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { prisma } from "@/lib/prisma";
import { getUserFromRequest } from "@/lib/auth";
import { can, forbidden, unauthorized } from "@/lib/rbac";
import { computeTotals } from "@/lib/documentCalc";
import { withTotals } from "@/lib/serialize";

const PaymentSchema = z.object({ amount: z.number().positive() });

/** Encaisse un paiement sur une facture ; passe le statut à jour selon le solde restant. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await getUserFromRequest(req);
  if (!user) return unauthorized();
  if (!can(user, "update")) return forbidden();

  const invoice = await prisma.invoice.findFirst({
    where: { id: Number(id), ...(user.companyId ? { companyId: user.companyId } : {}) },
    include: { lines: true },
  });
  if (!invoice) return NextResponse.json({ detail: "Facture introuvable" }, { status: 404 });

  const body = await req.json().catch(() => null);
  const parsed = PaymentSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json({ detail: "Montant invalide" }, { status: 422 });
  }

  const totals = computeTotals(
    invoice.lines.map((l) => ({
      quantity: Number(l.quantity),
      unitPrice: Number(l.unitPrice),
      vatRate: Number(l.vatRate),
      discountAmount: Number(l.discountAmount),
    })),
    Number(invoice.discountPct),
    Number(invoice.discountAmount)
  );

  const newPaid = Number(invoice.paidAmount) + parsed.data.amount;
  if (newPaid > totals.totalTTC + 0.01) {
    return NextResponse.json(
      { detail: `Le montant encaissé dépasse le total facture (${totals.totalTTC})` },
      { status: 422 }
    );
  }

  const status = newPaid >= totals.totalTTC - 0.01 ? "PAYEE" : "PARTIELLEMENT_PAYEE";

  const updated = await prisma.invoice.update({
    where: { id: invoice.id },
    data: { paidAmount: newPaid, status },
    include: { lines: true, client: { select: { id: true, name: true } } },
  });

  return NextResponse.json(withTotals(updated));
}
