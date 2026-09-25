"""GET /api/vod/categories/?m3u_account=<id> filters by account (#96)."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.m3u.models import M3UAccount
from apps.vod.models import M3UVODCategoryRelation, VODCategory

User = get_user_model()


class VodCategoryAccountFilterTests(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username="vodcatadmin", password="x")
        admin.user_level = 10
        admin.save()
        self.client = APIClient()
        self.client.force_authenticate(user=admin)
        self.a = M3UAccount.objects.create(name="A", server_url="http://a.example", account_type=M3UAccount.Types.XC, is_active=True)
        self.b = M3UAccount.objects.create(name="B", server_url="http://b.example", account_type=M3UAccount.Types.XC, is_active=True)
        self.cat_a = VODCategory.objects.create(name="only-a", category_type="movie")
        self.cat_b = VODCategory.objects.create(name="only-b", category_type="movie")
        M3UVODCategoryRelation.objects.create(m3u_account=self.a, category=self.cat_a)
        M3UVODCategoryRelation.objects.create(m3u_account=self.b, category=self.cat_b)

    def test_the_m3u_account_filter_named_a_relation_vodcategory_does_not_have(self):
        res = self.client.get("/api/vod/categories/", {"m3u_account": self.a.id})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        names = [c["name"] for c in (body["results"] if isinstance(body, dict) else body)]
        self.assertEqual(names, ["only-a"])
