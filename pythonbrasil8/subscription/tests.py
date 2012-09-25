# -*- coding: utf-8 -*-
from django.conf import settings
from django.contrib import admin as django_admin
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.urlresolvers import reverse, NoReverseMatch
from django.http import HttpResponseRedirect
from django.db import models as django_models
from django.test import TestCase
from django.test.client import RequestFactory

from pythonbrasil8.dashboard import models as dash_models
from pythonbrasil8.subscription import admin, models, views
from pythonbrasil8.subscription.models import Subscription, Transaction, PRICES
from pythonbrasil8.subscription.views import SubscriptionView, NotificationView


class SubscriptionModelTestCase(TestCase):

    def setUp(self):
        self.user = User.objects.create(username="Wolverine")

    def test_name_url(self):
        try:
            reverse('talk-subscription')
        except NoReverseMatch:
            self.fail("Reversal of url named 'talk-subscription' failed with NoReverseMatch")

    def test_should_have_type(self):
        self.assert_field_in('type', Subscription)

    def test_type_should_be_CharField(self):
        type_field = Subscription._meta.get_field_by_name('type')[0]
        self.assertIsInstance(type_field, django_models.CharField)

    def test_type_should_have_choices(self):
        type_field = Subscription._meta.get_field_by_name('type')[0]
        choices = [choice[0] for choice in type_field._choices]
        self.assertIn('talk', choices)
        self.assertIn('tutorial', choices)

    def test_should_have_user(self):
        self.assert_field_in('user', Subscription)

    def test_user_should_be_a_foreign_key(self):
        user_field = Subscription._meta.get_field_by_name('user')[0]
        self.assertIsInstance(user_field, django_models.ForeignKey)
        self.assertEqual(User, user_field.related.parent_model)

    def test_should_have_date(self):
        self.assert_field_in('date', Subscription)

    def test_date_should_be_datetime_field(self):
        date_field = Subscription._meta.get_field_by_name('date')[0]
        self.assertIsInstance(date_field, django_models.DateTimeField)
        self.assertTrue(date_field.auto_now_add)

    def test_subscription_done_should_be_false_if_has_not_a_transaction(self):
        self.assertFalse(Subscription().done())

    def test_subscription_done_should_be_false_if_transactions_isnt_done(self):
        subscription = Subscription.objects.create(
            user=self.user,
            type="talk",
        )
        Transaction.objects.create(
            subscription=subscription,
            status="pending",
            code="xpto",
            price="897.02"
        )
        self.assertFalse(subscription.done())

    def test_subscription_done_should_be_truth_if_transactions_is_done(self):
        subscription = Subscription.objects.create(
            user=self.user,
            type="talk",
        )
        Transaction.objects.create(
            subscription=subscription,
            status="done",
            code="xpto",
            price="543.21"
        )
        self.assertTrue(subscription.done())

    def assert_field_in(self, field_name, model):
        self.assertIn(field_name, model._meta.get_all_field_names())


class TransacitonModelTestCase(TestCase):

    def test_should_have_code(self):
        self.assert_field_in('code', Transaction)

    def test_should_have_status(self):
        self.assert_field_in('status', Transaction)

    def test_should_have_subscription(self):
        self.assert_field_in('subscription', Transaction)

        subscription_field = Transaction._meta.get_field_by_name('subscription')[0]
        self.assertIsInstance(subscription_field, django_models.ForeignKey)
        self.assertEqual(Subscription, subscription_field.related.parent_model)

    def test_get_checkout_url(self):
        t = Transaction(code="123")
        expected_url = settings.PAGSEGURO_WEBCHECKOUT + "123"
        self.assertEqual(expected_url, t.get_checkout_url())

    def assert_field_in(self, field_name, model):
        self.assertIn(field_name, model._meta.get_all_field_names())


class SubscriptionViewTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        call_command("loaddata", "profiles.json", verbosity=0)

    @classmethod
    def tearDownClass(cls):
        call_command("flush", interactive=False, verbosity=0)

    def setUp(self):
        self.user = User.objects.get(pk=1)
        self.request = RequestFactory().get("/", {})
        self.request.user = self.user

        self.requests_original = views.requests

        class ResponseMock(object):
            content = "<code>xpto123</code>"

            def ok(self):
                return True

        def post(self, *args, **kwargs):
            return ResponseMock()

        views.requests.post = post

    def tearDown(self):
        views.requests = self.requests_original
        Subscription.objects.all().delete()

    def test_subscription_view_should_redirect_to_dashboard_if_it_fails_to_create_the_transaction(self):
        class ResponseMock(object):
            content = None

            @property
            def ok(self):
                return False

        requests_original = views.requests
        try:
            views.requests.post = lambda self, *args, **kwargs: ResponseMock()
            request = RequestFactory().get("/", {})
            request.user = User.objects.get(pk=1)
            v = SubscriptionView()
            v._notify_staff = lambda u: None
            response = v.dispatch(request)
            self.assertFalse(Subscription.objects.filter(user__pk=1).exists())
            self.assertEqual(302, response.status_code)
            self.assertEqual("/dashboard/", response["Location"])
        finally:
            views.requests = requests_original

    def test_subscription_view_should_create_a_subscription_for_the_current_user_and_redirect_to_payment_gateway(self):
        response = SubscriptionView.as_view()(self.request)
        self.assertTrue(Subscription.objects.filter(user=self.user).exists())
        self.assertEqual(302, response.status_code)
        expected_url = settings.PAGSEGURO_WEBCHECKOUT + "xpto123"
        self.assertEqual(expected_url, response["Location"])

    def test_subscription_view_should_create_a_subscription_for_the_user_type(self):
        SubscriptionView.as_view()(self.request)
        transaction = Transaction.objects.get(subscription__user=self.user)
        self.assertEqual(transaction.price, PRICES["Student"])

    def test_should_returns_error_when_user_is_not_logged(self):
        self.request.user.is_authenticated = lambda: False
        response = SubscriptionView.as_view()(self.request)
        self.assertEqual(302, response.status_code)
        self.assertIn('/accounts/login/', response.items()[1][1])

    def test_generate_transaction(self):
        subscription = Subscription.objects.create(
            type='talk',
            user=self.user,
        )
        transaction = SubscriptionView().generate_transaction(subscription)
        self.assertEqual(subscription, transaction.subscription)
        self.assertEqual("xpto123", transaction.code)

    def test_should_redirect_to_the_profile_url_if_the_user_does_not_have_a_profile(self):
        request = RequestFactory().get("/dashboard/subscription/talk/")
        request.user = User.objects.get(pk=2)
        response = SubscriptionView.as_view()(request)
        self.assertIsInstance(response, HttpResponseRedirect)
        base_url = reverse("edit-profile")
        expected_url = "%s?next=%s" % (base_url, request.path)
        self.assertEqual(expected_url, response["Location"])

    def test_should_redirect_to_the_profile_url_if_the_profile_does_not_contain_a_name(self):
        request = RequestFactory().get("/")
        request.user = User.objects.get(pk=3)
        response = SubscriptionView.as_view()(request)
        self.assertIsInstance(response, HttpResponseRedirect)
        base_url = reverse("edit-profile")
        expected_url = "%s?next=%s" % (base_url, request.path)
        self.assertEqual(expected_url, response["Location"])


class NotificationViewTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        call_command("loaddata", "profiles.json", verbosity=0)

    @classmethod
    def tearDownClass(cls):
        call_command("flush", interactive=False, verbosity=0)

    def setUp(self):
        self.user = User.objects.get(pk=1)
        self.requests_original = views.requests

        class ResponseMock(object):
            content = "<xml><status>3</status><reference>3</reference></xml>"

            def ok(self):
                return True

        def get(self, *args, **kwargs):
            return ResponseMock()

        views.requests.get = get

    def tearDown(self):
        views.requests = self.requests_original

    def test_name_url(self):
        try:
            reverse('notification')
        except NoReverseMatch:
            self.fail("Reversal of url named 'notification' failed with NoReverseMatch")

    def test_transaction_should_get_info_about_transaction(self):
        status, ref = NotificationView().transaction("code")
        self.assertEqual(3, status)
        self.assertEqual(3, ref)

    def test_transaction_done(self):
        subscription = Subscription.objects.create(
            user=self.user,
            type="talk",
        )
        transaction = Transaction.objects.create(
            subscription=subscription,
            status="pending",
            code="xpto",
            price="123.54"
        )
        NotificationView().transaction_done(subscription.id)
        transaction = Transaction.objects.get(id=transaction.id)
        self.assertEqual("done", transaction.status)

    def test_transaction_canceled(self):
        subscription = Subscription.objects.create(
            user=self.user,
            type="talk",
        )
        transaction = Transaction.objects.create(
            subscription=subscription,
            status="pending",
            code="xpto",
            price="115.84"
        )
        NotificationView().transaction_canceled(subscription.id)
        transaction = Transaction.objects.get(id=transaction.id)
        self.assertEqual("canceled", transaction.status)

    def test_methods_by_status(self):
        methods_by_status = NotificationView().methods_by_status
        self.assertEqual("transaction_done", methods_by_status[3].__name__)
        self.assertEqual("transaction_canceled", methods_by_status[7].__name__)

    def test_post(self):
        subscription = Subscription.objects.create(
            user=self.user,
            type="talk",
        )
        transaction = Transaction.objects.create(
            subscription=subscription,
            status="pending",
            code="xpto",
            price=123.45
        )
        notification_view = NotificationView()
        notification_view.transaction = (lambda code: (3, 1))
        request = RequestFactory().post("/", {"notificationCode": "123"})

        response = notification_view.post(request)

        transaction = Transaction.objects.get(id=transaction.id)
        self.assertEqual("done", transaction.status)
        self.assertEqual("OK", response.content)


class PricesTestCase(TestCase):

    def test_prices(self):
        expected = {
            'Student': 150,
            'APyB Associated': 150,
            'Speaker': 150,
            'Individual': 250,
            'Corporate': 350
        }
        self.assertEqual(expected, PRICES)


class SubscriptionAdminTestCase(TestCase):

    @classmethod
    def setUpClass(cls):
        call_command("loaddata", "profiles.json", verbosity=0)
        cls.factory = RequestFactory()

    @classmethod
    def tearDownClass(cls):
        call_command("flush", interactive=False, verbosity=0)

    def test_name(self):
        profile = dash_models.AccountProfile.objects.get(user=1)
        sub = models.Subscription(user=User.objects.get(pk=1))
        self.assertEqual(profile.name, admin.name(sub))

    def test_name_short_description(self):
        self.assertEqual(u"Name", admin.name.short_description)

    def test_name_function_is_in_list_display(self):
        self.assertIn(admin.name, admin.SubscriptionAdmin.list_display)

    def test_status(self):
        subscription = models.Subscription.objects.create(user=User.objects.get(pk=1), type="talk")
        try:
            self.assertEqual(u"pending", admin.status(subscription))
            Transaction.objects.create(code="1234", price=100, status="canceled", subscription=subscription)
            self.assertEqual(u"canceled", admin.status(subscription))
            Transaction.objects.create(code="4321", price=100, status="pending", subscription=subscription)
            self.assertEqual(u"pending", admin.status(subscription))
            Transaction.objects.create(code="123", price=100, status="done", subscription=subscription)
            self.assertEqual(u"confirmed", admin.status(subscription))
        finally:
            subscription.delete()

    def test_status_short_description(self):
        self.assertEqual(u"Status", admin.status.short_description)

    def test_status_is_in_list_display(self):
        self.assertIn(admin.status, admin.SubscriptionAdmin.list_display)

    def test_subscription_model_is_registered_with_subscription_admin(self):
        self.assertIn(models.Subscription, django_admin.site._registry)
        self.assertIsInstance(django_admin.site._registry[models.Subscription], admin.SubscriptionAdmin)
