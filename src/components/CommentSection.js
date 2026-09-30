import React, { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "../services/api";
import useAuth from "../hooks/useAuth";

export default function CommentSection({ targetType = "manga", targetId }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [content, setContent] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sort, setSort] = useState("top");

  const { data: commentsData, isLoading } = useQuery({
    queryKey: ["comments", targetType, targetId, sort],
    queryFn: () => api.comments.list(targetType, targetId, { sort }),
    enabled: !!targetId,
  });

  const comments = Array.isArray(commentsData?.items) ? commentsData.items : (Array.isArray(commentsData) ? commentsData : []);

  const handleAddComment = async (e) => {
    e.preventDefault();
    if (!content.trim() || !targetId || submitting) return;
    setSubmitting(true);
    try {
      await api.comments.create({
        target_type: targetType,
        target_id: String(targetId),
        content: content.trim(),
      });
      setContent("");
      queryClient.invalidateQueries({ queryKey: ["comments", targetType, targetId] });
    } catch (err) {
      console.error("Failed to post comment:", err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="bg-[#15171c] border border-[#262a33] p-5 sm:p-6 rounded-2xl shadow-xl space-y-6">
      <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
        <h2 className="text-lg font-bold text-white flex items-center gap-2">
          <i className="fas fa-comments text-[#00AEF0]"></i>
          <span>Discussion ({comments.length})</span>
        </h2>

        <div className="flex items-center gap-1 text-xs">
          <span className="text-[#8b93a3] font-semibold mr-1">Sort by:</span>
          {["top", "newest", "oldest"].map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setSort(s)}
              className={`px-2.5 py-1 rounded-lg font-bold capitalize transition ${
                sort === s
                  ? "bg-[#00AEF0] text-white"
                  : "bg-[#101216] text-gray-400 hover:text-white"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Comment input form */}
      <form onSubmit={handleAddComment} className="space-y-3">
        <textarea
          rows={3}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder={user ? "Join the discussion..." : "Sign in or post a thought..."}
          className="w-full p-3.5 rounded-xl bg-[#101216] border border-[#262a33] text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-[#00AEF0] resize-none"
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-[#8b93a3]">
            Be respectful and keep spoilers tagged.
          </span>
          <button
            type="submit"
            disabled={!content.trim() || submitting}
            className="px-5 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white font-bold text-xs shadow-lg transition disabled:opacity-50"
          >
            {submitting ? "Posting…" : "Post Comment"}
          </button>
        </div>
      </form>

      {/* Comments List */}
      <div className="space-y-3">
        {isLoading ? (
          <p className="text-xs text-[#8b93a3] text-center py-4">Loading comments…</p>
        ) : comments.length > 0 ? (
          comments.map((cmt) => (
            <div key={cmt.id} className="p-3.5 rounded-xl bg-[#101216] border border-[#262a33] space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  {cmt.user_profile_image || cmt.user_avatar || cmt.profile_image ? (
                    <img
                      src={cmt.user_profile_image || cmt.user_avatar || cmt.profile_image}
                      alt={cmt.user_name || "User"}
                      className="w-7 h-7 rounded-full object-cover border border-[#00AEF0] flex-none"
                    />
                  ) : (
                    <div className="w-7 h-7 rounded-full bg-gradient-to-tr from-[#00AEF0] to-purple-600 flex items-center justify-center font-bold text-xs text-white flex-none">
                      {(cmt.user_name || "A")[0].toUpperCase()}
                    </div>
                  )}
                  <div>
                    <span className="text-xs font-bold text-white block">{cmt.user_name || "Reader"}</span>
                    <span className="text-[10px] text-[#8b93a3]">{cmt.created_at ? new Date(cmt.created_at).toLocaleDateString() : "Recently"}</span>
                  </div>
                </div>
                {cmt.score != null && (
                  <span className="text-xs text-emerald-400 font-bold">+{cmt.score}</span>
                )}
              </div>
              <p className="text-xs text-gray-200 leading-relaxed pl-9">{cmt.content}</p>
            </div>
          ))
        ) : (
          <p className="text-xs text-[#8b93a3] text-center py-6">No comments yet. Be the first to share your thoughts!</p>
        )}
      </div>
    </section>
  );
}
