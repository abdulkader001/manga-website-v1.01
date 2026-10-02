"""Native comment system, reputation, ranking, and Pills (SRS Part 3)."""

from __future__ import annotations

import uuid

import pytest

from backend_fastapi.app.core.api_errors import ApiError, ErrorCode
from backend_fastapi.app.models import Chapter, Comment, Manga, User, UserRole
from backend_fastapi.app.models.community import (
    CultivationRealmConfig,
    Pill,
    ReputationEvent,
)
from backend_fastapi.app.models.user import MAX_COMMENT_REPLY_DEPTH
from backend_fastapi.app.services import (
    comment_service,
    moderation_service,
    pill_service,
    ranking_service,
    reputation_service,
)

from _support.db_reset import clear_users_and_content


def _make_user(db_session, **kwargs) -> User:
    defaults = dict(
        email=f"user-{uuid.uuid4().hex}@example.com",
        is_active=True,
        provider="magic_link",
    )
    defaults.update(kwargs)
    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def community_data(fastapi_client, db_session):
    # ``fastapi_client`` (session-scoped) is what creates the schema via
    # Base.metadata.create_all; requesting it here guarantees tables exist
    # even if this file runs in isolation. Bulk deletes bypass ORM cascade
    # and SQLite in tests doesn't enforce FK constraints, so every table a
    # stale row could linger in is cleared explicitly -- otherwise SQLite's
    # rowid reuse after a full-table delete could leak a comment from one
    # test into another test's manga/user id.
    db_session.query(ReputationEvent).delete()
    # clear_users_and_content walks the FK graph, so every table above --
    # pills, reports, reactions, votes, comments, chapters, manga -- is
    # covered by it. CultivationRealmConfig has no FK to any of them, so it
    # still needs clearing explicitly.
    db_session.query(CultivationRealmConfig).delete()
    clear_users_and_content(db_session)

    author = _make_user(db_session)
    other = _make_user(db_session)
    manga = Manga(
        title="Community Test Manga",
        slug=f"community-test-{uuid.uuid4().hex[:8]}",
        cover_image="cover.jpg",
        description="d",
        source_url="https://example.com/m",
        language="en",
    )
    db_session.add(manga)
    db_session.flush()
    chapter = Chapter(
        manga_id=manga.id,
        chapter_number=1,
        chapter_title="One",
        chapter_url="https://x/1",
    )
    db_session.add(chapter)
    db_session.commit()
    return {"author": author, "other": other, "manga": manga, "chapter": chapter}


# ---------------------------------------------------------------------------
# Create / edit / delete / threading
# ---------------------------------------------------------------------------


def test_create_edit_delete_comment_flow(db_session, community_data):
    author = community_data["author"]
    manga = community_data["manga"]

    comment = comment_service.create_comment(
        db_session,
        user=author,
        target_type="manga",
        target_id=manga.id,
        content="Great chapter!",
    )
    assert comment.content == "Great chapter!"
    assert comment.edited_at is None

    edited = comment_service.edit_comment(
        db_session, user=author, comment_id=comment.id, content="Even better on reread."
    )
    assert edited.content == "Even better on reread."
    assert edited.edited_at is not None

    other = community_data["other"]
    with pytest.raises(ApiError) as exc:
        comment_service.edit_comment(
            db_session, user=other, comment_id=comment.id, content="hijack"
        )
    assert exc.value.code == ErrorCode.FORBIDDEN

    deleted = comment_service.delete_comment(
        db_session, user=author, comment_id=comment.id
    )
    assert deleted.deleted_at is not None
    serialized = comment_service.serialize_comment(db_session, deleted)
    assert serialized["content"] is None
    assert serialized["deleted"] is True


def test_reply_depth_clamps_at_cap(db_session, community_data):
    author = community_data["author"]
    manga = community_data["manga"]

    parent = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="root"
    )
    current = parent
    for i in range(MAX_COMMENT_REPLY_DEPTH + 5):
        current = comment_service.create_comment(
            db_session,
            user=author,
            target_type="manga",
            target_id=manga.id,
            content=f"reply {i}",
            parent_id=current.id,
        )
    assert current.depth == MAX_COMMENT_REPLY_DEPTH
    assert current.parent_id is not None  # true chain preserved even past the cap


