"""credential_sibling_profile_ids (Phase 4a-1c, spec § Slot reclaim, step 1).

The fixture shape is PoolEnforcementTests' (test_connection_pool.py): XC
accounts in one ServerGroup whose profiles carry max_streams.
"""

from django.test import TestCase

from apps.m3u.connection_pool import credential_sibling_profile_ids
from apps.m3u.models import M3UAccount, M3UAccountProfile, ServerGroup


def _account(name, group, *, username="user", password="pass", profile_max=1):
    account = M3UAccount.objects.create(
        name=name,
        account_type="XC",
        username=username,
        password=password,
        server_url="http://xc.example.com",
        server_group=group,
        max_streams=5,
    )
    profile = M3UAccountProfile.objects.get(m3u_account=account, is_default=True)
    profile.max_streams = profile_max
    profile.save()
    return profile


class CredentialSiblingTests(TestCase):
    def setUp(self):
        self.group = ServerGroup.objects.create(name="sibling-pool")

    def test_siblings_share_the_credential_counter_across_accounts(self):
        one = _account("Sibling One", self.group)
        two = _account("Sibling Two", self.group)
        self.assertEqual(
            credential_sibling_profile_ids(one), sorted([one.id, two.id])
        )
        self.assertEqual(
            credential_sibling_profile_ids(two), sorted([one.id, two.id])
        )

    def test_a_different_login_in_the_same_group_is_not_a_sibling(self):
        one = _account("Login One", self.group)
        other = _account("Login Two", self.group, username="other", password="word")
        self.assertEqual(credential_sibling_profile_ids(one), [one.id])
        self.assertEqual(credential_sibling_profile_ids(other), [other.id])

    def test_an_unlimited_profile_has_no_siblings(self):
        unlimited = _account("Unlimited", self.group, profile_max=0)
        limited = _account("Limited", self.group)
        self.assertEqual(credential_sibling_profile_ids(unlimited), [])
        # An unlimited profile skips credential enforcement, so it does not
        # count against the counter and is not named as one of its siblings.
        self.assertEqual(credential_sibling_profile_ids(limited), [limited.id])

    def test_an_inactive_profile_sharing_the_counter_is_a_sibling(self):
        one = _account("Active One", self.group)
        two = _account("Inactive Two", self.group)
        M3UAccountProfile.objects.filter(pk=two.pk).update(is_active=False)
        two.refresh_from_db()
        self.assertFalse(two.is_active)
        # Deactivation releases nothing: a channel still playing on it holds
        # the credential slot, so it is named (R65).
        self.assertEqual(
            credential_sibling_profile_ids(one), sorted([one.id, two.id])
        )

    def test_a_profile_outside_any_server_group_has_no_siblings(self):
        ungrouped = _account("Ungrouped", None)
        self.assertEqual(credential_sibling_profile_ids(ungrouped), [])
