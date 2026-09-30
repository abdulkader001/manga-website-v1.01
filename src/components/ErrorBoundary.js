import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 max-w-xl mx-auto my-12 bg-[#15171c] border border-red-900/40 rounded-2xl text-center space-y-4 shadow-2xl">
          <div className="text-3xl text-red-500">⚠️</div>
          <h2 className="text-lg font-bold text-white">Something went wrong</h2>
          <p className="text-xs text-gray-400">
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065] transition"
          >
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
