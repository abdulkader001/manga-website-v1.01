import React from "react";
import { Navigate, useLocation } from "react-router";
import useAuth from "../hooks/useAuth";
import AdminSecondFactor from "./AdminSecondFactor";

export default function AuthGuard({ children, requireAdmin, requireMainAdmin, allowSecondaryAdmins }) {
  const { user, isAdmin, isSecondaryAdmin, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">
        Checking authentication…
      </div>
    );
  }

  // 1. Mandatory login gate: if user is not authenticated, redirect to /login
  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // 2. Profile completion check: if user is logged in but hasn't entered name, username, and birthdate
  const isProfileComplete = Boolean(
    user.profile_completed && user.birth_date && user.name && user.username
  );

  if (!isProfileComplete && location.pathname !== "/complete-profile") {
    return <Navigate to="/complete-profile" replace />;
  }

  // 3. Main-admin-only pages. isAdmin is the owner tier (admin / permanent
  // admin); the backend enforces the same rule, this only avoids a dead page.
  if (requireMainAdmin) {
    if (!isAdmin) {
      return <Navigate to="/admin" replace />;
    }
    return <AdminSecondFactor>{children}</AdminSecondFactor>;
  }

  // 4. Admin permissions check
  if (requireAdmin) {
    if (allowSecondaryAdmins && (isAdmin || isSecondaryAdmin)) {
      return <AdminSecondFactor>{children}</AdminSecondFactor>;
    }
    if (isAdmin) {
      return <AdminSecondFactor>{children}</AdminSecondFactor>;
    }
    return <Navigate to="/" replace />;
  }

  return children;
}
