import { PrismaClient } from "@prisma/client";
import bcrypt from "bcryptjs";

const prisma = new PrismaClient();

async function main() {
  const company = await prisma.company.upsert({
    where: { code: "CHEVALDOR" },
    update: {},
    create: {
      code: "CHEVALDOR",
      name: "Hôtel Le Cheval d'Or",
      legalForm: "SARL",
      address: "Anié, Togo",
      email: "contact@chevaldor.com",
      currency: "XOF",
      isDefault: true,
    },
  });

  const adminEmail = process.env.SEED_ADMIN_EMAIL || "admin@chevaldor.com";
  const adminPassword = process.env.SEED_ADMIN_PASSWORD || "Password1234@";

  await prisma.user.upsert({
    where: { email: adminEmail },
    update: {},
    create: {
      email: adminEmail,
      username: "admin",
      passwordHash: await bcrypt.hash(adminPassword, 12),
      fullName: "Administrateur",
      role: "ADMIN",
      companyId: company.id,
    },
  });

  console.log(`Seed OK — société "${company.name}", admin "${adminEmail}"`);
}

main()
  .catch((err) => {
    console.error(err);
    process.exit(1);
  })
  .finally(() => prisma.$disconnect());
