import bcrypt from "bcryptjs";
import { SignJWT, jwtVerify } from "jose";
import { NextRequest } from "next/server";
import { prisma } from "./prisma";

const JWT_SECRET = process.env.JWT_SECRET;
const TOKEN_TTL_SECONDS = 60 * 60 * 12; // 12h, cohérent avec l'ERP actuel

function secretKey() {
  if (!JWT_SECRET) {
    throw new Error("JWT_SECRET manquant — définissez-le dans les variables d'environnement.");
  }
  return new TextEncoder().encode(JWT_SECRET);
}

export async function hashPassword(password: string): Promise<string> {
  return bcrypt.hash(password, 12);
}

export async function verifyPassword(password: string, hash: string): Promise<boolean> {
  return bcrypt.compare(password, hash);
}

export interface AuthUser {
  id: number;
  email: string;
  role: "ADMIN" | "DG" | "MANAGER";
  companyId: number | null;
}

export async function signToken(user: AuthUser): Promise<string> {
  return new SignJWT({ email: user.email, role: user.role, companyId: user.companyId })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(String(user.id))
    .setIssuedAt()
    .setExpirationTime(`${TOKEN_TTL_SECONDS}s`)
    .sign(secretKey());
}

export async function verifyToken(token: string): Promise<AuthUser | null> {
  try {
    const { payload } = await jwtVerify(token, secretKey());
    return {
      id: Number(payload.sub),
      email: String(payload.email),
      role: payload.role as AuthUser["role"],
      companyId: (payload.companyId as number | null) ?? null,
    };
  } catch {
    return null;
  }
}

/** Extrait et vérifie l'utilisateur depuis l'en-tête Authorization: Bearer <token>. */
export async function getUserFromRequest(req: NextRequest): Promise<AuthUser | null> {
  const header = req.headers.get("authorization") || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : null;
  if (!token) return null;
  const user = await verifyToken(token);
  if (!user) return null;

  // Revérifie que le compte existe toujours et est actif (révocation immédiate si désactivé).
  const dbUser = await prisma.user.findUnique({ where: { id: user.id } });
  if (!dbUser || !dbUser.isActive) return null;
  return user;
}
