export interface LineInput {
  quantity: number;
  unitPrice: number;
  vatRate: number;
  discountAmount?: number;
}

export interface DocumentTotals {
  subtotalHT: number;
  vatAmount: number;
  totalHT: number;
  totalTTC: number;
}

/** Calcule les totaux d'un devis/facture à partir de ses lignes + remise globale. */
export function computeTotals(
  lines: LineInput[],
  discountPct = 0,
  discountAmount = 0
): DocumentTotals {
  let subtotalHT = 0;
  let vatAmount = 0;

  for (const line of lines) {
    const lineTotal = line.quantity * line.unitPrice - (line.discountAmount || 0);
    subtotalHT += lineTotal;
    vatAmount += lineTotal * (line.vatRate / 100);
  }

  let totalHT = subtotalHT;
  if (discountPct > 0) totalHT -= totalHT * (discountPct / 100);
  if (discountAmount > 0) totalHT -= discountAmount;

  const totalTTC = totalHT + vatAmount;

  return {
    subtotalHT: round2(subtotalHT),
    vatAmount: round2(vatAmount),
    totalHT: round2(totalHT),
    totalTTC: round2(totalTTC),
  };
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
