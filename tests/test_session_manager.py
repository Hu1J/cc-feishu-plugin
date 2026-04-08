import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import tempfile
from cc_feishu_bridge.claude.session_manager import SessionManager


@pytest.fixture
def manager():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    mgr = SessionManager(db_path)
    yield mgr
    Path(db_path).unlink(missing_ok=True)


def test_create_and_get_session(manager):
    session = manager.create_session("ou_123", "/Users/test/projects")
    assert session.user_id == "ou_123"
    assert session.project_path == "/Users/test/projects"
    assert session.message_count == 0
    assert session.chat_type == "p2p"
    assert session.session_key == "ou_123"  # p2p: session_key = user_id

    active = manager.get_active_session("ou_123")
    assert active is not None
    assert active.session_id == session.session_id
    assert active.chat_type == "p2p"
    assert active.session_key == "ou_123"


def test_update_session(manager):
    session = manager.create_session("ou_123", "/Users/test/projects")
    manager.update_session(session.session_id, cost=0.05, message_increment=1)
    updated = manager.get_active_session("ou_123")
    assert updated.total_cost == 0.05
    assert updated.message_count == 1


def test_get_no_session(manager):
    assert manager.get_active_session("ou_unknown") is None


def test_delete_session(manager):
    session = manager.create_session("ou_123", "/Users/test/projects")
    manager.delete_session(session.session_id)
    assert manager.get_active_session("ou_123") is None


def test_update_chat_id(tmp_path):
    """update_chat_id updates the most recent session's chat_id."""
    from cc_feishu_bridge.claude.session_manager import SessionManager
    import os
    db = os.path.join(tmp_path, "test.db")
    sm = SessionManager(db_path=db)
    s = sm.create_session("ou_user1", "/tmp")
    sm.update_chat_id("ou_user1", "oc_chat123")
    updated = sm.get_active_session("ou_user1")
    assert updated.chat_id == "oc_chat123"


def test_get_active_session_by_chat_id(tmp_path):
    """get_active_session_by_chat_id returns session with chat_id set."""
    from cc_feishu_bridge.claude.session_manager import SessionManager
    import os
    db = os.path.join(tmp_path, "test.db")
    sm = SessionManager(db_path=db)
    sm.create_session("ou_user1", "/tmp")
    sm.update_chat_id("ou_user1", "oc_chat456")
    s = sm.get_active_session_by_chat_id()
    assert s is not None
    assert s.chat_id == "oc_chat456"


def test_get_active_session_by_chat_id_none_set(tmp_path):
    """Returns None if no session has a chat_id."""
    from cc_feishu_bridge.claude.session_manager import SessionManager
    import os
    db = os.path.join(tmp_path, "test.db")
    sm = SessionManager(db_path=db)
    sm.create_session("ou_user1", "/tmp")
    s = sm.get_active_session_by_chat_id()
    assert s is None


def test_create_and_get_group_session(manager):
    """Group session: session_key = chat_id, chat_type = 'group'."""
    session = manager.create_session(
        "ou_123", "/Users/test/projects",
        chat_type="group",
        chat_id="oc_group_chat_001",
    )
    assert session.chat_type == "group"
    assert session.session_key == "oc_group_chat_001"
    assert session.user_id == "ou_123"
    assert session.chat_id == "oc_group_chat_001"

    # Lookup by session_key (chat_id) works
    active = manager.get_active_session("oc_group_chat_001")
    assert active is not None
    assert active.session_id == session.session_id
    assert active.chat_type == "group"
    assert active.session_key == "oc_group_chat_001"

    # Lookup by user_id does NOT find the group session (different session_key)
    p2p_active = manager.get_active_session("ou_123")
    assert p2p_active is None  # no p2p session created yet


def test_group_and_p2p_sessions_independent(manager):
    """Same user_open_id in group and p2p have different sessions."""
    # Create a p2p session for user ou_456
    p2p_session = manager.create_session(
        "ou_456", "/Users/test/projects",
        chat_type="p2p",
    )
    assert p2p_session.chat_type == "p2p"
    assert p2p_session.session_key == "ou_456"

    # Create a group session for the same user in a different chat
    group_session = manager.create_session(
        "ou_456", "/Users/test/projects",
        chat_type="group",
        chat_id="oc_group_chat_002",
    )
    assert group_session.chat_type == "group"
    assert group_session.session_key == "oc_group_chat_002"

    # The two sessions are independent (different session_ids)
    assert p2p_session.session_id != group_session.session_id

    # Lookup by p2p session_key finds the p2p session
    p2p_active = manager.get_active_session("ou_456")
    assert p2p_active is not None
    assert p2p_active.session_id == p2p_session.session_id
    assert p2p_active.chat_type == "p2p"

    # Lookup by group session_key finds the group session
    group_active = manager.get_active_session("oc_group_chat_002")
    assert group_active is not None
    assert group_active.session_id == group_session.session_id
    assert group_active.chat_type == "group"