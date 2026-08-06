class UserNotFoundError(Exception):
    def __init__(self, external_id: str) -> None:
        self.external_id = external_id
        super().__init__(f"User not found: {external_id}")


class InvalidGoogleClaimsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class EmailDomainNotAllowedError(Exception):
    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"Email domain not allowed: {email}")


class BrandAccessDeniedError(Exception):
    def __init__(self, brand_external_id: str) -> None:
        self.brand_external_id = brand_external_id
        super().__init__(f"No access to brand: {brand_external_id}")


class ApplicationNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Application not found: {name}")


class RoleNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Role not found: {name}")


class UserServiceBrandNotFoundError(Exception):
    def __init__(self, brand_external_id: str) -> None:
        self.brand_external_id = brand_external_id
        super().__init__(f"User-service brand not found for: {brand_external_id}")
