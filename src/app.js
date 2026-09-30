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
import ErrorBoundary from "./components/ErrorBoundary";
import AdblockCheck from "./components/AdblockCheck";
import AdSection, { AdsProvider } from "./components/GlobalAds";
import AdPlacement from "./components/AdPlacement";
import ScrollToTopButton from "./components/ScrollToTopButton";
import ScrollToTop from "./components/ScrollToTop";
import AntiTamperGuard from "./components/AntiTamperGuard";

// Eagerly imported for lightning-fast, instantaneous navigation
import SeriesManagement from "./pages/Admin/SeriesManagement";
import AdsManager from "./pages/Admin/AdsManager";
import AdSlotsManager from "./pages/Admin/AdSlotsManager";
import Health from "./pages/Admin/Health";
import RoleManagement from "./pages/Admin/RoleManagement";
import UserDatabase from "./pages/Admin/UserDatabase";
import AdminPanel from "./pages/AdminPanel";
import AdminSettings from "./pages/Admin/AdminSettings";
import ApiManagement from "./pages/Admin/ApiManagement";
import AuditReport from "./pages/Admin/AuditReport";
import ChapterReports from "./pages/Admin/ChapterReports";
import AdminSecurity from "./pages/Admin/AdminSecurity";

function AppShell({ children }) {
  const location = useLocation();
  const isAuthRoute =
    location.pathname === "/login" ||
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
    <Routes>
      {/* Auth Entry & Onboarding Routes */}
      <Route path="/login" element={<Login />} />
      <Route path="/magic-link/:token" element={<MagicLinkConsume />} />
      <Route path="/login/magic/:token" element={<MagicLinkConsume />} />
      <Route path="/complete-profile" element={<CompleteProfile />} />

      {/* Mandatory Protected Content: All pages require verified login & profile */}
      <Route
        element={
          <AuthGuard>
            <Outlet />
          </AuthGuard>
        }
      >
        <Route path="/" element={<Homepage />} />
        <Route path="/browse" element={<BrowseManga />} />
        <Route path="/reader/:mangaId/:chapterId" element={<ChapterViewer />} />
        <Route path="/manga/:mangaId" element={<MangaDetail />} />
        <Route path="/bookmarks" element={<BookmarkHistoryTab />} />
        <Route path="/settings" element={<UserSettings />} />
        <Route path="/notifications" element={<NotificationsPage />} />

        {/* Admin Section: Instant render without chunk latency */}
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
            <AuthGuard requireAdmin>
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
            <AuthGuard requireAdmin>
              <ChapterReports />
            </AuthGuard>
          }
        />
      </Route>

      {/* F-76: anything unmatched renders a real 404 page */}
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function AppContent() {
  const location = useLocation();

  return (
    <AppShell>
      <ErrorBoundary resetKey={location.pathname}>
        <AppRoutes />
      </ErrorBoundary>
    </AppShell>
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
