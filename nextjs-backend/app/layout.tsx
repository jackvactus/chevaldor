export const metadata = {
  title: "Cheval d'Or — Backend API",
  description: "Backend Next.js de l'ERP Cheval d'Or (fondations : auth, clients, devis, factures).",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body style={{ margin: 0, fontFamily: "system-ui, sans-serif" }}>{children}</body>
    </html>
  );
}
