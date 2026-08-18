import { computeTotals } from "./documentCalc";

type LineLike = {
  quantity: unknown;
  unitPrice: unknown;
  vatRate: unknown;
  discountAmount: unknown;
};

type DocLike = {
  lines: LineLike[];
  discountPct: unknown;
  discountAmount: unknown;
};

/** Convertit les Decimal Prisma en number et ajoute les totaux calculés. */
export function withTotals<T extends DocLike>(doc: T) {
  const lines = doc.lines.map((l) => ({
    ...l,
    quantity: Number(l.quantity),
    unitPrice: Number(l.unitPrice),
    vatRate: Number(l.vatRate),
    discountAmount: Number(l.discountAmount),
  }));

  const totals = computeTotals(
    lines,
    Number(doc.discountPct || 0),
    Number(doc.discountAmount || 0)
  );

  return { ...doc, lines, totals };
}
