import React, { createContext, useContext, useState, useEffect, useCallback } from "react";
import api, { refreshSession, setSessionActive } from "../services/api";

// Set while someone is signed in on this browser. The access token lasts an
// hour, the refresh cookie much longer: when the page opens with an expired
// access token, this says it is worth renewing it instead of showing the
// person as signed out. Guests never have it, so they never try.
const HAD_SESSION_KEY = "mw_had_session";

function hadSession() {
  try {
    return localStorage.getItem(HAD_SESSION_KEY) === "1";
  } catch {
    return false;
  }
}

function rememberSession(on) {
  try {
    if (on) localStorage.setItem(HAD_SESSION_KEY, "1");
    else localStorage.removeItem(HAD_SESSION_KEY);
  } catch {
    // storage blocked: the page just won't renew on its own
  }
}

async function loadMe() {
  try {
    return await api.auth.me();
  } catch (err) {
    if (err?.status === 401 && hadSession() && (await refreshSession())) {
      return api.auth.me();
    }
    throw err;
  }
}

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const fetchUser = useCallback(async () => {
    try {
      const data = await loadMe();
      const profile = data && data.user ? data.user : data;
      if (profile && profile.id) {
        setUser(profile);
        setSessionActive(true);
        rememberSession(true);
      } else {
        setUser(null);
        setSessionActive(false);
      }
    } catch (err) {
      setUser(null);
      setSessionActive(false);
      // Signed out for real (refresh refused too): stop trying on every load.
      if (err?.status === 401) rememberSession(false);
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
      rememberSession(false);
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
