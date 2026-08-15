from datetime import timedelta

import azure.functions as func
import azure.durable_functions as df


app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)


VALID_CATEGORIES = {
    "travel",
    "meals",
    "supplies",
    "equipment",
    "software",
    "other"
}


# =========================================================
# HTTP CLIENT - Start Expense Workflow
# =========================================================

@app.route(route="expenses/start", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_expense(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient
):
    try:
        expense = req.get_json()
    except ValueError:
        return func.HttpResponse(
            "Invalid JSON body",
            status_code=400
        )

    instance_id = await client.start_new(
        "expense_orchestrator",
        client_input=expense
    )

    return client.create_check_status_response(
        req,
        instance_id
    )


# =========================================================
# ORCHESTRATOR
# =========================================================

@app.orchestration_trigger(context_name="context")
def expense_orchestrator(
    context: df.DurableOrchestrationContext
):

    expense = context.get_input()

    # Step 1 - Validate expense
    validation_result = yield context.call_activity(
        "validate_expense",
        expense
    )

    if not validation_result["valid"]:
        return {
            "status": "validation_error",
            "error": validation_result["error"]
        }

    # Step 2 - Process expense amount
    process_result = yield context.call_activity(
        "process_expense",
        expense
    )

    # -----------------------------------------
    # Auto-approve expenses under $100
    # -----------------------------------------

    if process_result["status"] == "approved":

        notification = {
            "employeeEmail": expense["employeeEmail"],
            "status": "approved",
            "message": "Your expense was automatically approved."
        }

        notification_result = yield context.call_activity(
            "send_notification",
            notification
        )

        return {
            "status": "approved",
            "approved": True,
            "reason": process_result["reason"],
            "notification": notification_result,
            "expense": expense
        }

    # -----------------------------------------
    # Manager approval required
    # -----------------------------------------

    decision_task = context.wait_for_external_event(
        "manager_decision"
    )

    # One minute timeout for demonstration
    deadline = (
        context.current_utc_datetime
        + timedelta(minutes=1)
    )

    timeout_task = context.create_timer(deadline)

    winner = yield context.task_any([
        decision_task,
        timeout_task
    ])

    # -----------------------------------------
    # Manager responded first
    # -----------------------------------------

    if winner == decision_task:

        decision = decision_task.result

        # Timer is no longer needed
        timeout_task.cancel()

        # Manager approved
        if decision.lower() == "approve":

            notification = {
                "employeeEmail": expense["employeeEmail"],
                "status": "approved",
                "message": "Your expense was approved by your manager."
            }

            notification_result = yield context.call_activity(
                "send_notification",
                notification
            )

            return {
                "status": "approved",
                "approved": True,
                "reason": "Approved by manager",
                "notification": notification_result,
                "expense": expense
            }

        # Manager rejected
        elif decision.lower() == "reject":

            notification = {
                "employeeEmail": expense["employeeEmail"],
                "status": "rejected",
                "message": "Your expense was rejected by your manager."
            }

            notification_result = yield context.call_activity(
                "send_notification",
                notification
            )

            return {
                "status": "rejected",
                "approved": False,
                "reason": "Rejected by manager",
                "notification": notification_result,
                "expense": expense
            }

    # -----------------------------------------
    # Timeout occurred first
    # -----------------------------------------

    notification = {
        "employeeEmail": expense["employeeEmail"],
        "status": "escalated",
        "message": (
            "Your expense was automatically approved "
            "because the manager did not respond before the timeout."
        )
    }

    notification_result = yield context.call_activity(
        "send_notification",
        notification
    )

    return {
        "status": "escalated",
        "approved": True,
        "reason": "Manager did not respond before timeout",
        "notification": notification_result,
        "expense": expense
    }


# =========================================================
# ACTIVITY - Validate Expense
# =========================================================

@app.activity_trigger(input_name="expense")
def validate_expense(expense: dict):

    required_fields = [
        "employeeName",
        "employeeEmail",
        "amount",
        "category",
        "description",
        "managerEmail"
    ]

    missing_fields = [
        field
        for field in required_fields
        if field not in expense
        or expense[field] in [None, ""]
    ]

    if missing_fields:
        return {
            "valid": False,
            "error": (
                "Missing required fields: "
                + ", ".join(missing_fields)
            )
        }

    if expense["category"] not in VALID_CATEGORIES:
        return {
            "valid": False,
            "error": "Invalid category"
        }

    try:
        float(expense["amount"])
    except (TypeError, ValueError):
        return {
            "valid": False,
            "error": "Amount must be a number"
        }

    return {
        "valid": True
    }


# =========================================================
# ACTIVITY - Process Expense
# =========================================================

@app.activity_trigger(input_name="expense")
def process_expense(expense: dict):

    amount = float(expense["amount"])

    if amount < 100:
        return {
            "status": "approved",
            "approved": True,
            "reason": (
                "Auto-approved because amount is under $100"
            )
        }

    return {
        "status": "manager_required",
        "approved": None,
        "reason": "Manager approval required"
    }


# =========================================================
# HTTP CLIENT - Manager Decision
# =========================================================

@app.route(
    route="expenses/{instanceId}/decision",
    methods=["POST"]
)
@app.durable_client_input(client_name="client")
async def manager_decision(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient
):
    instance_id = req.route_params.get("instanceId")

    try:
        body = req.get_json()
    except ValueError:
        return func.HttpResponse(
            "Invalid JSON body",
            status_code=400
        )

    decision = body.get("decision")

    if decision not in ["approve", "reject"]:
        return func.HttpResponse(
            "Decision must be 'approve' or 'reject'",
            status_code=400
        )

    await client.raise_event(
        instance_id,
        "manager_decision",
        decision
    )

    return func.HttpResponse(
        f"Manager decision '{decision}' sent successfully.",
        status_code=200
    )


# =========================================================
# ACTIVITY - Send Notification
# =========================================================

@app.activity_trigger(input_name="notification")
def send_notification(notification: dict):

    # Simulated notification for local development.
    # Replace with a real email provider before final submission
    # if an actual email is required.

    return {
        "emailSent": True,
        "to": notification["employeeEmail"],
        "status": notification["status"],
        "message": notification["message"]
    }