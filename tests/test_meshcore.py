import pytest
import pytest_asyncio
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.session.manager import SessionManager
from citadel.transport.engines.meshcore.meshcore_refactored import MeshCoreTransportEngine
from citadel.transport.engines.meshcore.session_coordinator import SessionCoordinator
from citadel.transport.packets import ToUser


@pytest_asyncio.fixture
async def context():
    data = {}
    data["config"] = Config()
    data["db"] = DatabaseManager(data["config"])
    await data["db"].start()
    data["session_mgr"] = SessionManager(data["config"], data["db"])

    yield data

    await data["db"].shutdown()


def test_chunk_message(context):
    # Test the protocol handler's chunking functionality
    from citadel.transport.engines.meshcore.protocol_handler import ProtocolHandler

    # Create a mock MeshCore object
    mock_meshcore = Mock()
    handler = ProtocolHandler(context['config'], context['db'], mock_meshcore)

    long_msg = "this is a test of a very long message which means i need to keep typing for quite a while to make sure that i'm well over the 140 character limit that we're currently using for meshcore packets."

    chunks = handler._chunk_message(long_msg, 140)

    # Basic chunking validation
    assert len(chunks) > 1, "Long message should be split into multiple chunks"
    assert len(chunks) == 2, "This specific message should create exactly 2 chunks"

    # Check that chunks contain chunk markers
    assert "[1/2]" in chunks[0], "First chunk should have [1/2] marker"
    assert "[2/2]" in chunks[1], "Second chunk should have [2/2] marker"

    # Check that each chunk respects the length limit (allowing for chunk markers)
    for i, chunk in enumerate(chunks):
        assert len(chunk) <= 140, f"Chunk {i+1} exceeds 140 character limit: {len(chunk)} chars"

    # Check that chunks contain parts of the original message
    assert "this is a test" in chunks[0], "First chunk should contain beginning of message"
    assert "meshcore packets" in chunks[1], "Second chunk should contain end of message"


def test_meshcore_engine_initialization(context):
    """Test that MeshCoreTransportEngine initializes correctly with proper parameter order."""
    # Should not raise any exceptions with config, db, session_mgr order
    engine = MeshCoreTransportEngine(context['config'], context['db'], context['session_mgr'])

    # Check that basic attributes are set
    assert engine.config == context['config']
    assert engine.db == context['db']
    assert engine.session_mgr == context['session_mgr']
    assert hasattr(engine, 'mc_config')