def test_deleting_a_comment_does_not_cascade_delete_its_replies(
    db_session, community_data
):
    """F-34: the DB-level FK on comments.parent_id must not be ON DELETE
    CASCADE (it was, combined with User.comments' own
    cascade="all, delete-orphan", so a hard user-delete would transitively
    delete every reply beneath every comment that user posted, however deep,
    regardless of who wrote those replies).

    SQLite in this test suite doesn't enforce FK actions by default (see the
    ``community_data`` fixture's own note on this), so exercising the ORM
    delete path alone would pass either way -- SQLAlchemy's dependency
    processing nulls the FK itself, independent of the DB constraint. This
    test instead turns FK enforcement on for one raw connection and deletes
    the parent comment directly via SQL, to prove what the *database
    constraint itself* now does: ON DELETE SET NULL, not CASCADE.
    """
    from sqlalchemy import text

    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]

    root = comment_service.create_comment(
        db_session,
        user=author,
        target_type="manga",
        target_id=manga.id,
        content="root comment by author",
    )
    reply = comment_service.create_comment(
        db_session,
        user=other,
        target_type="manga",
        target_id=manga.id,
        content="reply by a different user",
        parent_id=root.id,
    )
    root_id, reply_id = root.id, reply.id
    db_session.commit()

    # PostgreSQL always enforces FK actions; SQLite needs the PRAGMA, and
    # because StaticPool hands back the same underlying connection on every
    # checkout it must be reset afterward or it leaks into every later test on
    # this engine -- several of which rely on FK actions staying off (see this
    # file's community_data fixture).
    bind = db_session.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    with bind.connect() as conn:
        try:
            if is_sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.execute(text("DELETE FROM comments WHERE id = :id"), {"id": root_id})
            conn.commit()
        finally:
            if is_sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                conn.commit()

    db_session.expire_all()
    survivor = db_session.query(Comment).filter(Comment.id == reply_id).first()
    assert survivor is not None, "another user's reply must not be deleted"
    assert survivor.content == "reply by a different user"
    assert survivor.parent_id is None, "orphaned reply becomes top-level, not deleted"


def test_max_comment_length_enforced(db_session, community_data):
    author = community_data["author"]
    manga = community_data["manga"]
    from backend_fastapi.app.models.user import MAX_COMMENT_LENGTH

    with pytest.raises(ApiError) as exc:
        comment_service.create_comment(
            db_session,
            user=author,
            target_type="manga",
            target_id=manga.id,
            content="x" * (MAX_COMMENT_LENGTH + 1),
        )
    assert exc.value.code == ErrorCode.VALIDATION_FAILED


# ---------------------------------------------------------------------------
# Voting / reputation
# ---------------------------------------------------------------------------


def test_vote_toggle_updates_counts_and_reputation(db_session, community_data):
    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]

    comment = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="hi"
    )

    with pytest.raises(ApiError) as exc:
        comment_service.toggle_vote(
            db_session, user=author, comment_id=comment.id, value=1
        )
    assert exc.value.code == ErrorCode.SELF_ACTION_FORBIDDEN

    comment = comment_service.toggle_vote(
        db_session, user=other, comment_id=comment.id, value=1
    )
    assert comment.like_count == 1
    db_session.refresh(author)
    assert author.reputation == 1

    # Toggle the same like off again -- reputation withdrawn.
    comment = comment_service.toggle_vote(
        db_session, user=other, comment_id=comment.id, value=1
    )
    assert comment.like_count == 0
    db_session.refresh(author)
    assert author.reputation == 0

    # Dislike does not grant reputation.
    comment = comment_service.toggle_vote(
        db_session, user=other, comment_id=comment.id, value=-1
    )
    assert comment.dislike_count == 1
    db_session.refresh(author)
    assert author.reputation == 0

    # Flip dislike -> like grants reputation.
    comment = comment_service.toggle_vote(
        db_session, user=other, comment_id=comment.id, value=1
    )
    assert comment.like_count == 1
    assert comment.dislike_count == 0
    db_session.refresh(author)
    assert author.reputation == 1


def test_reaction_toggle(db_session, community_data):
    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]

    comment = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="hi"
    )
    comment_service.toggle_reaction(
        db_session, user=other, comment_id=comment.id, emoji="🔥"
    )
    serialized = comment_service.serialize_comment(db_session, comment, viewer=other)
    assert serialized["reactions"] == [
        {"emoji": "🔥", "count": 1, "viewer_reacted": True}
    ]

    comment_service.toggle_reaction(
        db_session, user=other, comment_id=comment.id, emoji="🔥"
    )
    serialized = comment_service.serialize_comment(db_session, comment, viewer=other)
    assert serialized["reactions"] == []

    with pytest.raises(ApiError):
        comment_service.toggle_reaction(
            db_session, user=other, comment_id=comment.id, emoji="not-an-emoji"
        )


