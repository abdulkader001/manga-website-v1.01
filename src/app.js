import React, { Suspense } from "react";
import { BrowserRouter as Router, Routes, Route, useLocation, Outlet } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import Navbar from "./components/Navbar";
import Homepage from "./components/Homepage";
import BrowseManga from "./components/BrowseManga";
import ChapterViewer from "./components/ChapterViewer";
import BookmarkHistoryTab from "./components/BookmarkHistoryTab";
import MangaDetail from "./components/MangaDetail";
import Login from "./components/Login";
import MagicLinkConsume from "./pages/MagicLinkConsume";
import CompleteProfile from "./pages/CompleteProfile";
import UserSettings from "./pages/UserSettings";
import NotificationsPage from "./pages/NotificationsPage";
import NotFound from "./pages/NotFound";
import Footer from "./components/Footer";

import AuthGuard from "./components/AuthGuard";
import RegionGate from "./components/RegionGate";
import ErrorBoundary from "./components/ErrorBoundary";
import AdblockCheck from "./components/AdblockCheck";
import AdSection, { AdsProvider } from "./components/GlobalAds";
import AdPlacement from "./components/AdPlacement";
import ScrollToTopButton from "./components/ScrollToTopButton";
import ScrollToTop from "./components/ScrollToTop";
import AntiTamperGuard from "./components/AntiTamperGuard";

// Admin screens are separate chunks (F-95): readers never download them,
// admins load each on first open.
const SeriesManagement = React.lazy(() => import("./pages/Admin/SeriesManagement"));
const AdsManager = React.lazy(() => import("./pages/Admin/AdsManager"));
const AdSlotsManager = React.lazy(() => import("./pages/Admin/AdSlotsManager"));
const Health = React.lazy(() => import("./pages/Admin/Health"));
const RoleManagement = React.lazy(() => import("./pages/Admin/RoleManagement"));
const UserDatabase = React.lazy(() => import("./pages/Admin/UserDatabase"));
const AdminPanel = React.lazy(() => import("./pages/AdminPanel"));
const AdminSettings = React.lazy(() => import("./pages/Admin/AdminSettings"));
const ApiManagement = React.lazy(() => import("./pages/Admin/ApiManagement"));
const AuditReport = React.lazy(() => import("./pages/Admin/AuditReport"));
const ChapterReports = React.lazy(() => import("./pages/Admin/ChapterReports"));
const AdminSecurity = React.lazy(() => import("./pages/Admin/AdminSecurity"));
const SecretVault = React.lazy(() => import("./pages/Admin/SecretVault"));
const StorageBackups = React.lazy(() => import("./pages/Admin/StorageBackups"));
const Geolock = React.lazy(() => import("./pages/Admin/Geolock"));

function PageLoading() {
  return (
    <div className="min-h-[50vh] flex items-center justify-center text-xs text-[#8b93a3]">Loading…</div>
  );
}

// The one-time site-owner sign-in is its own chunk: nothing links to it and
// regular visitors never download it.
const AdminLogin = React.lazy(() => import("./pages/AdminLogin"));

function AppShell({ children }) {
  const location = useLocation();
  const isAuthRoute =
    location.pathname === "/login" ||
    location.pathname === "/admin-login" ||
    location.pathname === "/complete-profile" ||
    location.pathname.startsWith("/magic-link") ||
    location.pathname.startsWith("/login/magic");
  const showChrome = !isAuthRoute;

  return (
    <div className="min-h-screen flex flex-col bg-[var(--bg-primary)] text-[var(--text-primary)]">
      {showChrome && <Navbar />}

      {showChrome && <AdSection sectionKey="global" className="global-ads--header" fallback={null} />}

      {/* Admin-assigned site-wide slots */}
      {showChrome && <AdPlacement placement="global_top" className="ad-placement--global-top" />}

      {/* 📖 Main Content */}
      <main className="flex-1">{children}</main>

      {showChrome && <AdPlacement placement="global_bottom" className="ad-placement--global-bottom" />}

      {showChrome && <AdSection sectionKey="global" className="global-ads--footer" fallback={null} />}

      {showChrome && <Footer />}
      <ScrollToTopButton />
    </div>
  );
}

