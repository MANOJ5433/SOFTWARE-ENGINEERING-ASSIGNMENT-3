"""Domain constants: roles, booking and ticket state models, and permission rules."""

MANAGER_ROLES = ("admin", "facility_manager")
APPROVER_ROLES = ("admin", "facility_manager", "approver")
STAFF_ROLES = ("admin", "facility_manager", "technician", "approver")

BOOKING_ACTIVE = ("REQUESTED", "APPROVED", "CONFIRMED", "IN_USE")
BOOKING_STATUSES = BOOKING_ACTIVE + ("COMPLETED", "CANCELLED")

# (current state, action) -> next state
BOOKING_TRANSITIONS = {
    ("REQUESTED", "approve"): "APPROVED",
    ("REQUESTED", "reject"): "CANCELLED",
    ("REQUESTED", "cancel"): "CANCELLED",
    ("APPROVED", "confirm"): "CONFIRMED",
    ("APPROVED", "cancel"): "CANCELLED",
    ("CONFIRMED", "start"): "IN_USE",
    ("CONFIRMED", "cancel"): "CANCELLED",
    ("IN_USE", "complete"): "COMPLETED",
}
BOOKING_ACTION_ROLES = {
    "approve": APPROVER_ROLES,
    "reject": APPROVER_ROLES,
    "confirm": MANAGER_ROLES,
    "start": MANAGER_ROLES,
    "complete": MANAGER_ROLES,
    "cancel": MANAGER_ROLES,
}
# Actions the original requester may perform on their own booking, in addition to the roles above.
REQUESTER_ACTIONS = {"confirm", "start", "complete", "cancel"}

TICKET_STATUSES = ("INTAKE", "ASSIGNED", "INSPECTION", "PENDING_WORK", "RESOLVED", "CLOSED")
TICKET_TRANSITIONS = {
    ("INTAKE", "assign"): "ASSIGNED",
    ("ASSIGNED", "assign"): "ASSIGNED",
    ("ASSIGNED", "start_inspection"): "INSPECTION",
    ("INSPECTION", "pending_work"): "PENDING_WORK",
    ("INSPECTION", "resolve"): "RESOLVED",
    ("PENDING_WORK", "resolve"): "RESOLVED",
    ("RESOLVED", "close"): "CLOSED",
    ("RESOLVED", "reopen"): "ASSIGNED",
}
TICKET_ACTION_ROLES = {"assign": MANAGER_ROLES, "close": MANAGER_ROLES, "reopen": MANAGER_ROLES}
# Field actions are allowed for the assigned technician, or for a manager.
FIELD_ACTIONS = {"start_inspection", "pending_work", "resolve"}

TICKET_CATEGORIES = ("ELECTRICAL", "PLUMBING", "HVAC", "SAFETY", "FURNITURE_FIXTURE", "OTHER")
PRIORITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
SENSOR_TYPES = ("TEMPERATURE", "SMOKE_LEVEL")
