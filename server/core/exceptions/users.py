class UserNotFoundError(Exception):
    def __init__(self, external_id: str) -> None:
        self.external_id = external_id
        super().__init__(f"User not found: {external_id}")


class InvalidGoogleClaimsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
