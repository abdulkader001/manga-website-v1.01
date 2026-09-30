import React from "react";
import { Link } from "react-router-dom";

/**
 * MangaCard Component
 * Displays a preview of a single manga.
 *
 * Props:
 *  - manga: {
 *      id: number,
 *      title: string,
 *      cover_image?: string,
 *      description?: string,
 *      genres?: string[] | string,
 *      popularity?: number,
 *      status?: string
 *    }
 *  - showViews: Boolean (optional) → shows popularity count if true
 */
const MangaCard = React.memo(({ manga, showViews = false }) => {
  if (!manga || !manga.id) {
    if (process.env.NODE_ENV !== "production") {
      console.warn("MangaCard received invalid manga data:", manga);
    }
    return (
      <div className="manga-card manga-card--invalid">
        Invalid Manga Data
      </div>
    );
  }

  const mangaTitle = manga.title || "Untitled Manga";
  const coverImageSrc =
    manga.cover_url || manga.cover_image || "/images/placeholder-cover.jpg";
  const description = manga.description || "";
  const genres = Array.isArray(manga.genres)
    ? manga.genres.join(", ")
    : typeof manga.genres === "string"
    ? manga.genres
    : "";
  const isHot = Boolean(manga.is_hot || (manga.daily_views && manga.daily_views >= 2500) || (manga.popularity && manga.popularity > 5000));

  return (
    <div className="manga-card relative" aria-label={mangaTitle}>
      {/* Cover */}
      <div className="manga-card__image-container relative">
        {isHot && (
          <span className="absolute top-1.5 left-1.5 z-10 px-2 py-0.5 rounded-full text-[10px] font-black uppercase tracking-wider bg-red-600 text-white shadow-lg flex items-center gap-1 animate-pulse">
            <span>🔥</span>
            <span>HOT</span>
          </span>
        )}
        <img
          src={coverImageSrc}
          alt={`Cover for ${mangaTitle}`}
          className="manga-card__image"
          referrerPolicy="no-referrer"
          loading="lazy"
          decoding="async"
          onError={(e) => {
            e.currentTarget.onerror = null;
            e.currentTarget.src = "/images/placeholder-cover.jpg";
          }}
        />
      </div>

        {/* Title */}
      <h3 className="manga-card__title">{mangaTitle}</h3>

        {/* Description */}
      {description && (
        <p className="manga-card__description" title={description}>
          {description.length > 120
            ? `${description.substring(0, 120)}…`
            : description}
        </p>
      )}
      {/* Genres */}
      {Array.isArray(manga.genres) && manga.genres.length > 0 ? (
        <div className="manga-card__genres flex flex-wrap gap-1 mt-1">
          {manga.genres.slice(0, 3).map((g, idx) => (
            <Link
              key={idx}
              to={`/browse?genre=${encodeURIComponent(g)}`}
              onClick={(e) => e.stopPropagation()}
              className="hover:text-[#00AEF0] transition underline"
            >
              {g}{idx < Math.min(manga.genres.length, 3) - 1 ? "," : ""}
            </Link>
          ))}
        </div>
      ) : genres ? (
        <p className="manga-card__genres">{genres}</p>
      ) : null}

      {/* Popularity */}
      {showViews && manga.popularity != null && (
        <p className="manga-card__views">👁 {manga.popularity}</p>
      )}

         {/* Status */}
      {manga.status && (
        <p className="manga-card__status">
          Status:{" "}
          {manga.status.charAt(0).toUpperCase() + manga.status.slice(1)}
        </p>
      )}
    </div>
  );
});

export default MangaCard;
