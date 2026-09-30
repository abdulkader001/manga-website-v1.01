import React from "react";
import { Navigate, useLocation } from "react-router-dom";
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

  // 3. Strict Main Admin Exclusive Gate (Only Main Admin / admin@mangareader.local can access User DB & Roles)
  if (requireMainAdmin) {
    const isMain = Boolean(
      user.is_main_admin ||
      user.role === "admin" ||
      user.email === "admin@mangareader.local"
    );
    if (!isMain) {
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
