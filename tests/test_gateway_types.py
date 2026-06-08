from clonway_cockpit.gateway.types import Completion, GatewayError, Message, Usage


def test_completion_carries_text_and_usage():
    comp = Completion(text="hi", usage=Usage(prompt_tokens=3, completion_tokens=5))
    assert comp.text == "hi"
    assert comp.usage.prompt_tokens == 3
    assert comp.usage.completion_tokens == 5


def test_gateway_error_is_runtime_error():
    assert issubclass(GatewayError, RuntimeError)


def test_message_is_a_plain_mapping():
    msg: Message = {"role": "user", "content": "ping"}
    assert msg["role"] == "user"
