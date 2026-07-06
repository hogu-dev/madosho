from madosho_server import api, query_api


def test_both_planes_build_valid_openapi():
    for app in (api.app, query_api.app):
        schema = app.openapi()
        assert schema["openapi"].startswith("3.")
        assert schema["info"]["title"] in ("madosho", "madosho-query")


def test_query_endpoint_references_a_named_response_schema():
    schema = query_api.app.openapi()
    ok = schema["paths"]["/query"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
    # union response model -> anyOf of the two named component refs
    refs = str(ok)
    assert "QueryAnswerResponse" in refs and "QueryHitsResponse" in refs


def test_control_research_get_references_research_read():
    schema = api.app.openapi()
    path = schema["paths"]["/corpora/{corpus_id}/research/{run_id}"]["get"]
    ref = str(path["responses"]["200"]["content"]["application/json"]["schema"])
    assert "ResearchRunRead" in ref


def test_control_plane_names_slim_list_models():
    comps = api.app.openapi()["components"]["schemas"]
    assert "EvalRunList" in comps
    assert "ResearchRunList" in comps


def test_query_plane_documents_error_response():
    # ErrorResponse is registered on the query plane (not the control plane,
    # which uses FastAPI's default HTTPException envelope).
    comps = query_api.app.openapi()["components"]["schemas"]
    assert "ErrorResponse" in comps
