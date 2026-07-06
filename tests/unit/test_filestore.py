import hashlib
import io

from madosho_server.filestore import FileStore


def test_put_stream_hashes_and_resolves(tmp_path):
    store = FileStore(tmp_path / "fs")
    data = b"hello madosho"
    uri, digest = store.put_stream("greeting.txt", io.BytesIO(data))

    assert digest == hashlib.sha256(data).hexdigest()
    assert uri == f"{digest}/greeting.txt"
    resolved = store.path_for(uri)
    assert resolved.read_bytes() == data


def test_put_stream_strips_path_components_from_filename(tmp_path):
    store = FileStore(tmp_path / "fs")
    uri, digest = store.put_stream("../../evil.txt", io.BytesIO(b"x"))
    assert uri == f"{digest}/evil.txt"             # basename only — no traversal
    resolved = store.path_for(uri)
    assert resolved.read_bytes() == b"x"
    assert (tmp_path / "fs") in resolved.parents   # stayed inside the store base
