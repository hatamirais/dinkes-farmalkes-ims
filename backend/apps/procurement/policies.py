from __future__ import annotations

from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.users.access import can_approve_workflow, has_module_permission
from apps.users.models import ModuleAccess

from .models import ProcurementAmendment, ProcurementContract
from .services import contract_is_cancellable


def procurement_policy_required(check, message: str):
    """Guard a procurement view with one of this module's named policies."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied(message)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


def _has_hybrid_permission(user, permission: str) -> bool:
    """Match the project's Django-permission OR module-scope contract."""
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_superuser", False)
            or user.has_perm(permission)
            or has_module_permission(user, permission)
        )
    )


def can_view_contract(user) -> bool:
    return _has_hybrid_permission(user, "procurement.view_procurementcontract")


def can_create_contract(user) -> bool:
    return _has_hybrid_permission(user, "procurement.add_procurementcontract")


def can_change_contract(user) -> bool:
    return _has_hybrid_permission(user, "procurement.change_procurementcontract")


def can_approve_procurement_documents(user) -> bool:
    return can_approve_workflow(user, ModuleAccess.Module.PROCUREMENT)


def contract_accepts_amendment_changes(contract: ProcurementContract) -> bool:
    return (
        contract.status == ProcurementContract.Status.APPROVED
        and contract.closed_at is None
    )


def can_edit_contract(user, contract: ProcurementContract) -> bool:
    return can_change_contract(user) and contract.status == ProcurementContract.Status.DRAFT


def can_submit_contract(user, contract: ProcurementContract) -> bool:
    return can_change_contract(user) and contract.status == ProcurementContract.Status.DRAFT


def can_approve_contract(user, contract: ProcurementContract) -> bool:
    return (
        can_approve_procurement_documents(user)
        and contract.status == ProcurementContract.Status.SUBMITTED
    )


def can_close_contract(user, contract: ProcurementContract) -> bool:
    return can_change_contract(user) and contract.status == ProcurementContract.Status.APPROVED


def can_cancel_contract(
    user,
    contract: ProcurementContract,
    linked_receiving=None,
) -> bool:
    return can_change_contract(user) and contract_is_cancellable(
        contract,
        linked_receiving,
    )


def can_view_amendment(user) -> bool:
    return _has_hybrid_permission(user, "procurement.view_procurementamendment")


def can_add_amendment(user) -> bool:
    return _has_hybrid_permission(user, "procurement.add_procurementamendment")


def can_create_amendment(user, contract: ProcurementContract) -> bool:
    return can_add_amendment(user) and contract_accepts_amendment_changes(contract)


def can_change_amendment(user) -> bool:
    return _has_hybrid_permission(user, "procurement.change_procurementamendment")


def can_edit_amendment(user, amendment: ProcurementAmendment) -> bool:
    return (
        can_change_amendment(user)
        and amendment.status == ProcurementAmendment.Status.DRAFT
        and contract_accepts_amendment_changes(amendment.contract)
    )


def can_submit_amendment(user, amendment: ProcurementAmendment) -> bool:
    return can_edit_amendment(user, amendment)


def can_approve_amendment(user, amendment: ProcurementAmendment) -> bool:
    return (
        can_approve_procurement_documents(user)
        and amendment.status == ProcurementAmendment.Status.SUBMITTED
        and contract_accepts_amendment_changes(amendment.contract)
    )


def contract_actions(
    user,
    contract: ProcurementContract,
    linked_receiving=None,
) -> dict[str, bool]:
    """Return the decisions shared by contract routes and templates."""
    can_change = can_change_contract(user)
    can_approve = can_approve_procurement_documents(user)
    accepts_amendments = contract_accepts_amendment_changes(contract)
    return {
        "can_edit": can_change and contract.status == ProcurementContract.Status.DRAFT,
        "can_submit": can_change and contract.status == ProcurementContract.Status.DRAFT,
        "can_approve": can_approve
        and contract.status == ProcurementContract.Status.SUBMITTED,
        "can_close": can_change
        and contract.status == ProcurementContract.Status.APPROVED,
        "can_cancel": can_change
        and contract_is_cancellable(contract, linked_receiving),
        "can_create_amendment": can_add_amendment(user) and accepts_amendments,
    }


def amendment_actions(user, amendment: ProcurementAmendment) -> dict[str, bool]:
    """Return the decisions shared by amendment routes and templates."""
    can_change = can_change_amendment(user)
    is_editable = (
        amendment.status == ProcurementAmendment.Status.DRAFT
        and contract_accepts_amendment_changes(amendment.contract)
    )
    return {
        "can_edit": can_change and is_editable,
        "can_submit": can_change and is_editable,
        "can_approve": can_approve_procurement_documents(user)
        and amendment.status == ProcurementAmendment.Status.SUBMITTED
        and contract_accepts_amendment_changes(amendment.contract),
    }
