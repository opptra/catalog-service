from core.clients.dropbox import DropboxClient, _as_direct_url


def test_scl_share_keeps_rlkey_and_uses_content_host() -> None:
    url = "https://www.dropbox.com/scl/fi/abc123xyz/image.jpg?rlkey=def456&st=expiredtoken&dl=0"
    assert _as_direct_url(url) == (
        "https://dl.dropboxusercontent.com/scl/fi/abc123xyz/image.jpg?rlkey=def456"
    )


def test_scl_dl_query_is_rewritten_when_not_first_param() -> None:
    url = "https://www.dropbox.com/scl/fi/abc123xyz/image.jpg?rlkey=def456&dl=0"
    assert "&dl=0" not in _as_direct_url(url)
    assert "rlkey=def456" in _as_direct_url(url)


def test_scl_without_rlkey_is_not_moved_to_content_host() -> None:
    url = "https://www.dropbox.com/scl/fi/abc123xyz/image.jpg?dl=0"
    result = _as_direct_url(url)
    assert result.startswith("https://www.dropbox.com/scl/fi/abc123xyz/image.jpg")
    assert "raw=1" in result
    assert "dl.dropboxusercontent.com" not in result


def test_legacy_s_link_uses_content_host() -> None:
    url = "https://www.dropbox.com/s/abc123/image.jpg?dl=0"
    assert _as_direct_url(url) == "https://dl.dropboxusercontent.com/s/abc123/image.jpg"


def test_already_direct_url_is_cleaned() -> None:
    url = "https://dl.dropboxusercontent.com/scl/fi/abc123xyz/image.jpg?rlkey=def456&st=gone&dl=1"
    assert _as_direct_url(url) == (
        "https://dl.dropboxusercontent.com/scl/fi/abc123xyz/image.jpg?rlkey=def456"
    )


def test_folder_share_is_left_unchanged() -> None:
    url = "https://www.dropbox.com/scl/fo/folderid/name?rlkey=abc&dl=0"
    assert _as_direct_url(url) == url


def test_non_dropbox_url_is_left_unchanged() -> None:
    url = "https://example.com/image.jpg"
    assert _as_direct_url(url) == url


def test_empty_url_is_left_unchanged() -> None:
    assert _as_direct_url("") == ""


def test_client_uses_same_rewrite() -> None:
    url = "https://www.dropbox.com/scl/fi/abc123xyz/image.jpg?rlkey=def456&dl=0"
    assert DropboxClient._as_direct_url(url) == _as_direct_url(url)
