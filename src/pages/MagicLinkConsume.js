import React, { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router";
import api from "../services/api";
import useAuth from "../hooks/useAuth";

export default function MagicLinkConsume() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { refetchUser } = useAuth();
  const [status, setStatus] = useState("Verifying your email sign-in link…");
  const [error, setError] = useState(false);
  // A link works once. React (StrictMode in development) can run the effect
  // twice; the second call would find the link used, get a 401 and throw the
  // freshly signed-in person back to /login. So each token is spent only once.
  const usedToken = useRef(null);

  useEffect(() => {
    async function consume() {
      try {
        const data = await api.auth.consumeMagicLink(token);
        if (refetchUser) {
          await refetchUser();
        }

        const user = data?.user;
        const isComplete = Boolean(
          user?.profile_completed && user?.birth_date && user?.name && user?.username
        );

        if (!isComplete) {
          setStatus("Email verified! Redirecting to finish profile setup…");
          setTimeout(() => navigate("/complete-profile", { replace: true }), 900);
        } else {
          setStatus("Sign-in successful! Welcome back.");
          setTimeout(() => navigate("/", { replace: true }), 900);
        }
      } catch (err) {
        setError(true);
        setStatus(err.message || "Invalid or expired sign-in link. Please request a new one.");
      }
    }
    if (token && usedToken.current !== token) {
      usedToken.current = token;
      consume();
    }
  }, [token, navigate, refetchUser]);

  return (
    <div className="min-h-[70vh] flex items-center justify-center p-4">
      <div className="bg-[#15171c] border border-[#262a33] p-8 rounded-2xl max-w-sm w-full text-center space-y-4 shadow-2xl">
        <div className="text-3xl">{error ? "❌" : "✨"}</div>
        <h2 className="text-lg font-bold text-white">Email Verification</h2>
        <p className={`text-xs ${error ? "text-red-400 font-medium" : "text-gray-300"}`}>{status}</p>
        {error && (
          <button
            type="button"
            onClick={() => navigate("/login")}
            className="px-4 py-2 rounded-xl bg-[#00AEF0] text-white text-xs font-bold hover:bg-[#0F5065] transition"
          >
            Back to Login
          </button>
        )}
      </div>
    </div>
  );
}
