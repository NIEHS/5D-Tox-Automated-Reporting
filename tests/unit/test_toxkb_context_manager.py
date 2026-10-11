"""
Regression test for ToxKBQuerier as a context manager.

interpret() (and build_genomics_interpretation) used to open a ToxKBQuerier and
rely on either a bare `kb.close()` at the end or a try/finally to release the
read-only duckdb connection.  The CLI interpret() path had no try/finally around
the long narrative phase, so any exception between connect and close leaked the
duckdb file handle.

ToxKBQuerier now implements the context-manager protocol so callers can write
`with ToxKBQuerier(db_path) as kb: ...` and have the connection released even
when the body raises.  Pre-fix (no __enter__/__exit__), entering the `with`
block raises AttributeError, so the two assertions below cannot be reached.
"""

import duckdb
import pytest

import narrative.interpret as interpret


@pytest.fixture
def kb_path(tmp_path):
    """A minimal on-disk duckdb the read-only ToxKBQuerier can open."""
    p = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(p))
    # ToxKBQuerier connects read_only, which requires the file to already exist
    # with at least a schema; a single trivial table is enough.
    con.execute("CREATE TABLE genes (gene_symbol VARCHAR)")
    con.execute("INSERT INTO genes VALUES ('TP53')")
    con.close()
    return str(p)


def _is_connection_closed(kb: "interpret.ToxKBQuerier") -> bool:
    try:
        kb.con.execute("SELECT 1")
        return False
    except Exception:
        # duckdb raises ConnectionException once the connection is closed.
        return True


def test_context_manager_yields_self_and_closes_on_normal_exit(kb_path):
    with interpret.ToxKBQuerier(kb_path) as kb:
        assert isinstance(kb, interpret.ToxKBQuerier)
        assert kb.background_genes() == {"TP53"}
    assert _is_connection_closed(kb), "connection should be closed after the with-block"


def test_context_manager_closes_when_body_raises(kb_path):
    kb_ref = {}

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom):
        with interpret.ToxKBQuerier(kb_path) as kb:
            kb_ref["kb"] = kb
            raise _Boom("simulated failure mid-pipeline")

    # The exception must propagate (not be swallowed) AND the connection must
    # still have been released — this is the leak the fix closes.
    assert _is_connection_closed(kb_ref["kb"]), (
        "connection should be closed even when the with-body raises"
    )
