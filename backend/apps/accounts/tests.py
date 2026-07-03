import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.db import connection
from django.urls import reverse
from rest_framework.response import Response
from rest_framework.test import APIClient
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.departments.models import Department
from apps.staff.models import Staff

from .decorators import role_required
from .permissions import (
    HasMinimumRole,
    IsAdmin,
    IsCashier,
    IsDepartmentManager,
    IsOwner,
    IsStoreManager,
    get_user_role,
)
from .rate_limiting import (
    IP_RATE_LIMIT,
    LOCKOUT_SECONDS,
    USER_RATE_LIMIT,
    _ip_attempts_key,
    _user_attempts_key,
    _user_locked_key,
    clear_failed_attempts,
    get_lockout_remaining,
    is_ip_rate_limited,
    is_user_locked,
    record_failed_attempt,
)
from .services import blacklist_token, generate_tokens

User = get_user_model()

PASSWORD = "testpass123"


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def dept(db):
    return Department.objects.create(name="Accounts Test Dept", slug="accounts-test-dept", display_order=1)


@pytest.fixture
def user_with_staff(dept):
    user = User.objects.create_user(email="cashier@accounts-test.com", password=PASSWORD)
    staff = Staff.objects.create(
        user=user, first_name="Casey", last_name="Cashier", email="cashier@accounts-test.com",
        role="cashier", department=dept,
    )
    return user, staff


