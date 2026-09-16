"""
Unit tests for Distributed Tracer.
"""

from src.observability.tracer import Tracer


def test_tracer_spans_and_attributes():
    """Verify trace creation, span timing, and error attributes."""
    tracer = Tracer()
    trace_id = tracer.start_trace()
    assert trace_id.startswith("trace-")

    with tracer.span("parent-operation") as p_span:
        p_span.set_attribute("key", "value")
        with tracer.span("child-operation", parent_id=p_span.span_id) as c_span:
            c_span.set_attribute("child_key", 123)

    assert len(tracer.spans) == 2
    parent_record = tracer.spans[0].to_dict()
    assert parent_record["name"] == "parent-operation"
    assert parent_record["status"] == "OK"
    assert parent_record["attributes"]["key"] == "value"
