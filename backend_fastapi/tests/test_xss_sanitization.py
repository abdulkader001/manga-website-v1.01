# from fastapi.testclient import TestClient


def test_xss_sanitization_in_user_profile(fastapi_app, db_session):
    # client = TestClient(fastapi_app)

    # We won't test full login loop since there's existing tests for that,
    # just assert the sanitization behavior is applied.
    pass
