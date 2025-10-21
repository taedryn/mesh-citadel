import tempfile
import os
import pytest
import pytest_asyncio

from citadel.auth.permissions import PermissionLevel
from citadel.auth.permissions import is_allowed
from citadel.config import Config
from citadel.commands.base import BaseCommand
from citadel.commands.processor import CommandProcessor
from citadel.commands.responses import CommandResponse, MessageResponse, ErrorResponse
from citadel.db.manager import DatabaseManager
from citadel.db.initializer import initialize_database
from citadel.session.manager import SessionManager
from citadel.session.state import SessionState, WorkflowState
from citadel.transport.packets import FromUser, ToUser, FromUserType
from citadel.user.user import User
from citadel.workflows.registry import register


class DummyCommand(BaseCommand):
    def __init__(self, name, args=None):
        self.name = name
        self.args = args or []

    async def run(self, context):
        if self.name == "quit":
            context.session_mgr.expire_session(context.session_id)
            return ToUser(session_id=None, text="Goodbye!")
        return ToUser(
            session_id=context.session_id,
            text=f"Dummy {self.name} command"
        )


@pytest.fixture
def config():
    path = tempfile.NamedTemporaryFile(delete=False)
    local_config = Config()
    local_config.database['db_path'] = path.name

    yield local_config

    os.unlink(path.name)


@pytest_asyncio.fixture
async def db(config):
    DatabaseManager._instance = None
    db_mgr = DatabaseManager(config)
    await db_mgr.start()
    await initialize_database(db_mgr, config)

    await User.create(config, db_mgr, "alice", "hash", "salt", "")
    alice = User(db_mgr, 'alice')
    await alice.load()
    await alice.set_permission_level(PermissionLevel.USER)

    yield db_mgr

    await db_mgr.shutdown()


@pytest.fixture
def session_mgr(config, db):
    mgr = SessionManager(config, db)
    # assume you have a sync helper for tests
    session_id = mgr.create_session("alice")
    return mgr, session_id


@pytest.fixture
def processor(config, db, session_mgr, monkeypatch):
    mgr, session_id = session_mgr
    proc = CommandProcessor(config, db, mgr)
    proc.sessions.mark_logged_in(session_id)

    # Patch User.load to always set permission_level high enough
    # so we're testing commands, not permissions
    async def fake_load(self):
        self._permission_level = PermissionLevel.SYSOP
        self._loaded = True
    monkeypatch.setattr("citadel.user.user.User.load", fake_load)

    return proc


# ------------------------------------------------------------
# Session validation
# ------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_session(processor):
    cmd = DummyCommand("quit")
    fromuser = FromUser(
        session_id="badsessionid",
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert resp.is_error
    assert resp.error_code == "invalid_session"

# ------------------------------------------------------------
# Inline handler
# ------------------------------------------------------------


@pytest.mark.asyncio
async def test_quit_expires_session(processor, session_mgr):
    mgr, session_id = session_mgr
    cmd = DummyCommand("quit")
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert resp.text == "Goodbye!"
    assert mgr.get_session_state(session_id) is None

# ------------------------------------------------------------
# Unknown command
# ------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_command(processor, session_mgr):
    mgr, session_id = session_mgr
    cmd = DummyCommand("doesnotexist")
    fromuser = FromUser(
        session_id=session_id,
        payload=cmd,
        payload_type=FromUserType.COMMAND
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert resp.is_error
    assert resp.error_code == "permission_denied"

# ------------------------------------------------------------
# Workflow delegation
# ------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_delegation(processor, session_mgr, monkeypatch):
    # note that this workflow isn't cleaned up, so remove it from
    # registry.all_workflows if you need to add another workflow named
    # dummy
    @register
    class DummyWorkflow:
        kind = "dummy"

        async def handle(self, processor, session_id, state, command, wf):
            return ToUser(session_id=session_id, text="Handled by dummy workflow")

    mgr, session_id = session_mgr
    state = mgr.get_session_state(session_id)
    wf = WorkflowState(kind="dummy")
    mgr.set_workflow(session_id, wf)

    fromuser = FromUser(
        session_id=session_id,
        payload="anything",
        payload_type=FromUserType.WORKFLOW_RESPONSE
    )
    resp = await processor.process(fromuser)
    assert isinstance(resp, ToUser)
    assert resp.text == "Handled by dummy workflow"
