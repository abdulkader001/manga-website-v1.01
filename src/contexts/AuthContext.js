import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import api, { setSessionActive } from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    try {
      const data = await api.auth.me();
      const profile = data && data.user ? data.user : data;
      if (profile && profile.id) {
        setUser(profile);
        setSessionActive(true);
      } else {
        setUser(null);
        setSessionActive(false);
      }
    } catch (err) {
      setUser(null);
      setSessionActive(false);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  const login = useCallback((provider = "google") => {
    api.auth.login(provider);
  }, []);

  const logout = useCallback(async (options = {}) => {
    try {
      await api.auth.logout(options);
    } catch (err) {
      console.warn("Logout error:", err);
    } finally {
      setUser(null);
      window.location.href = "/";
    }
  }, []);

  const isAdmin = !!(
    user &&
    (user.role === "admin" ||
      user.role === "permanent_admin" ||
      user.is_main_admin ||
      user.permanent)
  );
  // Sub-admins and Admins (role "co_admin") are both staff; the owner is isAdmin.
  const isSecondaryAdmin = !!(
    user &&
    (user.role === "secondary_admin" || user.role === "co_admin" || user.is_secondary_admin)
  );
  const username = user?.username || user?.name || (user?.email ? user.email.split("@")[0] : "Reader");
  const name = user?.name || username;

  const value = {
    user,
    username,
    name,
    isAdmin,
    isSecondaryAdmin,
    isLoading,
    login,
    logout,
    refetchUser: fetchUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuthContext() {
  const context = useContext(AuthContext);
  if (!context) {
    return {
      user: null,
      username: "Reader",
      name: "Reader",
      isAdmin: false,
      isSecondaryAdmin: false,
      isLoading: false,
      login: () => {},
      logout: () => {},
      refetchUser: () => {},
    };
  }
  return context;
}

export default AuthContext;
