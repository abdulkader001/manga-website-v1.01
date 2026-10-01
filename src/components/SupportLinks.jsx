import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "../services/api";

// Footer "Support the site" block. Every link and address here was checked
// by the server (known donation platforms over https, addresses that match
// their network) and can only be changed by the main admin.

const PLATFORM_ICON = {
  kofi: "fas fa-mug-hot",
  buymeacoffee: "fas fa-mug-hot",
  paypal: "fab fa-paypal",
  patreon: "fab fa-patreon",
  github: "fab fa-github",
  opencollective: "fas fa-hand-holding-heart",
  liberapay: "fas fa-hand-holding-heart",
  stripe: "fab fa-stripe-s",
  boosty: "fas fa-heart",
};

function CryptoEntry({ entry }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(entry.address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* the address stays selectable */
    }
  };
  return (
    <div className="rounded-xl bg-[#15171c] border border-[#262a33] p-2.5 text-left space-y-1 max-w-full">
      <div className="text-[11px] font-bold text-white flex items-center gap-1.5">
        <i className="fab fa-bitcoin text-amber-400"></i>
        {entry.label}
      </div>
      <div className="flex items-center gap-2">
        <code className="text-[10px] text-gray-300 break-all select-all">{entry.address}</code>
        <button
          type="button"
          onClick={copy}
          className="flex-none px-2 py-1 rounded-lg text-[10px] font-bold border border-[#262a33] text-gray-300 hover:text-white hover:border-[#00AEF0]"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="text-[10px] text-amber-300/80">Send only on this network.{entry.note ? ` ${entry.note}` : ""}</p>
    </div>
  );
}

export default function SupportLinks() {
  const { data } = useQuery({
    queryKey: ["supportLinks"],
    queryFn: () => api.support.get(),
    staleTime: 5 * 60 * 1000,
  });
  const links = Array.isArray(data?.links) ? data.links : [];
  if (links.length === 0) return null;
  const payLinks = links.filter((l) => l.kind === "link");
  const crypto = links.filter((l) => l.kind === "crypto");

  return (
    <section className="pb-6 border-b border-[#262a33]/60 space-y-3 text-center" aria-label="Support the site">
      <h2 className="text-xs font-bold uppercase tracking-wider text-gray-300">
        <i className="fas fa-heart text-pink-400 mr-1.5"></i>Support the site
      </h2>
      {payLinks.length > 0 && (
        <div className="flex flex-wrap items-center justify-center gap-2.5 text-xs font-semibold">
          {payLinks.map((l) => (
            <a
              key={l.id}
              href={l.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              referrerPolicy="no-referrer"
              title={l.note || l.label}
              className="px-3 py-1.5 rounded-xl bg-[#15171c] hover:bg-[#1f2330] border border-[#262a33] hover:border-pink-400 text-gray-200 hover:text-white transition flex items-center gap-2"
            >
              <i className={`${PLATFORM_ICON[l.platform] || "fas fa-heart"} text-pink-400`}></i>
              <span>{l.label}</span>
            </a>
          ))}
        </div>
      )}
      {crypto.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2 max-w-3xl mx-auto">
          {crypto.map((c) => (
            <CryptoEntry key={c.id} entry={c} />
          ))}
        </div>
      )}
    </section>
  );
}
