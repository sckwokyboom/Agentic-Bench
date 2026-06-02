from abench_ui.ws_buffer import SessionEventBuffer


def test_buffer_round_robins_after_capacity():
    buf = SessionEventBuffer(capacity=3)
    for i in range(5):
        buf.append({"i": i})
    # only the last 3 should remain
    assert [e["i"] for e in buf.replay_from(0)] == [2, 3, 4]


def test_replay_from_specific_event_id():
    buf = SessionEventBuffer(capacity=10)
    ids = [buf.append({"i": i}) for i in range(5)]
    # EXCLUSIVE replay: client sends the last id it HAS (event for i=2);
    # replay returns strictly-newer events i=3, i=4 — no duplicate of i=2.
    out = list(buf.replay_from(ids[2]))
    assert [e["i"] for e in out] == [3, 4]


def test_replay_from_overflow_returns_all_remaining():
    """If last_event_id is older than the oldest buffered → return everything."""
    buf = SessionEventBuffer(capacity=3)
    for i in range(10):
        buf.append({"i": i})
    out = list(buf.replay_from(0))
    assert len(out) == 3  # only the last 3 are buffered
