import bleach

ALLOWED_TAGS = ["strong", "em", "a", "p"]
ALLOWED_ATTRIBUTES = {"a": ["href", "title"]}

# Ad slots may carry richer, admin-authored markup than free-text fields
# (image/iframe based display ads), so they use a wider tag allowlist. The
# non-negotiable requirement is that active content — <script> tags, inline
# event handlers (onclick=...), and dangerous URL schemes (javascript:) — is
# stripped so a compromised or malicious admin cannot store XSS that then
# executes in every visitor's browser. Cross-origin <iframe>s are permitted
# because the same-origin policy prevents them from reading the parent page or
# its cookies, which is how legitimate display ads are embedded.
AD_ALLOWED_TAGS = [
    "a",
    "b",
    "br",
    "div",
    "em",
    "i",
    "iframe",
    "img",
    "ins",
    "p",
    "small",
    "span",
    "strong",
    "u",
]
AD_ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "width", "height", "loading"],
    "iframe": [
        "src",
        "width",
        "height",
        "frameborder",
        "scrolling",
        "allow",
        "allowfullscreen",
        "referrerpolicy",
        "loading",
    ],
    # NOTE: inline ``style`` is intentionally omitted. Sanitizing CSS safely
    # requires the optional ``bleach[css]``/``tinycss2`` dependency; without it
    # bleach strips ``style`` entirely anyway. If ad markup needs inline styles
    # (e.g. AdSense ``style="display:block"``), add ``tinycss2`` (pinned) plus a
    # restricted CSSSanitizer as a follow-up rather than allowing raw CSS.
    "ins": ["class", "data-ad-client", "data-ad-slot", "data-ad-format"],
    "div": ["class", "id"],
    "span": ["class", "id"],
}
AD_ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


def sanitize_html(text: str | None) -> str | None:
    if not text:
        return text
    return bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)


def strip_all_html(text: str | None) -> str | None:
    if not text:
        return text
    return bleach.clean(text, tags=[], strip=True)


def sanitize_ad_html(text: str | None) -> str | None:
    """Sanitize admin-authored ad markup, removing any active/executable content.

    ``<script>`` tags, inline event handlers and ``javascript:`` URLs are
    stripped while common display-ad container tags are preserved.
    """

    if not text:
        return text
    return bleach.clean(
        text,
        tags=AD_ALLOWED_TAGS,
        attributes=AD_ALLOWED_ATTRIBUTES,
        protocols=AD_ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
