class BadRequestException(Exception):
    def __init__(self, message: str, short_message: str) -> None:
        self.message = message
        self.short_message = short_message