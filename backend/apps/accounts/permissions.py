from rest_framework.permissions import BasePermission

ROLE_HIERARCHY = {
    "cashier": 1,
    "department_manager": 2,
    "store_manager": 3,
    "admin": 4,
    "owner": 5,
}


def get_user_role(user):
    """
    Always fetches the current role from the database.
    Never relies on the JWT payload for role enforcement.
    """
    if not user or not user.is_authenticated:
        return None
    try:
        return user.staff_profile.role
    except Exception:
        return None


class HasMinimumRole(BasePermission):
    """
    Base permission class. Subclasses set `minimum_role`.
    Grants access if the user's current DB role meets or exceeds it.
    """

    minimum_role = None

    def has_permission(self, request, view):
        role = get_user_role(request.user)
        if not role:
            return False
        return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(self.minimum_role, 999)


class IsCashier(HasMinimumRole):
    minimum_role = "cashier"


class IsDepartmentManager(HasMinimumRole):
    minimum_role = "department_manager"


class IsStoreManager(HasMinimumRole):
    minimum_role = "store_manager"


class IsAdmin(HasMinimumRole):
    minimum_role = "admin"


class IsOwner(HasMinimumRole):
    minimum_role = "owner"
