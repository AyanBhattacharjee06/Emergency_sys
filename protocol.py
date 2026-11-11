import json

PORT = 9000
EMERGENCY_PORT = 9001
MAX_PACKET = 8192


def encode(message):
    raw = json.dumps(message, separators=(',', ':')).encode()
    if len(raw) > MAX_PACKET:
        raise ValueError('Message exceeds datagram limit')
    return raw


def decode(raw):
    if len(raw) > MAX_PACKET:
        raise ValueError('Datagram too large')
    message = json.loads(raw)
    if not isinstance(message, dict) or not isinstance(message.get('type'), str):
        raise ValueError('Expected an object with a type')
    return message
