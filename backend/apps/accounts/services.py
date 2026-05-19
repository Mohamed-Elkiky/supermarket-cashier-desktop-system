from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken


def generate_tokens(user):
    refresh = RefreshToken.for_user(user)

    # Embed role into token payload for RBAC checks
    role = None
    if hasattr(user, "staff_profile") and user.staff_profile:
        role = user.staff_profile.role
    refresh["role"] = role

    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "email": user.email,
        "role": role,
    }


def blacklist_token(refresh_token: str):
    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
    except TokenError as e:
        raise ValueError(str(e))
