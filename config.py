import os


class Config(object):
    STRING_SESSION = os.environ.get("STRING_SESSION", "")

    API_ID = int(os.environ.get("API_ID", 12345))

    API_HASH = os.environ.get("API_HASH", "")
