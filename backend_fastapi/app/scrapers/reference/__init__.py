"""Reference sites: what the owner's chosen source sites look like.

The owner saved the homepages of the sites this project is meant to read
(``pages/<host>.html.gz``, scripts cut short and styles removed). ``SITES``
records what those pages show about each site: where series and chapters
live, how the reader delivers its pictures, what gets in the way, and
whether the site can be read at all.

Two users:

* the Scraper AI: ``notes_for(host)`` is added to its prompt when it writes
  a parser for one of these sites, together with the built-in parser as a
  starting point, so even a small model starts from facts;
* people (or an AI assistant) adding a parser by hand: ``GUIDE.md`` in this
  folder is the step-by-step recipe, and the saved pages are test inputs
  (``load_page``).

Facts marked ``seen`` were read from the saved pages on 2026-10-03; facts
marked ``known`` come from public scraper projects (gallery-dl, HakuNeko,
Mihon/Tachiyomi extensions) and were not checked against a live page.
"""

from __future__ import annotations

from .sites import SITES, Site, load_page, notes_for, site_for

__all__ = ["SITES", "Site", "load_page", "notes_for", "site_for"]
