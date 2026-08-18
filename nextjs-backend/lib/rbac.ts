import { NextResponse } from "next/server";
import { AuthUser } from "./auth";

/**
 * RBAC de départ, volontairement simple : à affiner module par module
 * (le système Python source a une matrice de permissions bien plus fine,
 * voir rbac_matrix.py — non reportée ici pour cette 1ère passe).
 */
type Action = "view" | "create" | "update" | "delete";

const CAN_WRITE: Record<AuthUser["role"], boolean> = {
  ADMIN: true,
  DG: true,
  MANAGER: true,
};

const CAN_DELETE: Record<AuthUser["role"], boolean> = {
  ADMIN: true,
  DG: true,
  MANAGER: false,
};

export function can(user: AuthUser, action: Action): boolean {
  if (action === "view") return true;
  if (action === "delete") return CAN_DELETE[user.role];
  return CAN_WRITE[user.role];
}

export function unauthorized() {
  return NextResponse.json({ detail: "Authentification requise" }, { status: 401 });
}

export function forbidden() {
  return NextResponse.json({ detail: "Action non autorisée pour ce rôle" }, { status: 403 });
}
