from gcp_local.core.errors import GcpError, rest_error_body


def test_rest_envelope_shape():
    err = GcpError(code=404, reason="notFound", message="Bucket b does not exist")
    body = rest_error_body(err)
    assert body == {
        "error": {
            "code": 404,
            "message": "Bucket b does not exist",
            "errors": [
                {
                    "domain": "global",
                    "reason": "notFound",
                    "message": "Bucket b does not exist",
                }
            ],
            "status": "NOT_FOUND",
        }
    }


def test_rest_envelope_unknown_status_uses_unknown():
    err = GcpError(code=418, reason="iamATeapot", message="hi")
    body = rest_error_body(err)
    assert body["error"]["status"] == "UNKNOWN"