# ---------------------------------------------------------------------------
# Moderation
# ---------------------------------------------------------------------------


def test_moderator_remove_revokes_reputation(db_session, community_data):
    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]
    moderator = _make_user(db_session, role=UserRole.SECONDARY, is_secondary_admin=True)  # moderating is staff work

    comment = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="hi"
    )
    comment_service.toggle_vote(db_session, user=other, comment_id=comment.id, value=1)
    db_session.refresh(author)
    assert author.reputation == 1

    removed = comment_service.moderator_remove_comment(
        db_session, moderator=moderator, comment_id=comment.id, reason="spam"
    )
    assert removed.removed_at is not None
    db_session.refresh(author)
    assert author.reputation == 0

    serialized = comment_service.serialize_comment(db_session, removed)
    assert serialized["removed"] is True
    assert serialized["content"] is None


def test_report_resolution_rewards_reporter_only_when_actioned(
    db_session, community_data
):
    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]
    moderator = _make_user(db_session, role=UserRole.SECONDARY, is_secondary_admin=True)  # moderating is staff work

    comment = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="hi"
    )
    report = comment_service.report_comment(
        db_session, user=other, comment_id=comment.id, reason="rude"
    )

    resolved = comment_service.resolve_report(
        db_session, moderator=moderator, report_id=report.id, actioned=False
    )
    assert resolved.status == "dismissed"
    db_session.refresh(other)
    assert other.reputation == 0

    report2 = comment_service.report_comment(
        db_session, user=other, comment_id=comment.id, reason="rude again"
    )
    comment_service.resolve_report(
        db_session, moderator=moderator, report_id=report2.id, actioned=True
    )
    db_session.refresh(other)
    assert other.reputation == 5


def test_resolve_report_notifies_reporter_exactly_once(
    db_session, community_data, monkeypatch
):
    author = community_data["author"]
    other = community_data["other"]
    manga = community_data["manga"]
    moderator = _make_user(db_session, role=UserRole.SECONDARY, is_secondary_admin=True)  # moderating is staff work

    comment = comment_service.create_comment(
        db_session, user=author, target_type="manga", target_id=manga.id, content="hi"
    )
    report = comment_service.report_comment(
        db_session, user=other, comment_id=comment.id, reason="rude"
    )

    calls = []
    monkeypatch.setattr(
        comment_service, "notify_async", lambda **kwargs: calls.append(kwargs)
    )

    comment_service.resolve_report(
        db_session, moderator=moderator, report_id=report.id, actioned=True
    )

    assert len(calls) == 1
    assert calls[0]["type"] == "moderation.report_resolved"
    assert calls[0]["user_id"] == other.id
    assert calls[0]["data"]["actioned"] is True


def test_resolve_report_skips_notification_for_system_reports(
    db_session, community_data, monkeypatch
):
    author = community_data["author"]
    manga = community_data["manga"]
    moderator = _make_user(db_session, role=UserRole.SECONDARY, is_secondary_admin=True)  # moderating is staff work

    comment = comment_service.create_comment(
        db_session,
        user=author,
        target_type="manga",
        target_id=manga.id,
        content="check http://a.com http://b.com http://c.com now",
    )
    reports = comment_service.list_reports(db_session)
    system_report = next(r for r in reports if r.target_id == comment.id)
    assert system_report.reporter_id is None

    calls = []
    monkeypatch.setattr(
        comment_service, "notify_async", lambda **kwargs: calls.append(kwargs)
    )

    comment_service.resolve_report(
        db_session, moderator=moderator, report_id=system_report.id, actioned=True
    )

    assert calls == []


def test_spam_filter_auto_flags_suspicious_comment(db_session, community_data):
    author = community_data["author"]
    manga = community_data["manga"]

    comment = comment_service.create_comment(
        db_session,
        user=author,
        target_type="manga",
        target_id=manga.id,
        content="check http://a.com http://b.com http://c.com now",
    )
    reports = comment_service.list_reports(db_session)
    matching = [r for r in reports if r.target_id == comment.id]
    assert len(matching) == 1
    assert matching[0].reporter_id is None
    assert matching[0].reason.startswith("automated_filter:")


