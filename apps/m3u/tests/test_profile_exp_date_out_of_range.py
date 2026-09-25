"""Guards #199: an out-of-range exp_date (beyond datetime.fromtimestamp's
platform time_t range) or a non-dict user_info must not crash
M3UAccountProfile.save() or the admin-page accessor methods.
"""
from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount, M3UAccountProfile


class ParseExpDateOverflowTests(SimpleTestCase):
    """_parse_exp_date is a @staticmethod; call it directly for float('inf').

    A literal Python float('inf') cannot round-trip through
    M3UAccountProfile.save() on PostgreSQL: Django's JSON encoder renders it
    as the bareword ``Infinity``, which is not valid JSON syntax, and the
    write is refused at the database layer (psycopg.errors.
    InvalidTextRepresentation) before any Python-level parsing code runs.
    That is a pre-existing, unrelated storage limitation, not part of #199
    (which is about _parse_exp_date raising OverflowError, not ValueError,
    for a value datetime.fromtimestamp cannot represent) -- so this one case
    is exercised at the unit level instead of through a save() round trip.
    """

    def test_float_infinity_does_not_raise(self):
        self.assertIsNone(M3UAccountProfile._parse_exp_date(float("inf")))


class ProfileExpDateOutOfRangeTests(TestCase):
    def _make_xc_profile(self, name="Exp Range Account"):
        account = M3UAccount.objects.create(
            name=name,
            server_url="http://example.com/playlist.m3u",
            account_type=M3UAccount.Types.XC,
        )
        return M3UAccountProfile.objects.get(m3u_account=account, is_default=True)

    def test_out_of_range_exp_date_does_not_raise_on_refresh_save(self):
        """Three of the fuzz campaign's shrunk counterexamples -- values
        that a JSONField can actually store (see ParseExpDateOverflowTests
        for float('inf'), which cannot). A prior valid exp_date must survive
        an out-of-range save unchanged, exactly as an unparseable string
        already does."""
        cases = {
            "twenty_four_digit_string": "999999999999999999999999",
            "1e30": "1e30",
            "-1e20": "-1e20",
        }
        for label, bad_value in cases.items():
            with self.subTest(label=label):
                profile = self._make_xc_profile(name=f"Exp Range {label}")
                profile.custom_properties = {
                    "user_info": {"exp_date": "1700000000"},
                }
                profile.save(update_fields=["custom_properties", "exp_date"])
                profile.refresh_from_db()
                previous = profile.exp_date
                self.assertIsNotNone(previous)

                profile.custom_properties = {"user_info": {"exp_date": bad_value}}
                # Must not raise.
                profile.save(update_fields=["custom_properties", "exp_date"])

                profile.refresh_from_db()
                self.assertEqual(profile.exp_date, previous)

    def test_name_only_save_of_a_row_holding_a_bad_exp_date_succeeds(self):
        """A stored bad value must not poison even a name-only save (#199's
        save() re-parses custom_properties on every XC-profile save)."""
        profile = self._make_xc_profile()
        M3UAccountProfile.objects.filter(pk=profile.pk).update(
            custom_properties={"user_info": {"exp_date": "1e30"}},
        )
        profile.refresh_from_db()

        profile.name = "Renamed Profile"
        profile.save(update_fields=["name"])  # must not raise

        profile.refresh_from_db()
        self.assertEqual(profile.name, "Renamed Profile")

    def test_get_account_expiration_returns_none_for_out_of_range_exp_date(self):
        profile = self._make_xc_profile()
        M3UAccountProfile.objects.filter(pk=profile.pk).update(
            exp_date=None,
            custom_properties={"user_info": {"exp_date": "1e30"}},
        )
        profile.refresh_from_db()

        self.assertIsNone(profile.get_account_expiration())

    def test_non_dict_user_info_does_not_raise(self):
        """A provider's XC response can leave user_info as None, a list or a
        string; save() and the three sibling accessors must treat that as
        absent rather than raising AttributeError from a bare .get()."""
        profile = self._make_xc_profile()
        cases = {"none": None, "list": [1, 2, 3], "string": "not a dict"}
        for label, bad_user_info in cases.items():
            with self.subTest(label=label):
                profile.custom_properties = {"user_info": bad_user_info}
                # Must not raise.
                profile.save(update_fields=["custom_properties", "exp_date"])

                self.assertIsNone(profile.get_account_status())
                self.assertIsNone(profile.get_max_connections())
                self.assertIsNone(profile.get_active_connections())
