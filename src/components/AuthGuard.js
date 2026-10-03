import React from "react";
import { Navigate, useLocation } from "react-router";
import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "../hooks/useAuth";
import useStaffPermissions from "../hooks/useStaffPermissions";
import AdminSecondFactor from "./AdminSecondFactor";

// `followSiteSetting`: sign-in is required by default, so a guest passes only
// when the server says plainly that the owner switched "Sign-in required" off
// (Admin Settings). If the answer can't be fetched the guest goes to the login
// page. The backend enforces the same switch.
export default function AuthGuard({
  children,
  requireAdmin,
  requireMainAdmin,
  allowSecondaryAdmins,
  permission,
  followSiteSetting,
}) {
  const { user, isAdmin, isSecondaryAdmin, isLoading } = useAuth();
  // `permission`: a sub-admin passes only with this toggle on (the main admin
  // always passes). Matches the tile filter on the admin hub.
  const { can, suspended, isLoading: permissionsLoading } = useStaffPermissions();
  const location = useLocation();
  const siteAccess = useQuery({
    queryKey: ["siteAccess"],
    queryFn: () => api.config.siteAccess(),
    enabled: Boolean(followSiteSetting),
    staleTime: 60000,
    retry: 1,
  });

  if (isLoading || (followSiteSetting && !user && siteAccess.isLoading)) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">
        Checking authentication…
      </div>
    );
  }

  // 1. Mandatory login gate: if user is not authenticated, redirect to /login
  if (!user) {
    if (followSiteSetting && siteAccess.data?.loginRequired === false) {
      return children;
    }
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

  // 4. Admin permissions check. A person whose powers the owner switched off
  // keeps the title but nothing in the admin area opens for them.
  if (requireAdmin && suspended) {
    return (
      <div className="max-w-md mx-auto mt-16 p-6 rounded-2xl bg-[#101216] border border-[#262a33] text-gray-200 space-y-2">
        <h2 className="text-sm font-bold text-white">Your admin powers are switched off</h2>
        <p className="text-xs text-[#8b93a3]">
          The site owner switched your admin powers off. You keep your role, but the admin area stays
          closed until the owner switches them back on.
        </p>
      </div>
    );
  }
  if (requireAdmin) {
    if (allowSecondaryAdmins && (isAdmin || isSecondaryAdmin)) {
      if (permission && !isAdmin) {
        if (permissionsLoading) {
          return (
            <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">
              Checking permissions…
            </div>
          );
        }
        if (!can(permission)) return <Navigate to="/admin" replace />;
      }
      return <AdminSecondFactor>{children}</AdminSecondFactor>;
    }
    if (isAdmin) {
      return <AdminSecondFactor>{children}</AdminSecondFactor>;
    }
    return <Navigate to="/" replace />;
  }

  return children;
}
