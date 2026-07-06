from madosho_server import api


def test_control_plane_small_response_models_present():
    comps = api.app.openapi()["components"]["schemas"]
    for name in ("StatusResponse", "RebuildResponse", "RunningResponse",
                 "SelectedPipelineResponse", "VerdictResponse"):
        assert name in comps


def test_control_plane_pipeline_models_present():
    comps = api.app.openapi()["components"]["schemas"]
    for name in ("ComponentCard", "DocumentPipelineCard",
                 "RecommendedPipeline", "CreatePipelineResponse"):
        assert name in comps


def test_control_plane_cube_and_comparison_models_present():
    comps = api.app.openapi()["components"]["schemas"]
    for name in ("CubeResponse", "DocGroup", "PipelineRow", "CubeCell",
                 "ComparisonResponse", "ComparisonPage", "PipelineExtractResponse"):
        assert name in comps


def test_control_plane_run_models_present():
    comps = api.app.openapi()["components"]["schemas"]
    for name in ("EvalRunRead", "ResearchRunRead", "ProposalRead"):
        assert name in comps
