from rest_framework import permissions


class IsStoreOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        return bool(
            obj.user == request.user
            or getattr(request.user, "is_admin_user", False)
        )


class CanCreateStore(permissions.BasePermission):
    """
    Permission to allow creating stores only if the user can create stores
    (e.g. seller). Requires authentication.
    """

    def has_permission(self, request, view):
        if request.method == "POST":
            return bool(request.user and request.user.is_authenticated and getattr(request.user, "can_create_stores", False))
        return True


class CanManageStore(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in ["PUT", "PATCH", "DELETE"]:
            return bool(
                request.user
                and request.user.is_authenticated
                and getattr(request.user, "can_manage_stores", False)
            )
        return True
