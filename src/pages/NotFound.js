import React from "react";
import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="min-h-[60vh] flex flex-col items-center justify-center p-4 text-center space-y-4">
      <div className="text-6xl font-extrabold text-[#00AEF0]">404</div>
      <h1 className="text-xl font-bold text-white">Page Not Found</h1>
      <p className="text-xs text-[#8b93a3] max-w-sm">
        The chapter, series, or page you are looking for does not exist or may have been moved.
      </p>
      <Link
        to="/"
        className="px-5 py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold shadow-lg transition"
      >
        Return Home
      </Link>
    </div>
  );
}
