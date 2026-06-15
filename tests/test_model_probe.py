from abench.model_probe import classify, scrub


def test_classify_ok():
    assert classify(200, '{"choices":[]}', None) == (True, "ok")


def test_classify_auth():
    assert classify(401, "Unauthorized", None)[1] == "auth"
    assert classify(403, "forbidden", None)[1] == "auth"


def test_classify_model_not_found():
    assert classify(404, "no such model", None)[1] == "model_not_found"
    assert classify(400, 'Model "x" does not exist', None)[1] == "model_not_found"


def test_classify_network_and_tls():
    assert classify(None, "", "timed out")[1] == "network"
    assert classify(None, "", "CERTIFICATE_VERIFY_FAILED")[1] == "tls"


def test_scrub_removes_key():
    assert "sk-secret" not in scrub("error for key sk-secret here", "sk-secret")
    assert scrub("no key here", "sk-secret") == "no key here"