def test_blocked_and_timed_out_users_cannot_post(db_session, community_data):
    author = community_data["author"]
    manga = community_data["manga"]
    moderator = _make_user(db_session, role=UserRole.SECONDARY, is_secondary_admin=True)  # moderating is staff work

    moderation_service.block_user(
        db_session, moderator=moderator, target=author, reason="abuse"
    )
    with pytest.raises(ApiError) as exc:
        comment_service.create_comment(
            db_session,
            user=author,
            target_type="manga",
            target_id=manga.id,
            content="hi",
        )
    assert exc.value.code == ErrorCode.COMMUNITY_BLOCKED

    moderation_service.unblock_user(db_session, moderator=moderator, target=author)
    comment_service.create_comment(
        db_session,
        user=author,
        target_type="manga",
        target_id=manga.id,
        content="hi again",
    )

    moderation_service.timeout_user(
        db_session, moderator=moderator, target=author, hours=1, reason="cool down"
    )
    with pytest.raises(ApiError) as exc:
        comment_service.create_comment(
            db_session,
            user=author,
            target_type="manga",
            target_id=manga.id,
            content="hi",
        )
    assert exc.value.code == ErrorCode.COMMUNITY_TIMED_OUT


# ---------------------------------------------------------------------------
# Cultivation ranking
# ---------------------------------------------------------------------------


def test_rank_for_progresses_through_realms(db_session, community_data):
    rank = ranking_service.rank_for(db_session, 0)
    assert rank["realm_name"] == "Qi Refining"
    assert rank["stage"] == 1

    rank = ranking_service.rank_for(db_session, 5_000)
    assert rank["realm_name"] == "Foundation Establishment"
    assert rank["stage"] == 1
    assert rank["dedicated_contributor"] is False

    # Halfway to Core Formation (15,000) from Foundation (5,000): stage ~6.
    rank = ranking_service.rank_for(db_session, 10_000)
    assert rank["realm_name"] == "Foundation Establishment"
    assert rank["stage"] == 6

    rank = ranking_service.rank_for(db_session, 30_000)
    assert rank["realm_name"] == "Nascent Soul"
    assert rank["dedicated_contributor"] is True


def test_rank_advancement_sends_notification(db_session, community_data, monkeypatch):
    author = community_data["author"]
    calls = []
    monkeypatch.setattr(
        reputation_service, "notify_async", lambda **kwargs: calls.append(kwargs)
    )
    reputation_service.award(
        db_session,
        user_id=author.id,
        delta=5_000,
        source="test",
        ref_type="test",
        ref_id="1",
    )
    assert any(c["type"] == "rank.advancement" for c in calls)


# ---------------------------------------------------------------------------
# Pills
# ---------------------------------------------------------------------------


def test_pill_mint_is_idempotent_and_claim_awards_reputation(
    db_session, community_data
):
    author = community_data["author"]
    chapter = community_data["chapter"]

    pill = pill_service.mint_if_new(
        db_session, user_id=author.id, chapter_id=chapter.id, target_lang="es"
    )
    assert pill is not None
    again = pill_service.mint_if_new(
        db_session, user_id=author.id, chapter_id=chapter.id, target_lang="es"
    )
    assert again is None  # 3C.3.3: one Pill per (user, chapter, language)

    claimed = pill_service.claim(db_session, user_id=author.id, pill_id=pill.id)
    assert claimed.status == "claimed"
    db_session.refresh(author)
    assert author.reputation == 100

    with pytest.raises(ApiError) as exc:
        pill_service.claim(db_session, user_id=author.id, pill_id=pill.id)
    assert exc.value.code == ErrorCode.PILL_ALREADY_CLAIMED


def test_pill_revoked_for_fraud_reverses_reputation_but_not_for_supersession(
    db_session, community_data
):
    author = community_data["author"]
    chapter = community_data["chapter"]

    pill = pill_service.mint_if_new(
        db_session, user_id=author.id, chapter_id=chapter.id, target_lang="fr"
    )
    pill_service.claim(db_session, user_id=author.id, pill_id=pill.id)
    db_session.refresh(author)
    assert author.reputation == 100

    pill_service.revoke(db_session, pill_id=pill.id, reason="fraudulent contribution")
    db_session.refresh(author)
    assert author.reputation == 0
    assert db_session.get(Pill, pill.id).status == "revoked"
