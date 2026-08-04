from core.auth.policy import AuthPolicy, get_auth_policy, has_internal_suffix, internal_api, no_auth


def _plain_handler():
    return None


def test_unannotated_handler_defaults_to_google_user():
    assert get_auth_policy(_plain_handler) is AuthPolicy.GOOGLE_USER
    assert not has_internal_suffix(_plain_handler)


def test_internal_api_sets_internal_client_policy_and_suffix():
    @internal_api
    def handler():
        return None

    assert get_auth_policy(handler) is AuthPolicy.INTERNAL_CLIENT
    assert has_internal_suffix(handler)


def test_no_auth_sets_public_policy_without_suffix():
    @no_auth
    def handler():
        return None

    assert get_auth_policy(handler) is AuthPolicy.PUBLIC
    assert not has_internal_suffix(handler)
