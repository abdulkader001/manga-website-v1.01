import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "./useAuth";

// What the signed-in admin / sub-admin may do, from the server (the same
// check the API enforces). Readers get an empty set and no request is made.
export default function useStaffPermissions() {
  const { isAdmin, isSecondaryAdmin } = useAuth();
  const staff = Boolean(isAdmin || isSecondaryAdmin);
  const { data, isLoading } = useQuery({
    queryKey: ["staffPermissions"],
    queryFn: () => api.admin.permissions.mine(),
    enabled: staff,
    staleTime: 60_000,
    retry: false,
  });
  const granted = new Set(data?.permissions || []);
  return {
    isMainAdmin: Boolean(isAdmin),
    /** the Admin tier (not the owner): changes sub-admins, keeps a succession line */
    isAdminTier: !isAdmin && data?.role === "admin",
    isLoading: staff && !isAdmin && isLoading,
    /** the owner switched all this person's powers off: they keep the seat, nothing opens */
    suspended: !isAdmin && Boolean(data?.suspended),
    /** the owner's tab list for this person (null = follow the permissions) */
    tabs: data?.tabs ?? null,
    /** true for the main admin, or when the sub-admin has this toggle on */
    can: (key) => Boolean(isAdmin) || (staff && !data?.suspended && granted.has(key)),
  };
}
