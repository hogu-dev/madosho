from madosho_server import init_db


def test_init_db_exposes_callable():
    # the heavy path (procrastinate schema) needs Postgres and is exercised by
    # the slow test; here we only assert the entry function exists and is callable
    assert callable(init_db.init_database)
