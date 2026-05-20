from functools import wraps

from rest_framework import status
from rest_framework.response import Response

from .permissions import ROLE_HIERARCHY, get_user_role


def role_required(minimum_role):
    """
    Decorator for APIView methods.
    Usage:
        @role_required('store_manager')
        def post(self, request): ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(view_instance, request, *args, **kwargs):
            role = get_user_role(request.user)
            if not role:
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "NoStaffProfile",
                            "status": 403,
                            "errors": ["Your account has no staff profile assigned."],
                        },
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(minimum_role, 999):
                return Response(
                    {
                        "success": False,
                        "error": {
                            "code": "PermissionDenied",
                            "status": 403,
                            "errors": [
                                f"This action requires {minimum_role} role or above. " f"Your current role is {role}."
                            ],
                        },
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            return func(view_instance, request, *args, **kwargs)

        return wrapper

    return decorator
