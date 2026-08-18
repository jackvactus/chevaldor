const ENDPOINTS = [
  "POST /api/auth/login",
  "GET  /api/auth/me",
  "GET  /api/health",
  "GET  /api/clients",
  "POST /api/clients",
  "GET  /api/clients/:id",
  "PUT  /api/clients/:id",
  "DELETE /api/clients/:id",
  "GET  /api/quotes",
  "POST /api/quotes",
  "GET  /api/quotes/:id",
  "PUT  /api/quotes/:id",
  "DELETE /api/quotes/:id",
  "GET  /api/quotes/next-number",
  "POST /api/quotes/:id/convert-to-invoice",
  "GET  /api/invoices",
  "POST /api/invoices",
  "GET  /api/invoices/:id",
  "PUT  /api/invoices/:id",
  "DELETE /api/invoices/:id",
  "GET  /api/invoices/next-number",
  "POST /api/invoices/:id/payments",
];

export default function Home() {
  return (
    <main style={{ maxWidth: 720, margin: "48px auto", padding: "0 24px", color: "#2d2a26" }}>
      <h1 style={{ color: "#2d6b3f" }}>Cheval d&apos;Or — Backend API (Next.js)</h1>
      <p>
        Fondations du backend Next.js + PostgreSQL (Neon) : authentification/RBAC, Clients, Devis,
        Factures. Les autres modules (stock, comptabilité SYSCOHADA, RH/paie, CRM avancé...) seront
        ajoutés progressivement — voir le README du projet.
      </p>
      <p>
        Statut : <a href="/api/health">/api/health</a>
      </p>
      <h2>Endpoints disponibles</h2>
      <pre style={{ background: "#f7f3eb", padding: 16, borderRadius: 8, overflowX: "auto" }}>
        {ENDPOINTS.join("\n")}
      </pre>
    </main>
  );
}
