import { prisma } from "./prisma";

/**
 * Calcule le prochain numéro Q{année}-{seq} / F{année}-{seq} à partir du
 * MAX du suffixe numérique réellement présent en base (jamais un COUNT,
 * qui recolle un numéro déjà pris dès qu'un document a été supprimé —
 * bug déjà rencontré et corrigé sur la version Python, voir CLAUDE.md §M2bis).
 */
export async function nextDocumentNumber(
  model: "quote" | "invoice",
  prefix: string
): Promise<string> {
  const year = new Date().getFullYear();

  const rows =
    model === "quote"
      ? await prisma.quote.findMany({
          where: { number: { startsWith: `${prefix}${year}-` } },
          select: { number: true },
        })
      : await prisma.invoice.findMany({
          where: { number: { startsWith: `${prefix}${year}-` } },
          select: { number: true },
        });

  let maxSeq = 0;
  for (const row of rows) {
    const suffix = row.number.split("-").pop() || "0";
    const n = parseInt(suffix, 10);
    if (!Number.isNaN(n) && n > maxSeq) maxSeq = n;
  }

  const seq = String(maxSeq + 1).padStart(3, "0");
  return `${prefix}${year}-${seq}`;
}
