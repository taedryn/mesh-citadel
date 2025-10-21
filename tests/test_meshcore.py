import pytest
import pytest_asyncio
from citadel.config import Config
from citadel.db.manager import DatabaseManager
from citadel.session.manager import SessionManager
from citadel.transport.engines.meshcore import MeshCoreTransportEngine

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
    trans = MeshCoreTransportEngine(context['session_mgr'],
                                    context['config'], context['db'])
    long_msg = "this is a test of a very long message which means i need to keep typing for quite a while to make sure that i'm well over the 140 character limit that we're currently using for meshcore packets."

    first_chunk = "this is a test of a very long message which means i need to keep typing for quite a while to make sure that i'm well over the 140"
    second_chunk = "character limit that we're currently using for meshcore packets."

    chunks = trans._chunk_message(long_msg, 140)
    assert len(chunks) > 1
    assert chunks[0] == first_chunk
    assert chunks[1] == second_chunk
