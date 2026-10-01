import { useQuery } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "./useAuth";

// What the signed-in admin / sub-admin may do, from the server (the same
// check the API enforces). Readers get an empty set and no request is made.
export default function useStaffPermissions() {
  const { isAdmin, isSecondaryAdmin } = useAuth();
  const staff = Boolean(isAdmin || isSecondaryAdmin);
  const { data } = useQuery({
    queryKey: ["staffPermissions"],
    queryFn: () => api.admin.permissions.mine(),
    enabled: staff,
    staleTime: 60_000,
    retry: false,
  });
  const granted = new Set(data?.permissions || []);
  return {
    isMainAdmin: Boolean(isAdmin),
    /** true for the main admin, or when the sub-admin has this toggle on */
    can: (key) => Boolean(isAdmin) || (staff && granted.has(key)),
  };
}
