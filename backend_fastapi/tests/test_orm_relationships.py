from sqlalchemy.orm import Session
from backend_fastapi.app.models.manga import Manga, Chapter, ReadHistory
from backend_fastapi.app.models.user import Comment, User, UserRole
from backend_fastapi.app.models.base import Base


def test_manga_chapter_relationship(db_session: Session):
    Base.metadata.create_all(bind=db_session.get_bind())
    db = db_session
    manga = Manga(title="Test Manga", source_url="https://test.com/manga")
    db.add(manga)
    db.commit()

    chapter = Chapter(
        manga_id=manga.id, chapter_number=1, chapter_url="https://test.com/manga/1"
    )
    db.add(chapter)
    db.commit()

    assert chapter in manga.chapters
    assert chapter.manga == manga

    db.delete(manga)
    db.commit()

    assert db.query(Chapter).filter(Chapter.manga_id == manga.id).count() == 0


def test_user_history_relationship(db_session: Session):
    Base.metadata.create_all(bind=db_session.get_bind())
    db = db_session
    user = User(email="test@user.com", role=UserRole.USER)
    manga = Manga(title="Test Manga", source_url="https://test.com/manga")
    db.add(user)
    db.add(manga)
    db.commit()

    chapter = Chapter(
        manga_id=manga.id, chapter_number=1, chapter_url="https://test.com/manga/1"
    )
    db.add(chapter)
    db.commit()

    history = ReadHistory(user_id=user.id, manga_id=manga.id, chapter_id=chapter.id)
    db.add(history)
    db.commit()

    assert history in user.read_history
    assert history.user == user

    db.delete(user)
    db.commit()

    assert db.query(ReadHistory).filter(ReadHistory.user_id == user.id).count() == 0


def test_user_delete_hard_deletes_own_comments_but_orphans_other_users_replies(
    db_session: Session,
):
    """Regression test for F-34.

    ``User.comments`` is ``cascade="all, delete-orphan"`` while
    ``Comment.parent_id``'s FK is independently ``ondelete="SET NULL"`` (see
    the F-34 comments on both relationships in models/user.py). Today, a
    hard user-delete: (1) hard-deletes every comment the deleted user
    authored, and (2) does NOT delete replies to those comments written by
    OTHER users -- they survive, reparented to top-level (parent_id -> None)
    instead of being deleted with the parent.

    This behavior is intentionally left as-is pending a product decision on
    any future account-deletion feature (see the F-34 comments for why). If
    this test fails, someone changed the cascade/ondelete configuration --
    that's the intended trip-wire, not a bug to silence.
    """
    Base.metadata.create_all(bind=db_session.get_bind())
    db = db_session

    author = User(email="f34-author@example.com", role=UserRole.USER)
    replier = User(email="f34-replier@example.com", role=UserRole.USER)
    db.add_all([author, replier])
    db.commit()

    parent_comment = Comment(
        user_id=author.id,
        target_type="manga",
        target_id=1,
        content="Parent comment by the author",
    )
    db.add(parent_comment)
    db.commit()

    reply = Comment(
        user_id=replier.id,
        target_type="manga",
        target_id=1,
        content="Reply by another user",
        parent_id=parent_comment.id,
    )
    db.add(reply)
    db.commit()
    parent_id, reply_id = parent_comment.id, reply.id

    db.delete(author)
    db.commit()

    # The deleted user's own comment is hard-deleted (delete-orphan cascade).
    assert db.query(Comment).filter(Comment.id == parent_id).count() == 0

    # The other user's reply survives, reparented to top-level -- not
    # deleted alongside the comment it replied to.
    surviving_reply = db.query(Comment).filter(Comment.id == reply_id).one()
    assert surviving_reply.parent_id is None
    assert surviving_reply.user_id == replier.id
