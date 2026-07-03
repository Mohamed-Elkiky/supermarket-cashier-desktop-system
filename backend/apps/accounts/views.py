import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from .serializers import LoginSerializer, LogoutSerializer, RefreshSerializer
from .services import generate_tokens, blacklist_token
from .rate_limiting import (
    is_ip_rate_limited,
    is_user_locked,
    record_failed_attempt,
    clear_failed_attempts,
    get_lockout_remaining,
)
from apps.core.activity import log_activity

logger = logging.getLogger("apps.accounts")


def get_client_ip(request) -> str:
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "0.0.0.0")


class LoginView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Login",
        description="Authenticate with email and password. Returns a 15-minute access token and a 7-day rotating refresh token. Account is locked after 5 failed attempts for 15 minutes.",
        request=LoginSerializer,
        responses={
            200: OpenApiResponse(
                description="Login successful",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={
                            "success": True,
                            "data": {
                                "access": "eyJ...",
                                "refresh": "eyJ...",
                                "email": "staff@store.com",
                                "role": "cashier",
                            },
                        },
                    )
                ],
            ),
            400: OpenApiResponse(description="Invalid credentials"),
            429: OpenApiResponse(description="Rate limited or account locked"),
        },
        tags=["Authentication"],
    )
    def post(self, request):
        ip = get_client_ip(request)
        email = request.data.get("email", "").lower().strip()

        if is_ip_rate_limited(ip):
            logger.warning("IP rate limited: %s", ip)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "RateLimitExceeded",
                        "status": 429,
                        "errors": ["Too many login attempts from this IP. Try again later."],
                    },
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if email and is_user_locked(email):
            remaining = get_lockout_remaining(email)
            logger.warning("Locked account login attempt: %s from IP %s", email, ip)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "AccountLocked",
                        "status": 429,
                        "errors": [
                            f"Account locked due to too many failed attempts. "
                            f"Try again in {remaining // 60} minutes."
                        ],
                    },
                },
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = LoginSerializer(data=request.data, context={"request": request})

        if not serializer.is_valid():
            if email:
                record_failed_attempt(ip, email)
            return Response(
                {
                    "success": False,
                    "error": {
                        "code": "ValidationError",
                        "status": 400,
                        "errors": serializer.errors,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = serializer.validated_data["user"]
        clear_failed_attempts(ip, email)
        tokens = generate_tokens(user)

        log_activity(
            request=request,
            action="auth.login",
            entity_type="auth_users",
            entity_id=user.id,
            after_state={"email": user.email, "ip": ip},
        )

        logger.info("User logged in: %s from IP %s", user.email, ip)
        return Response({"success": True, "data": tokens}, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Logout",
        description="Blacklist the refresh token. The access token expires naturally after 15 minutes. Requires a valid Bearer token in the Authorization header.",
        request=LogoutSerializer,
        responses={
            200: OpenApiResponse(description="Logged out successfully"),
            400: OpenApiResponse(description="Invalid or already blacklisted token"),
            401: OpenApiResponse(description="Not authenticated"),
        },
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            blacklist_token(serializer.validated_data["refresh"])
        except ValueError as e:
            return Response(
                {"success": False, "error": {"code": "InvalidToken", "errors": [str(e)]}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        log_activity(
            request=request,
            action="auth.logout",
            entity_type="auth_users",
            entity_id=request.user.id,
            after_state={"email": request.user.email},
        )

        logger.info("User logged out: %s", request.user.email)
        return Response({"success": True}, status=status.HTTP_200_OK)


class SilentRefreshView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        summary="Silent token refresh",
        description="Exchange a valid refresh token for a new access token and rotated refresh token. Call this before the access token expires to keep the user logged in seamlessly.",
        request=RefreshSerializer,
        responses={
            200: OpenApiResponse(
                description="New tokens issued",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={
                            "success": True,
                            "data": {
                                "access": "eyJ...",
                                "refresh": "eyJ...",
                            },
                        },
                    )
                ],
            ),
            401: OpenApiResponse(description="Refresh token invalid or blacklisted"),
        },
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            refresh = RefreshToken(serializer.validated_data["refresh"])
            new_access = str(refresh.access_token)

            # Mirrors rest_framework_simplejwt.serializers.TokenRefreshSerializer's
            # own rotation logic: blacklist the old jti, then mutate this SAME
            # token object into a new one (new jti/exp/iat). Mutating in place
            # rather than minting RefreshToken.for_user() fresh naturally
            # preserves any other claims already embedded on it — e.g. the
            # "role" claim services.generate_tokens() sets at login.
            if api_settings.ROTATE_REFRESH_TOKENS:
                if api_settings.BLACKLIST_AFTER_ROTATION:
                    try:
                        refresh.blacklist()
                    except AttributeError:
                        # Blacklist app not installed — nothing to do.
                        pass

                refresh.set_jti()
                refresh.set_exp()
                refresh.set_iat()

            new_refresh = str(refresh)
            return Response(
                {"success": True, "data": {"access": new_access, "refresh": new_refresh}},
                status=status.HTTP_200_OK,
            )
        except TokenError as e:
            return Response(
                {"success": False, "error": {"code": "InvalidToken", "errors": [str(e)]}},
                status=status.HTTP_401_UNAUTHORIZED,
            )