@pytest.fixture
def user_without_staff(db):
    return User.objects.create_user(email="nostaff@accounts-test.com", password=PASSWORD)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def activity_log_table(db):
    """
    activity_log is written via raw SQL in apps.core.activity.log_activity()
    and has no Django model/migration of its own — see apps/finance/tests.py
    for the same fixture.
    """
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id BIGSERIAL PRIMARY KEY,
                    actor_staff_id INTEGER,
                    actor_role VARCHAR(30),
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(100) NOT NULL,
                    entity_id VARCHAR(50) NOT NULL,
                    before_state JSONB,
                    after_state JSONB,
                    device_identifier VARCHAR(255),
                    ip_address INET,
                    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)
        else:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_staff_id INTEGER,
                    actor_role VARCHAR(30),
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(100) NOT NULL,
                    entity_id VARCHAR(50) NOT NULL,
                    before_state TEXT,
                    after_state TEXT,
                    device_identifier VARCHAR(255),
                    ip_address VARCHAR(45),
                    occurred_at DATETIME NOT NULL
                )
            """)
    yield
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS activity_log")


def _login(api_client, user, password=PASSWORD):
    return api_client.post(reverse("auth-login"), {"email": user.email, "password": password}, format="json")


# ── LoginView ──────────────────────────────────────────────────────────────────

class TestLoginView:
    def test_valid_credentials_return_tokens_and_role(self, api_client, user_with_staff):
        user, staff = user_with_staff
        response = _login(api_client, user)
        assert response.status_code == 200
        data = response.data["data"]
        assert data["access"]
        assert data["refresh"]
        assert data["email"] == user.email
        assert data["role"] == staff.role

    def test_role_is_none_without_staff_profile(self, api_client, user_without_staff):
        response = _login(api_client, user_without_staff)
        assert response.status_code == 200
        assert response.data["data"]["role"] is None

    def test_invalid_credentials_return_400(self, api_client, user_with_staff):
        user, _ = user_with_staff
        response = api_client.post(reverse("auth-login"), {"email": user.email, "password": "wrong"}, format="json")
        assert response.status_code == 400
        assert response.data["success"] is False

    def test_invalid_credentials_record_failed_attempt(self, api_client, user_with_staff):
        user, _ = user_with_staff
        api_client.post(reverse("auth-login"), {"email": user.email, "password": "wrong"}, format="json")
        assert cache.get(_user_attempts_key(user.email)) == 1

    def test_account_locked_after_five_failed_attempts(self, api_client, user_with_staff):
        user, _ = user_with_staff
        for _ in range(USER_RATE_LIMIT):
            api_client.post(reverse("auth-login"), {"email": user.email, "password": "wrong"}, format="json")

        # 6th attempt — even with the CORRECT password — must be locked out.
        response = _login(api_client, user)
        assert response.status_code == 429
        assert response.data["error"]["code"] == "AccountLocked"

        remaining = get_lockout_remaining(user.email)
        assert LOCKOUT_SECONDS - 10 <= remaining <= LOCKOUT_SECONDS

    def test_ip_rate_limited_across_different_emails(self, api_client, db):
        for i in range(IP_RATE_LIMIT):
            api_client.post(
                reverse("auth-login"), {"email": f"user{i}@ip-rate-test.com", "password": "wrong"}, format="json",
            )

        response = api_client.post(
            reverse("auth-login"), {"email": "yet-another@ip-rate-test.com", "password": "wrong"}, format="json",
        )
        assert response.status_code == 429
        assert response.data["error"]["code"] == "RateLimitExceeded"

    def test_ip_rate_limit_applies_regardless_of_credentials(self, api_client, user_with_staff):
        user, _ = user_with_staff
        for i in range(IP_RATE_LIMIT):
            api_client.post(
                reverse("auth-login"), {"email": f"user{i}@ip-rate-test2.com", "password": "wrong"}, format="json",
            )
        # Even correct credentials for an otherwise-fine account get blocked
        # once the IP itself is rate limited.
        response = _login(api_client, user)
        assert response.status_code == 429
        assert response.data["error"]["code"] == "RateLimitExceeded"

    def test_successful_login_clears_prior_failed_attempts(self, api_client, user_with_staff):
        user, _ = user_with_staff
        for _ in range(USER_RATE_LIMIT - 2):
            api_client.post(reverse("auth-login"), {"email": user.email, "password": "wrong"}, format="json")
        assert cache.get(_user_attempts_key(user.email)) == USER_RATE_LIMIT - 2

        response = _login(api_client, user)
        assert response.status_code == 200
        assert cache.get(_user_attempts_key(user.email)) is None
        assert cache.get(_user_locked_key(user.email)) is None

    def test_successful_login_writes_activity_log(self, api_client, user_with_staff, activity_log_table):
        user, _ = user_with_staff
        response = _login(api_client, user)
        assert response.status_code == 200

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT action, entity_type, entity_id FROM activity_log WHERE action = %s", ["auth.login"],
            )
            rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "auth_users"
        assert rows[0][2] == str(user.id)


# ── LogoutView ─────────────────────────────────────────────────────────────────

class TestLogoutView:
    def test_valid_refresh_token_blacklisted(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = api_client.post(reverse("auth-logout"), {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 200

        refresh_response = api_client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json")
        assert refresh_response.status_code == 401

    def test_invalid_token_returns_400(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = api_client.post(reverse("auth-logout"), {"refresh": "not-a-real-token"}, format="json")
        assert response.status_code == 400
        assert response.data["error"]["code"] == "InvalidToken"

    def test_already_blacklisted_token_returns_400(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        api_client.post(reverse("auth-logout"), {"refresh": tokens["refresh"]}, format="json")
        response = api_client.post(reverse("auth-logout"), {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 400
        assert response.data["error"]["code"] == "InvalidToken"

    def test_unauthenticated_denied(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        response = api_client.post(reverse("auth-logout"), {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 401

    def test_logout_writes_activity_log(self, api_client, user_with_staff, activity_log_table):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        api_client.post(reverse("auth-logout"), {"refresh": tokens["refresh"]}, format="json")

        with connection.cursor() as cursor:
            cursor.execute("SELECT action FROM activity_log WHERE action = %s", ["auth.logout"])
            rows = cursor.fetchall()
        assert len(rows) == 1


# ── SilentRefreshView ──────────────────────────────────────────────────────────

class TestSilentRefreshView:
    def test_valid_refresh_returns_new_access_token(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]

        response = api_client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json")
        assert response.status_code == 200
        assert response.data["data"]["access"]
        assert response.data["data"]["refresh"]

    def test_rotated_refresh_token_differs_from_original(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        response = api_client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json")
        assert response.data["data"]["refresh"] != tokens["refresh"]

    def test_old_refresh_token_fails_after_being_refreshed(self, api_client, user_with_staff):
        user, _ = user_with_staff
        tokens = _login(api_client, user).data["data"]
        api_client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json")

        second_response = api_client.post(reverse("auth-refresh"), {"refresh": tokens["refresh"]}, format="json")
        assert second_response.status_code == 401

    def test_invalid_token_returns_401(self, api_client):
        response = api_client.post(reverse("auth-refresh"), {"refresh": "garbage-token-value"}, format="json")
        assert response.status_code == 401
        assert response.data["error"]["code"] == "InvalidToken"

    def test_missing_refresh_field_returns_400(self, api_client):
        response = api_client.post(reverse("auth-refresh"), {}, format="json")
        assert response.status_code == 400


# ── services.generate_tokens / blacklist_token ────────────────────────────────

class TestGenerateTokens:
    def test_embeds_role_from_staff_profile(self, user_with_staff):
        user, staff = user_with_staff
        tokens = generate_tokens(user)
        assert tokens["role"] == staff.role
        assert tokens["email"] == user.email
        assert tokens["access"]
        assert tokens["refresh"]

    def test_role_is_none_without_staff_profile(self, user_without_staff):
        tokens = generate_tokens(user_without_staff)
        assert tokens["role"] is None

    def test_role_claim_embedded_in_refresh_token_payload(self, user_with_staff):
        user, staff = user_with_staff
        tokens = generate_tokens(user)
        decoded = RefreshToken(tokens["refresh"])
        assert decoded["role"] == staff.role


class TestBlacklistToken:
    def test_blacklists_valid_token(self, user_with_staff):
        user, _ = user_with_staff
        tokens = generate_tokens(user)
        blacklist_token(tokens["refresh"])  # must not raise

        with pytest.raises(TokenError):
            RefreshToken(tokens["refresh"])

    def test_already_blacklisted_token_raises_value_error(self, user_with_staff):
        user, _ = user_with_staff
        tokens = generate_tokens(user)
        blacklist_token(tokens["refresh"])
        with pytest.raises(ValueError):
            blacklist_token(tokens["refresh"])

    def test_garbage_token_string_raises_value_error(self, db):
        with pytest.raises(ValueError):
            blacklist_token("not-a-real-token-at-all")


# ── rate_limiting ──────────────────────────────────────────────────────────────

class TestRateLimiting:
    def test_is_ip_rate_limited_false_under_threshold(self):
        assert is_ip_rate_limited("10.0.0.1") is False

    def test_is_ip_rate_limited_true_at_threshold(self):
        cache.set(_ip_attempts_key("10.0.0.2"), IP_RATE_LIMIT, timeout=60)
        assert is_ip_rate_limited("10.0.0.2") is True

    def test_is_user_locked_false_by_default(self):
        assert is_user_locked("nobody@rl-test.com") is False

    def test_is_user_locked_true_when_set(self):
        cache.set(_user_locked_key("locked@rl-test.com"), True, timeout=LOCKOUT_SECONDS)
        assert is_user_locked("locked@rl-test.com") is True

    def test_record_failed_attempt_increments_ip_and_user_independently(self):
        record_failed_attempt("10.0.0.3", "usera@rl-test.com")
        record_failed_attempt("10.0.0.3", "userb@rl-test.com")
        assert cache.get(_ip_attempts_key("10.0.0.3")) == 2
        assert cache.get(_user_attempts_key("usera@rl-test.com")) == 1
        assert cache.get(_user_attempts_key("userb@rl-test.com")) == 1

    def test_record_failed_attempt_locks_user_at_threshold(self):
        for _ in range(USER_RATE_LIMIT):
            record_failed_attempt("10.0.0.4", "lockme@rl-test.com")
        assert is_user_locked("lockme@rl-test.com") is True

    def test_record_failed_attempt_does_not_lock_below_threshold(self):
        for _ in range(USER_RATE_LIMIT - 1):
            record_failed_attempt("10.0.0.6", "notyet@rl-test.com")
        assert is_user_locked("notyet@rl-test.com") is False

    def test_clear_failed_attempts_clears_all_three_keys(self):
        for _ in range(USER_RATE_LIMIT):
            record_failed_attempt("10.0.0.5", "clearme@rl-test.com")
        assert is_user_locked("clearme@rl-test.com") is True

        clear_failed_attempts("10.0.0.5", "clearme@rl-test.com")
        assert cache.get(_ip_attempts_key("10.0.0.5")) is None
        assert cache.get(_user_attempts_key("clearme@rl-test.com")) is None
        assert cache.get(_user_locked_key("clearme@rl-test.com")) is None

    def test_get_lockout_remaining_zero_when_not_locked(self):
        assert get_lockout_remaining("neverlocked@rl-test.com") == 0

    def test_get_lockout_remaining_close_to_lockout_seconds(self):
        cache.set(_user_locked_key("locked2@rl-test.com"), True, timeout=LOCKOUT_SECONDS)
        remaining = get_lockout_remaining("locked2@rl-test.com")
        assert LOCKOUT_SECONDS - 5 <= remaining <= LOCKOUT_SECONDS


# ── decorators.role_required ───────────────────────────────────────────────────

class _DummyView:
    @role_required("store_manager")
    def post(self, request):
        return Response({"success": True, "data": "ok"})


class TestRoleRequiredDecorator:
    def test_no_staff_profile_returns_403_no_staff_profile(self, rf, user_without_staff):
        request = rf.post("/")
        request.user = user_without_staff
        response = _DummyView().post(request)
        assert response.status_code == 403
        assert response.data["error"]["code"] == "NoStaffProfile"

    def test_insufficient_role_returns_403_permission_denied(self, rf, user_with_staff):
        user, _ = user_with_staff  # role="cashier", decorator requires store_manager
        request = rf.post("/")
        request.user = user
        response = _DummyView().post(request)
        assert response.status_code == 403
        assert response.data["error"]["code"] == "PermissionDenied"
        assert "store_manager" in response.data["error"]["errors"][0]
        assert "cashier" in response.data["error"]["errors"][0]

    def test_sufficient_role_passes_through(self, rf, dept):
        user = User.objects.create_user(email="mgr@role-required-test.com", password=PASSWORD)
        Staff.objects.create(
            user=user, first_name="Manager", last_name="Store", email=user.email,
            role="store_manager", department=dept,
        )
        request = rf.post("/")
        request.user = user
        response = _DummyView().post(request)
        assert response.status_code == 200
        assert response.data["data"] == "ok"

    def test_unauthenticated_returns_403_no_staff_profile(self, rf):
        request = rf.post("/")
        request.user = AnonymousUser()
        response = _DummyView().post(request)
        assert response.status_code == 403
        assert response.data["error"]["code"] == "NoStaffProfile"


# ── permissions ────────────────────────────────────────────────────────────────

class TestGetUserRole:
    def test_returns_role_for_staff_user(self, user_with_staff):
        user, staff = user_with_staff
        assert get_user_role(user) == staff.role

    def test_returns_none_without_staff_profile(self, user_without_staff):
        assert get_user_role(user_without_staff) is None

    def test_returns_none_for_none(self):
        assert get_user_role(None) is None

    def test_returns_none_for_anonymous_user(self):
        assert get_user_role(AnonymousUser()) is None

    def test_always_requeries_fresh_rather_than_a_cached_value(self, user_with_staff):
        user, staff = user_with_staff
        assert get_user_role(user) == "cashier"

        staff.role = "store_manager"
        staff.save()

        # A brand-new instance, as a fresh HTTP request would carry —
        # get_user_role must reflect the DB change, not a stale role.
        fresh_user = User.objects.get(pk=user.pk)
        assert get_user_role(fresh_user) == "store_manager"


class TestHasMinimumRole:
    ALL_PERMISSION_CLASSES = [IsCashier, IsDepartmentManager, IsStoreManager, IsAdmin, IsOwner]

    @pytest.mark.parametrize("permission_class,role", [
        (IsCashier, "cashier"),
        (IsDepartmentManager, "department_manager"),
        (IsStoreManager, "store_manager"),
        (IsAdmin, "admin"),
        (IsOwner, "owner"),
    ])
    def test_exact_role_match_passes(self, rf, dept, permission_class, role):
        user = User.objects.create_user(email=f"{role}@perm-test.com", password=PASSWORD)
        Staff.objects.create(user=user, first_name="T", last_name="U", email=user.email, role=role, department=dept)
        request = rf.get("/")
        request.user = user
        assert permission_class().has_permission(request, None) is True

    def test_higher_role_satisfies_lower_requirement(self, rf, dept):
        user = User.objects.create_user(email="owner@perm-test.com", password=PASSWORD)
        Staff.objects.create(user=user, first_name="O", last_name="W", email=user.email, role="owner", department=dept)
        request = rf.get("/")
        request.user = user
        assert IsCashier().has_permission(request, None) is True

    def test_lower_role_fails_higher_requirement(self, rf, dept):
        user = User.objects.create_user(email="cashier2@perm-test.com", password=PASSWORD)
        Staff.objects.create(user=user, first_name="C", last_name="A", email=user.email, role="cashier", department=dept)
        request = rf.get("/")
        request.user = user
        assert IsOwner().has_permission(request, None) is False

    def test_unauthenticated_denied_by_every_subclass(self, rf):
        request = rf.get("/")
        request.user = AnonymousUser()
        for cls in self.ALL_PERMISSION_CLASSES:
            assert cls().has_permission(request, None) is False

    def test_profile_less_user_denied_by_every_subclass(self, rf, user_without_staff):
        request = rf.get("/")
        request.user = user_without_staff
        for cls in self.ALL_PERMISSION_CLASSES:
            assert cls().has_permission(request, None) is False

    def test_hierarchy_is_strictly_greater_or_equal(self, rf, dept):
        """department_manager (2) must satisfy IsCashier (1) and IsDepartmentManager (2)
        but not IsStoreManager (3) — i.e. the comparison is >=, not >."""
        user = User.objects.create_user(email="deptmgr@perm-test.com", password=PASSWORD)
        Staff.objects.create(
            user=user, first_name="D", last_name="M", email=user.email,
            role="department_manager", department=dept,
        )
        request = rf.get("/")
        request.user = user
        assert IsCashier().has_permission(request, None) is True
        assert IsDepartmentManager().has_permission(request, None) is True
        assert IsStoreManager().has_permission(request, None) is False
