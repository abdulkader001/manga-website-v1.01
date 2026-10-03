import React, { useEffect, useState } from "react";
import api from "../services/api";

const PRESET_PLATFORMS = [
  { platform: "discord", title: "Discord Community", icon: "fab fa-discord", defaultUrl: "https://discord.gg/" },
  { platform: "twitter", title: "Twitter / X Updates", icon: "fab fa-x-twitter", defaultUrl: "https://x.com/" },
  { platform: "telegram", title: "Telegram Channel", icon: "fab fa-telegram", defaultUrl: "https://t.me/" },
  { platform: "reddit", title: "Reddit Community", icon: "fab fa-reddit", defaultUrl: "https://reddit.com/r/" },
  { platform: "email", title: "Contact & Support", icon: "fas fa-envelope", defaultUrl: "mailto:" },
  { platform: "youtube", title: "YouTube Channel", icon: "fab fa-youtube", defaultUrl: "https://youtube.com/@" },
  { platform: "custom", title: "Custom Link", icon: "fas fa-link", defaultUrl: "https://" },
];

export default function FooterEditor() {
  const [footerData, setFooterData] = useState({
    copyright: "",
    disclaimer: "Disclaimer: All manga, manhwa, and manhua content are property of their respective creators and publishers. Content on this site is aggregated for fan translation research.",
  });
  const [socialLinks, setSocialLinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState(null);

  // New Link Form state
  const [newPlatform, setNewPlatform] = useState("discord");
  const [newTitle, setNewTitle] = useState("Discord Community");
  const [newUrl, setNewUrl] = useState("https://discord.gg/");
  const [newIcon, setNewIcon] = useState("fab fa-discord");
  const [newCustomIconUrl, setNewCustomIconUrl] = useState("");

  // Edit Link Modal state
  const [editingLink, setEditingLink] = useState(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);

  const notifyFooterUpdated = (updatedLinks) => {
    try {
      window.dispatchEvent(new CustomEvent("mgeko_footer_updated", { detail: { social_links: updatedLinks } }));
    } catch {}
  };

  // What visitors see is what the server stored (plan.md P1-10): show the
  // server's list after every change, and an error when it refused one.
  const applyServerLinks = async (res) => {
    let links = Array.isArray(res?.links) ? res.links : null;
    if (!links) {
      const fresh = await api.footer.getSocialLinks();
      links = Array.isArray(fresh?.links) ? fresh.links : socialLinks;
    }
    setSocialLinks(links);
    notifyFooterUpdated(links);
    return links;
  };
  const refused = (what, err) =>
    setNotice({ type: "error", message: `${what}: ${err?.message || "the server refused it."} Nothing was changed.` });

  const loadFooter = async () => {
    setLoading(true);
    try {
      const data = await api.footer.get();
      if (data) {
        setFooterData({
          copyright: data.copyright || "",
          disclaimer: data.disclaimer || "Disclaimer: All manga content are property of their respective creators.",
        });
        if (Array.isArray(data.social_links)) {
          setSocialLinks(data.social_links);
        }
      }
    } catch (err) {
      console.error("Failed to load footer data", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadFooter();
  }, []);

  const handlePlatformPresetChange = (platKey) => {
    setNewPlatform(platKey);
    const found = PRESET_PLATFORMS.find((p) => p.platform === platKey);
    if (found) {
      setNewTitle(found.title);
      setNewIcon(found.icon);
      setNewUrl(found.defaultUrl);
    }
  };

  const handleEditPlatformPresetChange = (platKey) => {
    if (!editingLink) return;
    const found = PRESET_PLATFORMS.find((p) => p.platform === platKey);
    if (found) {
      setEditingLink((prev) => ({
        ...prev,
        platform: platKey,
        title: found.title,
        icon: found.icon,
        url: prev.url && prev.url !== "https://" ? prev.url : found.defaultUrl,
      }));
    } else {
      setEditingLink((prev) => ({ ...prev, platform: platKey }));
    }
  };

  const handleSaveText = async (e) => {
    e.preventDefault();
    setSaving(true);
    setNotice(null);
    try {
      await api.footer.update({
        ...footerData,
        social_links: socialLinks,
      });
      notifyFooterUpdated(socialLinks);
      setNotice({ type: "success", message: "✅ Footer copyright, disclaimer, and social links saved successfully!" });
    } catch (err) {
      setNotice({ type: "error", message: "Failed to save footer: " + (err.message || "Unknown error") });
    } finally {
      setSaving(false);
    }
  };

  const handleAddSocialLink = async (e) => {
    e.preventDefault();
    if (!newUrl.trim()) return;
    try {
      const payload = {
        platform: newPlatform,
        title: newTitle.trim() || newPlatform,
        url: newUrl.trim(),
        icon: newIcon.trim() || "fas fa-link",
        custom_icon_url: newCustomIconUrl.trim(),
      };
      const res = await api.footer.addSocialLink(payload);
      await applyServerLinks(res);
      setNotice({ type: "success", message: `✅ Added "${payload.title}" to footer links!` });
      // Reset form to next preset
      handlePlatformPresetChange("twitter");
      setNewCustomIconUrl("");
    } catch (err) {
      setNotice({ type: "error", message: "Failed to add social link: " + (err.message || "Unknown error") });
    }
  };

  const handleSaveEditedLink = async (e) => {
    e.preventDefault();
    if (!editingLink || !editingLink.url.trim()) return;
    try {
      const res = await api.footer.updateSocialLink(editingLink.id, editingLink);
      await applyServerLinks(res);
      setEditingLink(null);
      setNotice({ type: "success", message: `✅ Updated "${editingLink.title}" successfully!` });
    } catch (err) {
      refused(`"${editingLink.title}" was not updated`, err);
    }
  };

  const handleToggleLink = async (id) => {
    const updated = socialLinks.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l));
    try {
      await applyServerLinks(await api.footer.saveSocialLinks(updated));
    } catch (err) {
      refused("The link was not switched", err);
    }
  };

  const handleDeleteLink = async (id) => {
    try {
      const res = await api.footer.deleteSocialLink(id);
      await applyServerLinks(res);
      setDeleteConfirmId(null);
      setNotice({ type: "success", message: "✅ Social link successfully deleted from footer!" });
    } catch (err) {
      setDeleteConfirmId(null);
      refused("The link was not deleted", err);
    }
  };

  const handleMoveLink = async (index, direction) => {
    const targetIdx = index + direction;
    if (targetIdx < 0 || targetIdx >= socialLinks.length) return;
    const reordered = [...socialLinks];
    const [moved] = reordered.splice(index, 1);
    reordered.splice(targetIdx, 0, moved);
    try {
      await applyServerLinks(await api.footer.saveSocialLinks(reordered));
    } catch (err) {
      refused("The new order was not saved", err);
    }
  };

  return (
    <div className="space-y-6 text-xs">
      {notice && (
        <div
          className={`p-3.5 rounded-xl border text-xs flex items-center justify-between shadow-md ${
            notice.type === "error"
              ? "bg-red-950/40 border-red-800 text-red-300"
              : "bg-emerald-950/40 border-emerald-800 text-emerald-300"
          }`}
        >
          <span>{notice.message}</span>
          <button type="button" onClick={() => setNotice(null)} className="text-gray-400 hover:text-white ml-2 text-sm">
            ✕
          </button>
        </div>
      )}

      {/* Section 1: Copyright & Legal Disclaimer */}
      <form onSubmit={handleSaveText} className="space-y-4">
        <div>
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <i className="fas fa-copyright text-[#00AEF0]"></i>
            <span>Copyright &amp; Site Disclaimer</span>
          </h3>
          <p className="text-[11px] text-[#8b93a3] mt-0.5">
            Customize the copyright notice line and legal aggregation disclaimer displayed across all pages.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3">
          <div>
            <label className="text-xs font-bold text-gray-300 block mb-1">
              Footer Copyright Text
            </label>
            <input
              type="text"
              required
              value={footerData.copyright}
              onChange={(e) => setFooterData({ ...footerData, copyright: e.target.value })}
              placeholder="e.g., © 2026 Your Site. All rights reserved."
              className="w-full px-3.5 py-2.5 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
            />
          </div>

          <div>
            <label className="text-xs font-bold text-gray-300 block mb-1">
              Footer Legal Disclaimer
            </label>
            <textarea
              rows={2}
              value={footerData.disclaimer}
              onChange={(e) => setFooterData({ ...footerData, disclaimer: e.target.value })}
              placeholder="Disclaimer text..."
              className="w-full p-3 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] resize-none"
            />
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          className="px-5 py-2.5 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold transition flex items-center gap-2 disabled:opacity-50"
        >
          <i className={saving ? "fas fa-spinner fa-spin" : "fas fa-save"}></i>
          <span>{saving ? "Saving…" : "Save Copyright & Disclaimer"}</span>
        </button>
      </form>

      {/* Section 2: Social Links & Community Handles */}
      <div className="border-t border-[#262a33] pt-6 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-bold text-white flex items-center gap-2">
              <i className="fas fa-share-alt text-[#00AEF0]"></i>
              <span>Community Social Handles &amp; Contact Channels</span>
            </h3>
            <p className="text-[11px] text-[#8b93a3] mt-0.5">
              Easily change, delete, reorder, or add Discord community, Twitter/X update, Telegram channel, Reddit community, and Contact &amp; support links.
            </p>
          </div>
        </div>

        {/* Existing Links List */}
        <div className="space-y-2">
          {socialLinks.length === 0 ? (
            <div className="p-4 rounded-xl bg-[#101216] border border-[#262a33] text-center text-[#8b93a3]">
              No social links configured yet. Add your community channel below!
            </div>
          ) : (
            socialLinks.map((link, idx) => (
              <div
                key={link.id}
                className="p-3 bg-[#101216] border border-[#262a33] rounded-xl flex items-center justify-between gap-3 transition hover:border-[#374151]"
              >
                <div className="flex items-center gap-3 min-w-0">
                  {/* Reorder Buttons */}
                  <div className="flex flex-col gap-0.5 flex-shrink-0">
                    <button
                      type="button"
                      disabled={idx === 0}
                      onClick={() => handleMoveLink(idx, -1)}
                      className="text-gray-500 hover:text-white disabled:opacity-20 text-[10px] p-0.5"
                      title="Move up"
                    >
                      ▲
                    </button>
                    <button
                      type="button"
                      disabled={idx === socialLinks.length - 1}
                      onClick={() => handleMoveLink(idx, 1)}
                      className="text-gray-500 hover:text-white disabled:opacity-20 text-[10px] p-0.5"
                      title="Move down"
                    >
                      ▼
                    </button>
                  </div>

                  {/* Icon */}
                  <div className="w-8 h-8 rounded-lg bg-[#15171c] border border-[#262a33] flex items-center justify-center text-sm text-[#00AEF0] flex-shrink-0">
                    {link.custom_icon_url ? (
                      <img src={link.custom_icon_url} alt={link.title} className="w-4 h-4 object-contain rounded" />
                    ) : (
                      <i className={link.icon || "fas fa-link"}></i>
                    )}
                  </div>

                  {/* Title & URL */}
                  <div className="min-w-0">
                    <span className="font-bold text-white block text-xs truncate">{link.title}</span>
                    <a
                      href={link.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-[11px] text-[#8b93a3] hover:text-[#00AEF0] transition font-mono truncate max-w-xs block"
                    >
                      {link.url}
                    </a>
                  </div>
                </div>

                <div className="flex items-center gap-2 flex-shrink-0">
                  {/* Status Toggle */}
                  <button
                    type="button"
                    onClick={() => handleToggleLink(link.id)}
                    className={`px-2.5 py-1 rounded-lg text-[10px] font-bold uppercase transition ${
                      link.enabled
                        ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                        : "bg-gray-800 text-gray-400 border border-gray-700"
                    }`}
                    title={link.enabled ? "Click to hide from footer" : "Click to display in footer"}
                  >
                    {link.enabled ? "Active" : "Hidden"}
                  </button>

                  {/* Edit Button */}
                  <button
                    type="button"
                    onClick={() => setEditingLink({ ...link })}
                    className="p-1.5 px-2.5 rounded-lg text-gray-300 hover:text-white bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] transition flex items-center gap-1"
                    title="Change / edit this social link"
                  >
                    <i className="fas fa-edit text-xs text-[#00AEF0]"></i>
                    <span className="hidden sm:inline text-[11px]">Edit</span>
                  </button>

                  {/* Delete Button */}
                  <button
                    type="button"
                    onClick={() => setDeleteConfirmId(link.id)}
                    className="p-1.5 px-2.5 rounded-lg text-red-400 hover:text-red-300 bg-red-950/20 hover:bg-red-950/40 border border-red-800/40 transition flex items-center gap-1"
                    title="Delete this social link"
                  >
                    <i className="fas fa-trash-alt text-xs"></i>
                    <span className="hidden sm:inline text-[11px]">Delete</span>
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Add New Social Link Form */}
        <form onSubmit={handleAddSocialLink} className="p-4 bg-[#101216] border border-[#262a33] rounded-2xl space-y-3">
          <div className="flex items-center gap-2">
            <i className="fas fa-plus-circle text-[#00AEF0]"></i>
            <span className="font-bold text-white text-xs">Create / Add New Social Channel</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-gray-400 block mb-1">Platform Preset</label>
              <select
                value={newPlatform}
                onChange={(e) => handlePlatformPresetChange(e.target.value)}
                className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
              >
                {PRESET_PLATFORMS.map((p) => (
                  <option key={p.platform} value={p.platform}>
                    {p.title}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-[11px] font-semibold text-gray-400 block mb-1">Display Title</label>
              <input
                type="text"
                required
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="e.g., Discord Community"
                className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
              />
            </div>

            <div>
              <label className="text-[11px] font-semibold text-gray-400 block mb-1">Target URL / Link</label>
              <input
                type="text"
                required
                value={newUrl}
                onChange={(e) => setNewUrl(e.target.value)}
                placeholder="https://discord.gg/..."
                className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div>
              <label className="text-[11px] font-semibold text-gray-400 block mb-1">
                Custom Favicon / Image URL (Optional)
              </label>
              <input
                type="url"
                value={newCustomIconUrl}
                onChange={(e) => setNewCustomIconUrl(e.target.value)}
                placeholder="https://example.com/favicon.png"
                className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-400 block mb-1">
                FontAwesome Icon Class
              </label>
              <input
                type="text"
                value={newIcon}
                onChange={(e) => setNewIcon(e.target.value)}
                placeholder="fab fa-discord"
                className="w-full px-3 py-2 rounded-xl bg-[#15171c] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
              />
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              className="px-4 py-2 rounded-xl bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold transition flex items-center gap-1.5 shadow"
            >
              <i className="fas fa-plus"></i>
              <span>Add Social Channel</span>
            </button>
          </div>
        </form>
      </div>

      {/* Edit Link Modal */}
      {editingLink && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <form
            onSubmit={handleSaveEditedLink}
            className="bg-[#15171c] border border-[#262a33] rounded-2xl max-w-lg w-full p-5 space-y-4 shadow-2xl text-xs"
          >
            <div className="flex items-center justify-between border-b border-[#262a33] pb-3">
              <div className="flex items-center gap-2">
                <i className="fas fa-edit text-[#00AEF0] text-sm"></i>
                <h3 className="text-sm font-bold text-white">Edit Social Link: {editingLink.title}</h3>
              </div>
              <button
                type="button"
                onClick={() => setEditingLink(null)}
                className="text-gray-400 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="text-[11px] font-semibold text-gray-400 block mb-1">Platform Preset</label>
                <select
                  value={editingLink.platform || "custom"}
                  onChange={(e) => handleEditPlatformPresetChange(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                >
                  {PRESET_PLATFORMS.map((p) => (
                    <option key={p.platform} value={p.platform}>
                      {p.title}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-[11px] font-semibold text-gray-400 block mb-1">Display Title</label>
                <input
                  type="text"
                  required
                  value={editingLink.title}
                  onChange={(e) => setEditingLink({ ...editingLink, title: e.target.value })}
                  placeholder="e.g. Discord Community, Twitter / X Updates"
                  className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0]"
                />
              </div>

              <div>
                <label className="text-[11px] font-semibold text-gray-400 block mb-1">Target URL</label>
                <input
                  type="text"
                  required
                  value={editingLink.url}
                  onChange={(e) => setEditingLink({ ...editingLink, url: e.target.value })}
                  placeholder="https://..."
                  className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="text-[11px] font-semibold text-gray-400 block mb-1">
                    FontAwesome Icon
                  </label>
                  <input
                    type="text"
                    value={editingLink.icon || ""}
                    onChange={(e) => setEditingLink({ ...editingLink, icon: e.target.value })}
                    placeholder="fab fa-discord"
                    className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                  />
                </div>

                <div>
                  <label className="text-[11px] font-semibold text-gray-400 block mb-1">
                    Custom Icon URL (Optional)
                  </label>
                  <input
                    type="url"
                    value={editingLink.custom_icon_url || ""}
                    onChange={(e) => setEditingLink({ ...editingLink, custom_icon_url: e.target.value })}
                    placeholder="https://..."
                    className="w-full px-3 py-2 rounded-xl bg-[#101216] border border-[#262a33] text-xs text-white focus:outline-none focus:border-[#00AEF0] font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="edit_enabled"
                  checked={editingLink.enabled !== false}
                  onChange={(e) => setEditingLink({ ...editingLink, enabled: e.target.checked })}
                  className="rounded text-[#00AEF0] bg-[#101216] border-[#262a33]"
                />
                <label htmlFor="edit_enabled" className="text-gray-300 font-semibold cursor-pointer">
                  Display this channel in the public footer
                </label>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setEditingLink(null)}
                className="px-3.5 py-1.5 rounded-lg bg-[#101216] hover:bg-[#1f2330] text-gray-300 text-xs font-semibold transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="px-4 py-1.5 rounded-lg bg-[#00AEF0] hover:bg-[#0F5065] text-white text-xs font-bold transition flex items-center gap-1.5 shadow"
              >
                <i className="fas fa-check text-xs"></i>
                <span>Save Changes</span>
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="fixed inset-0 z-50 flex [align-items:safe_center] justify-center overflow-y-auto bg-black/80 backdrop-blur-sm p-4 animate-in fade-in">
          <div className="bg-[#15171c] border border-red-500/50 rounded-2xl max-w-sm w-full p-5 space-y-4 shadow-2xl text-xs">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-red-600/20 text-red-400 flex items-center justify-center text-base flex-shrink-0">
                <i className="fas fa-trash-alt"></i>
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Delete Social Link</h3>
                <p className="text-[11px] text-gray-400">Are you sure you want to remove this link from the footer?</p>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#262a33]">
              <button
                type="button"
                onClick={() => setDeleteConfirmId(null)}
                className="px-3.5 py-1.5 rounded-lg bg-[#101216] hover:bg-[#1f2330] text-gray-300 text-xs font-semibold transition"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => handleDeleteLink(deleteConfirmId)}
                className="px-4 py-1.5 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs font-bold transition flex items-center gap-1.5 shadow"
              >
                <i className="fas fa-trash-alt text-xs"></i>
                <span>Delete Link</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
