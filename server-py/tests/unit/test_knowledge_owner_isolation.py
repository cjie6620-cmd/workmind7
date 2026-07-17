"""知识库文档所有者隔离单元测试。"""

from app.services.rag.ingest import doc_visible_to_user, filter_docs_for_user


def test_filter_docs_for_user_keeps_own_and_shared():
    docs = [
        {"id": "1", "ownerUserId": "alice", "title": "a"},
        {"id": "2", "ownerUserId": "bob", "title": "b"},
        {"id": "3", "ownerUserId": None, "title": "shared"},
    ]

    visible = filter_docs_for_user(docs, user_id="alice", is_admin=False)
    assert [d["id"] for d in visible] == ["1", "3"]


def test_filter_docs_for_admin_sees_all():
    docs = [
        {"id": "1", "ownerUserId": "alice"},
        {"id": "2", "ownerUserId": "bob"},
    ]
    assert len(filter_docs_for_user(docs, user_id="alice", is_admin=True)) == 2


def test_doc_visible_to_user_rejects_foreign_owner():
    assert doc_visible_to_user("bob", user_id="alice", is_admin=False) is False
    assert doc_visible_to_user(None, user_id="alice", is_admin=False) is True
    assert doc_visible_to_user("bob", user_id="alice", is_admin=True) is True
