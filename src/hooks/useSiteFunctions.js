import { useQuery } from "@tanstack/react-query";
import api from "../services/api";

// Which website functions the owner has switched on (Admin -> Site Functions).
// The server enforces every switch; this only lets the page hide what would be
// refused. While the answer is loading, or can't be fetched, a function counts
// as on: hiding a working feature on a hiccup would be worse than showing a
// button the server then refuses.
export default function useSiteFunctions() {
  const { data } = useQuery({
    queryKey: ["siteFunctions"],
    queryFn: () => api.config.siteFunctions(),
    staleTime: 30_000,
    retry: false,
  });
  const states = data?.functions || {};
  return {
    functions: states,
    isOn: (key) => states[key] !== false,
  };
}
