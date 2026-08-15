from azure.data.tables import TableServiceClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage

import json
import azure.functions as func
import os

app = func.FunctionApp(
    http_auth_level=func.AuthLevel.ANONYMOUS
)

VALID_CATEGORIES = {
    "travel",
    "meals",
    "supplies",
    "equipment",
    "software",
    "other"
}

@app.route(route="validate-expense", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    try:
        expense = req.get_json()
    except Exception:
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "error": "Invalid JSON body"
            }),
            status_code=400,
            mimetype="application/json"
        )

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
        if field not in expense or expense[field] in [None, ""]
    ]

    if missing_fields:
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "error": "Missing required fields: " + ", ".join(missing_fields)
            }),
            status_code=200,
            mimetype="application/json"
        )

    if expense["category"] not in VALID_CATEGORIES:
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "error": "Invalid category"
            }),
            status_code=200,
            mimetype="application/json"
        )

    try:
        float(expense["amount"])
    except (TypeError, ValueError):
        return func.HttpResponse(
            json.dumps({
                "valid": False,
                "error": "Amount must be a number"
            }),
            status_code=200,
            mimetype="application/json"
        )

    return func.HttpResponse(
        json.dumps({
            "valid": True
        }),
        status_code=200,
        mimetype="application/json"
    )


TABLE_NAME = "managerdecisions"


def get_table_client():
    connection_string = os.environ["AzureWebJobsStorage"]

    service = TableServiceClient.from_connection_string(
        connection_string
    )

    service.create_table_if_not_exists(TABLE_NAME)

    return service.get_table_client(TABLE_NAME)


# Manager clicks Approve or Reject
@app.route(
    route="manager-decision/{requestId}/{decision}",
    methods=["GET"]
)
def record_manager_decision(req: func.HttpRequest) -> func.HttpResponse:

    request_id = req.route_params.get("requestId")
    decision = req.route_params.get("decision")

    if decision not in ["approve", "reject"]:
        return func.HttpResponse(
            "Invalid decision",
            status_code=400
        )

    table = get_table_client()

    entity = {
        "PartitionKey": "expense",
        "RowKey": request_id,
        "decision": decision
    }

    table.upsert_entity(entity)

    return func.HttpResponse(
        f"Expense {decision}d successfully. You may close this page.",
        status_code=200
    )


# Logic App checks manager decision
@app.route(
    route="manager-decision/{requestId}",
    methods=["GET"]
)
def get_manager_decision(req: func.HttpRequest) -> func.HttpResponse:

    request_id = req.route_params.get("requestId")

    table = get_table_client()

    try:
        entity = table.get_entity(
            partition_key="expense",
            row_key=request_id
        )

        result = {
            "decision": entity["decision"]
        }

    except Exception:
        result = {
            "decision": "pending"
        }

    return func.HttpResponse(
        json.dumps(result),
        mimetype="application/json"
    )
    
@app.route(
    route="publish-outcome",
    methods=["POST"]
)
def publish_outcome(req: func.HttpRequest) -> func.HttpResponse:

    try:
        data = req.get_json()
    except ValueError:
        return func.HttpResponse(
            "Invalid JSON",
            status_code=400
        )

    outcome = data.get("outcome")

    if outcome not in ["approved", "rejected", "escalated"]:
        return func.HttpResponse(
            "Invalid outcome",
            status_code=400
        )

    connection_string = os.environ["ServiceBusConnection"]

    with ServiceBusClient.from_connection_string(
        connection_string
    ) as client:

        sender = client.get_topic_sender(
            topic_name="expense-outcomes"
        )

        with sender:

            message = ServiceBusMessage(
                json.dumps(data),
                application_properties={
                    "outcome": outcome
                }
            )

            sender.send_messages(message)

    return func.HttpResponse(
        json.dumps({
            "sent": True,
            "outcome": outcome
        }),
        mimetype="application/json"
    )