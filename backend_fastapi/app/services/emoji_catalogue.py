"""Base Unicode emoji catalogue (SRS 3A.4.1/3A.4.2).

A floor of >=100 emojis, categorized and keyworded for the picker's search.
This set can never be removed (3A.4.4) -- it ships with the platform and is
independent of the administrator-managed ``CustomEmoji`` table.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

CATEGORY_SMILEYS = "smileys"
CATEGORY_HANDS = "hands"
CATEGORY_HEARTS = "hearts"
CATEGORY_ANIMALS = "animals"
CATEGORY_FOOD_OBJECTS = "food_objects"

CATEGORY_LABELS: Dict[str, str] = {
    CATEGORY_SMILEYS: "Smileys",
    CATEGORY_HANDS: "Hands",
    CATEGORY_HEARTS: "Hearts",
    CATEGORY_ANIMALS: "Animals",
    CATEGORY_FOOD_OBJECTS: "Food & Objects",
}

# (emoji, category, keywords...) -- keywords power the picker's search box
# ("fire" -> flame emojis, "heart" -> the heart family, etc).
_BASE_EMOJIS: List[tuple] = [
    ("😀", CATEGORY_SMILEYS, ["grin", "smile", "happy"]),
    ("😃", CATEGORY_SMILEYS, ["smile", "happy", "joy"]),
    ("😄", CATEGORY_SMILEYS, ["smile", "happy", "laugh"]),
    ("😁", CATEGORY_SMILEYS, ["grin", "smile", "teeth"]),
    ("😆", CATEGORY_SMILEYS, ["laugh", "haha", "squint"]),
    ("😅", CATEGORY_SMILEYS, ["sweat", "laugh", "relief"]),
    ("🤣", CATEGORY_SMILEYS, ["rofl", "lol", "laugh", "floor"]),
    ("😂", CATEGORY_SMILEYS, ["lol", "tears", "joy", "laugh"]),
    ("🙂", CATEGORY_SMILEYS, ["smile", "slight"]),
    ("🙃", CATEGORY_SMILEYS, ["upside", "down", "silly"]),
    ("😉", CATEGORY_SMILEYS, ["wink"]),
    ("😊", CATEGORY_SMILEYS, ["blush", "smile", "happy"]),
    ("😇", CATEGORY_SMILEYS, ["angel", "innocent", "halo"]),
    ("🥰", CATEGORY_SMILEYS, ["love", "hearts", "adore"]),
    ("😍", CATEGORY_SMILEYS, ["love", "heart", "eyes", "crush"]),
    ("🤩", CATEGORY_SMILEYS, ["star", "struck", "excited"]),
    ("😘", CATEGORY_SMILEYS, ["kiss", "love"]),
    ("😗", CATEGORY_SMILEYS, ["kiss"]),
    ("☺️", CATEGORY_SMILEYS, ["smile", "relaxed"]),
    ("😚", CATEGORY_SMILEYS, ["kiss", "closed", "eyes"]),
    ("😙", CATEGORY_SMILEYS, ["kiss", "smile"]),
    ("🥲", CATEGORY_SMILEYS, ["smile", "tear", "bittersweet"]),
    ("😋", CATEGORY_SMILEYS, ["yum", "tongue", "delicious"]),
    ("😛", CATEGORY_SMILEYS, ["tongue", "silly"]),
    ("😜", CATEGORY_SMILEYS, ["wink", "tongue", "silly"]),
    ("🤪", CATEGORY_SMILEYS, ["zany", "crazy", "goofy"]),
    ("😝", CATEGORY_SMILEYS, ["tongue", "squint"]),
    ("🤑", CATEGORY_SMILEYS, ["money", "rich"]),
    ("🤗", CATEGORY_SMILEYS, ["hug", "embrace"]),
    ("🤭", CATEGORY_SMILEYS, ["giggle", "oops", "hand"]),
    ("🤫", CATEGORY_SMILEYS, ["quiet", "shush", "secret"]),
    ("🤔", CATEGORY_SMILEYS, ["think", "hmm", "ponder"]),
    ("🤐", CATEGORY_SMILEYS, ["zipper", "quiet", "secret"]),
    ("🤨", CATEGORY_SMILEYS, ["skeptic", "eyebrow", "suspicious"]),
    ("😐", CATEGORY_SMILEYS, ["neutral", "meh"]),
    ("😑", CATEGORY_SMILEYS, ["expressionless", "blank"]),
    ("😶", CATEGORY_SMILEYS, ["no", "mouth", "silent"]),
    ("😏", CATEGORY_SMILEYS, ["smirk", "sly"]),
    ("😒", CATEGORY_SMILEYS, ["unamused", "meh"]),
    ("🙄", CATEGORY_SMILEYS, ["eyeroll", "annoyed"]),
    ("😬", CATEGORY_SMILEYS, ["grimace", "awkward", "yikes"]),
    ("🤥", CATEGORY_SMILEYS, ["lying", "pinocchio"]),
    ("😌", CATEGORY_SMILEYS, ["relieved", "calm"]),
    ("😔", CATEGORY_SMILEYS, ["sad", "pensive"]),
    ("😪", CATEGORY_SMILEYS, ["sleepy", "tired"]),
    ("🤤", CATEGORY_SMILEYS, ["drool"]),
    ("😴", CATEGORY_SMILEYS, ["sleep", "zzz"]),
    ("😷", CATEGORY_SMILEYS, ["sick", "mask"]),
    ("🤒", CATEGORY_SMILEYS, ["sick", "fever", "thermometer"]),
    ("🤕", CATEGORY_SMILEYS, ["hurt", "bandage", "injured"]),
    ("🤢", CATEGORY_SMILEYS, ["nausea", "sick", "gross"]),
    ("🤮", CATEGORY_SMILEYS, ["vomit", "sick", "gross"]),
    ("🥵", CATEGORY_SMILEYS, ["hot", "heat", "sweating"]),
    ("🥶", CATEGORY_SMILEYS, ["cold", "freezing"]),
    ("😵", CATEGORY_SMILEYS, ["dizzy", "confused"]),
    ("🤯", CATEGORY_SMILEYS, ["mindblown", "shocked", "explode"]),
    ("🤠", CATEGORY_SMILEYS, ["cowboy", "hat"]),
    ("🥳", CATEGORY_SMILEYS, ["party", "celebrate", "birthday"]),
    ("😎", CATEGORY_SMILEYS, ["cool", "sunglasses"]),
    ("🤓", CATEGORY_SMILEYS, ["nerd", "glasses"]),
    ("🧐", CATEGORY_SMILEYS, ["monocle", "inspect"]),
    ("😕", CATEGORY_SMILEYS, ["confused"]),
    ("😟", CATEGORY_SMILEYS, ["worried"]),
    ("🙁", CATEGORY_SMILEYS, ["frown", "sad"]),
    ("😮", CATEGORY_SMILEYS, ["surprise", "wow", "open", "mouth"]),
    ("😲", CATEGORY_SMILEYS, ["astonished", "shocked"]),
    ("😳", CATEGORY_SMILEYS, ["flushed", "embarrassed"]),
    ("🥺", CATEGORY_SMILEYS, ["pleading", "puppy", "eyes"]),
    ("😦", CATEGORY_SMILEYS, ["frown", "open", "mouth"]),
    ("😧", CATEGORY_SMILEYS, ["anguished"]),
    ("😨", CATEGORY_SMILEYS, ["fearful", "scared"]),
    ("😰", CATEGORY_SMILEYS, ["anxious", "sweat"]),
    ("😥", CATEGORY_SMILEYS, ["sad", "relieved", "sweat"]),
    ("😢", CATEGORY_SMILEYS, ["cry", "sad", "tear"]),
    ("😭", CATEGORY_SMILEYS, ["sob", "cry", "bawling"]),
    ("😱", CATEGORY_SMILEYS, ["scream", "shocked", "fear"]),
    ("😖", CATEGORY_SMILEYS, ["confounded"]),
    ("😣", CATEGORY_SMILEYS, ["persevere", "struggle"]),
    ("😞", CATEGORY_SMILEYS, ["disappointed", "sad"]),
    ("😓", CATEGORY_SMILEYS, ["sweat", "downcast"]),
    ("😩", CATEGORY_SMILEYS, ["weary", "tired"]),
    ("😫", CATEGORY_SMILEYS, ["tired", "exhausted"]),
    ("🥱", CATEGORY_SMILEYS, ["yawn", "tired", "bored"]),
    ("😤", CATEGORY_SMILEYS, ["huff", "frustrated", "angry"]),
    ("😡", CATEGORY_SMILEYS, ["angry", "mad", "rage"]),
    ("😠", CATEGORY_SMILEYS, ["angry", "mad"]),
    ("🤬", CATEGORY_SMILEYS, ["cursing", "angry", "swear"]),
    ("💀", CATEGORY_SMILEYS, ["skull", "dead", "dying"]),
    ("👻", CATEGORY_SMILEYS, ["ghost", "spooky"]),
    ("🤡", CATEGORY_SMILEYS, ["clown"]),
    ("👽", CATEGORY_SMILEYS, ["alien"]),
    # Hands and gestures
    ("👍", CATEGORY_HANDS, ["thumbsup", "like", "yes", "approve"]),
    ("👎", CATEGORY_HANDS, ["thumbsdown", "dislike", "no"]),
    ("👏", CATEGORY_HANDS, ["clap", "applause", "bravo"]),
    ("🙌", CATEGORY_HANDS, ["raise", "hands", "celebrate", "praise"]),
    ("👐", CATEGORY_HANDS, ["open", "hands", "hug"]),
    ("🤲", CATEGORY_HANDS, ["palms", "pray", "offer"]),
    ("🙏", CATEGORY_HANDS, ["pray", "please", "thanks", "hope"]),
    ("✌️", CATEGORY_HANDS, ["peace", "victory"]),
    ("🤞", CATEGORY_HANDS, ["crossed", "fingers", "luck", "hope"]),
    ("🤝", CATEGORY_HANDS, ["handshake", "deal", "agree"]),
    ("💪", CATEGORY_HANDS, ["strong", "muscle", "flex"]),
    ("👊", CATEGORY_HANDS, ["fist", "bump", "punch"]),
    ("✊", CATEGORY_HANDS, ["fist", "power", "solidarity"]),
    ("👋", CATEGORY_HANDS, ["wave", "hello", "bye"]),
    ("🤟", CATEGORY_HANDS, ["love", "you", "rock"]),
    ("🤙", CATEGORY_HANDS, ["call", "hangloose"]),
    ("👌", CATEGORY_HANDS, ["ok", "perfect"]),
    ("🖖", CATEGORY_HANDS, ["vulcan", "spock"]),
    ("✋", CATEGORY_HANDS, ["stop", "hand", "high", "five"]),
    ("👆", CATEGORY_HANDS, ["point", "up"]),
    ("👇", CATEGORY_HANDS, ["point", "down"]),
    ("👉", CATEGORY_HANDS, ["point", "right"]),
    ("👈", CATEGORY_HANDS, ["point", "left"]),
    # Hearts and symbols
    ("❤️", CATEGORY_HEARTS, ["heart", "love", "red"]),
    ("🧡", CATEGORY_HEARTS, ["heart", "orange"]),
    ("💛", CATEGORY_HEARTS, ["heart", "yellow"]),
    ("💚", CATEGORY_HEARTS, ["heart", "green"]),
    ("💙", CATEGORY_HEARTS, ["heart", "blue"]),
    ("💜", CATEGORY_HEARTS, ["heart", "purple"]),
    ("🖤", CATEGORY_HEARTS, ["heart", "black"]),
    ("🤍", CATEGORY_HEARTS, ["heart", "white"]),
    ("🤎", CATEGORY_HEARTS, ["heart", "brown"]),
    ("💔", CATEGORY_HEARTS, ["heartbreak", "sad", "broken"]),
    ("❣️", CATEGORY_HEARTS, ["heart", "exclamation"]),
    ("💕", CATEGORY_HEARTS, ["hearts", "love"]),
    ("💞", CATEGORY_HEARTS, ["hearts", "revolving"]),
    ("💓", CATEGORY_HEARTS, ["heart", "beating"]),
    ("💗", CATEGORY_HEARTS, ["heart", "growing"]),
    ("💖", CATEGORY_HEARTS, ["heart", "sparkle"]),
    ("💘", CATEGORY_HEARTS, ["heart", "arrow", "cupid"]),
    ("💝", CATEGORY_HEARTS, ["heart", "gift", "ribbon"]),
    ("🔥", CATEGORY_HEARTS, ["fire", "lit", "hot", "flame"]),
    ("⭐", CATEGORY_HEARTS, ["star"]),
    ("🌟", CATEGORY_HEARTS, ["star", "glow", "sparkle"]),
    ("💯", CATEGORY_HEARTS, ["100", "perfect", "score"]),
    ("✨", CATEGORY_HEARTS, ["sparkles", "shiny", "magic"]),
    ("🎉", CATEGORY_HEARTS, ["party", "celebrate", "tada"]),
    ("🎊", CATEGORY_HEARTS, ["confetti", "party"]),
    ("💢", CATEGORY_HEARTS, ["anger", "mad"]),
    ("💥", CATEGORY_HEARTS, ["boom", "explosion"]),
    ("💫", CATEGORY_HEARTS, ["dizzy", "star"]),
    ("💦", CATEGORY_HEARTS, ["sweat", "splash"]),
    ("💨", CATEGORY_HEARTS, ["dash", "wind", "fast"]),
    ("🕊️", CATEGORY_HEARTS, ["dove", "peace"]),
    # Animals
    ("🐱", CATEGORY_ANIMALS, ["cat", "kitten"]),
    ("🐶", CATEGORY_ANIMALS, ["dog", "puppy"]),
    ("🐉", CATEGORY_ANIMALS, ["dragon"]),
    ("🦊", CATEGORY_ANIMALS, ["fox"]),
    ("🐼", CATEGORY_ANIMALS, ["panda"]),
    ("🐰", CATEGORY_ANIMALS, ["rabbit", "bunny"]),
    ("🐻", CATEGORY_ANIMALS, ["bear"]),
    ("🐯", CATEGORY_ANIMALS, ["tiger"]),
    ("🦁", CATEGORY_ANIMALS, ["lion"]),
    ("🐸", CATEGORY_ANIMALS, ["frog"]),
    ("🐵", CATEGORY_ANIMALS, ["monkey"]),
    ("🦄", CATEGORY_ANIMALS, ["unicorn"]),
    ("🐧", CATEGORY_ANIMALS, ["penguin"]),
    ("🐢", CATEGORY_ANIMALS, ["turtle"]),
    ("🐍", CATEGORY_ANIMALS, ["snake"]),
    ("🦅", CATEGORY_ANIMALS, ["eagle", "bird"]),
    # Food and objects
    ("🍜", CATEGORY_FOOD_OBJECTS, ["ramen", "noodles", "food"]),
    ("🍕", CATEGORY_FOOD_OBJECTS, ["pizza", "food"]),
    ("☕", CATEGORY_FOOD_OBJECTS, ["coffee", "tea"]),
    ("🎮", CATEGORY_FOOD_OBJECTS, ["game", "controller"]),
    ("📖", CATEGORY_FOOD_OBJECTS, ["book", "read", "manga"]),
    ("⚔️", CATEGORY_FOOD_OBJECTS, ["sword", "fight", "battle"]),
    ("🍣", CATEGORY_FOOD_OBJECTS, ["sushi", "food"]),
    ("🍰", CATEGORY_FOOD_OBJECTS, ["cake", "dessert"]),
    ("🍎", CATEGORY_FOOD_OBJECTS, ["apple", "fruit"]),
    ("🍿", CATEGORY_FOOD_OBJECTS, ["popcorn", "movie"]),
    ("🎬", CATEGORY_FOOD_OBJECTS, ["movie", "clapper", "film"]),
    ("📱", CATEGORY_FOOD_OBJECTS, ["phone", "mobile"]),
    ("💻", CATEGORY_FOOD_OBJECTS, ["laptop", "computer"]),
    ("🎵", CATEGORY_FOOD_OBJECTS, ["music", "note"]),
    ("🏆", CATEGORY_FOOD_OBJECTS, ["trophy", "win", "champion"]),
]


def _entry(emoji: str, category: str, keywords: List[str]) -> Dict[str, Any]:
    return {"emoji": emoji, "category": category, "keywords": keywords}


BASE_EMOJI_CATALOGUE: List[Dict[str, Any]] = [
    _entry(emoji, category, keywords) for emoji, category, keywords in _BASE_EMOJIS
]

BASE_EMOJI_COUNT = len(BASE_EMOJI_CATALOGUE)


def categories() -> List[Dict[str, str]]:
    return [{"key": key, "label": label} for key, label in CATEGORY_LABELS.items()]


def search(query: str = "") -> List[Dict[str, Any]]:
    """Filter the base catalogue by a search term (3A.4.2). Empty query
    returns the full catalogue in its defined (category-grouped) order."""

    q = (query or "").strip().lower()
    if not q:
        return list(BASE_EMOJI_CATALOGUE)
    return [
        entry
        for entry in BASE_EMOJI_CATALOGUE
        if q in entry["emoji"]
        or any(q in kw for kw in entry["keywords"])
        or q in CATEGORY_LABELS.get(entry["category"], "").lower()
    ]


# ---------------------------------------------------------------------------
# 3A.4.4 administrator-managed custom emojis (DB-backed, on top of the base
# set above, which can never be removed).
# ---------------------------------------------------------------------------


def list_custom(db: Session) -> List[Dict[str, Any]]:
    from ..models.community import CustomEmoji

    rows = db.query(CustomEmoji).order_by(CustomEmoji.created_at.asc()).all()
    return [
        {
            "id": row.id,
            "shortcode": row.shortcode,
            "emoji": f"custom:{row.shortcode}",
            "image_url": row.image_url,
            "category": row.category,
        }
        for row in rows
    ]


def add_custom(
    db: Session,
    *,
    shortcode: str,
    image_url: str,
    category: str = "custom",
    created_by_id: Optional[int] = None,
):
    from ..core.api_errors import ApiError, ErrorCode
    from ..models.community import CustomEmoji

    clean_shortcode = (shortcode or "").strip().lower().strip(":")
    if not clean_shortcode or not clean_shortcode.replace("_", "").isalnum():
        raise ApiError(
            ErrorCode.VALIDATION_FAILED,
            "shortcode must be alphanumeric/underscore only, e.g. 'manga_thumbsup'.",
        )
    if not (image_url or "").strip():
        raise ApiError(ErrorCode.VALIDATION_FAILED, "image_url is required.")
    if db.query(CustomEmoji).filter(CustomEmoji.shortcode == clean_shortcode).first():
        raise ApiError(ErrorCode.VALIDATION_FAILED, "That shortcode is already in use.")

    emoji = CustomEmoji(
        shortcode=clean_shortcode,
        image_url=image_url,
        category=category or "custom",
        created_by_id=created_by_id,
    )
    db.add(emoji)
    db.commit()
    db.refresh(emoji)
    return emoji


def remove_custom(db: Session, emoji_id: int) -> bool:
    from ..models.community import CustomEmoji

    emoji = db.get(CustomEmoji, emoji_id)
    if emoji is None:
        return False
    db.delete(emoji)
    db.commit()
    return True


__all__ = [
    "CATEGORY_LABELS",
    "BASE_EMOJI_CATALOGUE",
    "BASE_EMOJI_COUNT",
    "categories",
    "search",
    "list_custom",
    "add_custom",
    "remove_custom",
]