function AppRoutes() {
  return (
    <Suspense fallback={<PageLoading />}>
    <Routes>
      {/* Auth Entry & Onboarding Routes */}
      <Route path="/login" element={<Login />} />
      <Route
        path="/admin-login"
        element={
          <Suspense fallback={null}>
            <AdminLogin />
          </Suspense>
        }
      />
      <Route path="/magic-link/:token" element={<MagicLinkConsume />} />
      <Route path="/login/magic/:token" element={<MagicLinkConsume />} />
      <Route path="/complete-profile" element={<CompleteProfile />} />

      {/* Reading pages: open to guests unless the main admin turned on
          "Sign-in required" in Admin Settings. Signed-in users still have to
          finish their profile. */}
      <Route
        element={
          <AuthGuard followSiteSetting>
            <Outlet />
          </AuthGuard>
        }
      >
        <Route path="/" element={<Homepage />} />
        <Route path="/browse" element={<BrowseManga />} />
        <Route path="/reader/:mangaId/:chapterId" element={<ChapterViewer />} />
        <Route path="/manga/:mangaId" element={<MangaDetail />} />
        <Route path="/bookmarks" element={<BookmarkHistoryTab />} />
        <Route
          path="/settings"
          element={
            <AuthGuard>
              <UserSettings />
            </AuthGuard>
          }
        />
        <Route
          path="/notifications"
          element={
            <AuthGuard>
              <NotificationsPage />
            </AuthGuard>
          }
        />

        {/* Admin Section (lazy chunks, see F-95) */}
        <Route
          path="/admin/series"
          element={
            <AuthGuard requireAdmin allowSecondaryAdmins>
              <SeriesManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/roles"
          element={
            <AuthGuard requireMainAdmin>
              <RoleManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/users"
          element={
            <AuthGuard requireMainAdmin>
              <UserDatabase />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/ads"
          element={
            <AuthGuard requireAdmin>
              <AdsManager />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/ad-slots"
          element={
            <AuthGuard requireAdmin>
              <AdSlotsManager />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/health"
          element={
            <AuthGuard requireAdmin allowSecondaryAdmins permission="view_dashboard">
              <Health />
            </AuthGuard>
          }
        />
        <Route
          path="/admin"
          element={
            <AuthGuard requireAdmin allowSecondaryAdmins>
              <AdminPanel />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/security"
          element={
            <AuthGuard requireAdmin allowSecondaryAdmins>
              <AdminSecurity />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/vault"
          element={
            <AuthGuard requireAdmin requireMainAdmin>
              <SecretVault />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/backups"
          element={
            <AuthGuard requireAdmin requireMainAdmin>
              <StorageBackups />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/geolock"
          element={
            <AuthGuard requireAdmin requireMainAdmin>
              <Geolock />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/settings"
          element={
            <AuthGuard requireAdmin>
              <AdminSettings />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/api-management"
          element={
            <AuthGuard requireAdmin>
              <ApiManagement />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/audit-report"
          element={
            <AuthGuard requireAdmin>
              <AuditReport />
            </AuthGuard>
          }
        />
        <Route
          path="/admin/chapter-reports"
          element={
            <AuthGuard requireAdmin allowSecondaryAdmins permission="handle_reports">
              <ChapterReports />
            </AuthGuard>
          }
        />
      </Route>

      {/* F-76: anything unmatched renders a real 404 page */}
      <Route path="*" element={<NotFound />} />
    </Routes>
    </Suspense>
  );
}

function AppContent() {
  const location = useLocation();

  return (
    <RegionGate>
      <AppShell>
        <ErrorBoundary resetKey={location.pathname}>
          <AppRoutes />
        </ErrorBoundary>
      </AppShell>
    </RegionGate>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes fresh cache
      gcTime: 1000 * 60 * 30, // 30 minutes in memory
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        {/* Reset window scroll to top on every route navigation */}
        <ScrollToTop />
        {/* Protect site concepts, core architecture, and prevent unauthorized DevTools tampering */}
        <AntiTamperGuard>
          {/* Wrap the app inside AdblockCheck to detect blockers */}
          <AdblockCheck>
            <AdsProvider>
              <AppContent />
            </AdsProvider>
          </AdblockCheck>
        </AntiTamperGuard>
      </Router>
    </QueryClientProvider>
  );
}

export default App;
