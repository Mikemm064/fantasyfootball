import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import yahoo_auth


CREDS = yahoo_auth.YahooCredentials("client-id", "client-secret", "https://example.test/")


class YahooAuthTest(unittest.TestCase):
    def test_authorization_url_has_required_values(self):
        url = urlparse(yahoo_auth.authorization_url(CREDS, "csrf-state"))
        self.assertEqual(f"{url.scheme}://{url.netloc}{url.path}", yahoo_auth.AUTHORIZATION_ENDPOINT)
        self.assertEqual(parse_qs(url.query), {
            "client_id": ["client-id"],
            "redirect_uri": ["https://example.test/"],
            "response_type": ["code"],
            "state": ["csrf-state"],
        })

    def test_state_comparison_rejects_missing_and_wrong_values(self):
        self.assertTrue(yahoo_auth.states_match("expected", "expected"))
        self.assertFalse(yahoo_auth.states_match("expected", "wrong"))
        self.assertFalse(yahoo_auth.states_match(None, None))

    @patch("yahoo_auth.requests.post")
    def test_code_exchange_uses_server_side_post(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "access_token": "private-access",
            "refresh_token": "private-refresh",
            "expires_in": 3600,
        }
        post.return_value = response
        token = yahoo_auth.exchange_code(CREDS, "one-time-code")
        self.assertEqual(token["refresh_token"], "private-refresh")
        self.assertEqual(post.call_args.kwargs["data"]["grant_type"], "authorization_code")
        self.assertEqual(post.call_args.kwargs["data"]["code"], "one-time-code")

    @patch("yahoo_auth.requests.post")
    def test_refresh_replaces_rotated_refresh_token(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }
        post.return_value = response
        session = {"yahoo_token": {
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_at": 1,
        }}
        yahoo_auth.ensure_fresh_token(CREDS, session, now=1000)
        self.assertEqual(session["yahoo_token"]["refresh_token"], "new-refresh")
        self.assertEqual(post.call_args.kwargs["data"]["refresh_token"], "old-refresh")

    @patch("yahoo_auth.requests.get")
    def test_fantasy_check_is_read_only_get(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        get.return_value = response
        session = {"yahoo_token": {
            "access_token": "private-access",
            "refresh_token": "private-refresh",
            "expires_at": 9999,
        }}
        self.assertTrue(yahoo_auth.verify_fantasy_access(CREDS, session))
        self.assertEqual(get.call_args.args[0], yahoo_auth.FANTASY_TEST_ENDPOINT)


if __name__ == "__main__":
    unittest.main()
