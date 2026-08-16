# CST8917 Assignment 2 — Compare & Contrast: Dual Implementation of an Expense Approval Workflow

**Name:** Jingjing Duan  
**Student Number:** 041159829  
**Course:** CST8917 — Serverless Applications  
**Project:** Assignment 2 — Expense Approval Workflow  
**Date:** August 15, 2026  

---
##  Presentation Video
YouTube URL: https://youtu.be/vRheYvmATvs

## Project Overview

This project implements the same expense approval workflow using two Azure serverless orchestration approaches:

- **Version A:** Azure Durable Functions using the Python v2 programming model
- **Version B:** Azure Logic Apps with Azure Service Bus and Azure Functions

The workflow validates an expense request, automatically approves expenses under $100, requests manager approval for expenses of $100 or more, handles manager timeout, and notifies the employee of the final result.

Valid expense categories are:

`travel`, `meals`, `supplies`, `equipment`, `software`, and `other`.

The same six business scenarios were tested in both implementations:

1. Valid expense under $100 — auto-approved
2. Valid expense of $100 or more — manager approves
3. Valid expense of $100 or more — manager rejects
4. Valid expense of $100 or more — no manager response, escalated
5. Missing required field — validation error
6. Invalid category — validation error

---

## Version A — Azure Durable Functions

Version A implements the workflow using Azure Durable Functions and the Python v2 programming model.

The application contains an HTTP client function, an orchestrator, and several activity functions. The HTTP endpoint starts a new orchestration instance. The orchestrator controls the workflow and calls activities for validation, expense processing, and employee notification.

Expenses under $100 are automatically approved. Expenses of $100 or more use the Durable Functions **Human Interaction pattern**. The orchestrator creates two durable tasks: an external event that waits for a manager decision and a durable timer that represents the timeout. The orchestrator uses `task_any()` to continue when either the manager decision or the timer completes first.

A separate HTTP endpoint allows the manager decision to be simulated by sending either `approve` or `reject`. If the manager responds before the timer expires, the external event completes and the workflow uses that decision. If the timer completes first, the expense is automatically approved and flagged as escalated.

One challenge during development was handling the value returned by the external event. The manager decision was returned as a JSON-encoded string, so I had to decode and normalize the value before comparing it with `approve` or `reject`. After correcting that issue, all six Durable Functions scenarios passed.

The tests for Version A are stored in `version-a-durable-functions/test-durable.http`.

---

## Version B — Azure Logic Apps + Service Bus

Version B implements the same workflow using Azure Logic Apps, Azure Service Bus, Azure Functions, Azure Table Storage, and Office 365 Outlook.

Incoming expense requests are placed on the `expense-requests` Service Bus queue. The Logic App uses a Service Bus trigger to receive each request and then parses the message body. Because the Service Bus message content arrived Base64-encoded, the workflow decodes the content before parsing the JSON.

The Logic App calls an Azure Function to validate required fields and allowed categories. If validation fails, the employee receives a rejected notification when an email address is available and a rejected outcome is published.

For valid expenses under $100, the Logic App immediately sends an approved email to the employee.

For expenses of $100 or more, the Logic App sends an email to the manager containing **Approve** and **Reject** links. These links call Azure Function endpoints. The Azure Function stores the manager decision in Azure Table Storage using a generated request ID. The Logic App waits for a short delay and then calls another Function endpoint to retrieve the manager decision.

The workflow then evaluates the returned decision:

- `approve` → employee receives an approved email
- `reject` → employee receives a rejected email
- `pending` → no manager response was received before the timeout, so the request is automatically approved and marked as escalated

Final outcomes are published to the `expense-outcomes` Service Bus topic. The publisher Function adds an `outcome` application property. Three topic subscriptions use SQL filters:

- `approved-sub`: `outcome = 'approved'`
- `rejected-sub`: `outcome = 'rejected'`
- `escalated-sub`: `outcome = 'escalated'`

The main challenge was implementing manager interaction because Logic Apps does not provide the same durable external-event waiting model as Durable Functions. I implemented the interaction using email links, an Azure Function, Azure Table Storage, a delay, and a decision lookup.

Another issue occurred when the Logic App HTTP action appeared to contain a JSON body but the Function received an empty request body. I solved this by explicitly converting the parsed request to a string before sending it to the validation Function.

All six Version B scenarios were tested successfully. Supporting screenshots are stored in `version-b-logic-apps/screenshots/`.

---

# Comparison Analysis

## 1. Development Experience

The two versions provided very different development experiences. Durable Functions was more code-focused and initially required more understanding of orchestration concepts. I had to understand the relationship between the HTTP client, orchestrator, activity functions, external events, and durable timers. The Human Interaction pattern was not obvious at first, but once the structure was implemented, the workflow became relatively compact and logically consistent.

Logic Apps was easier to understand visually because every step was visible in the Designer. Conditions for validation, the $100 threshold, approval, rejection, and escalation could be seen as separate branches. This made the business workflow easier to explain to another person.

However, Version B took longer to build than I expected. The visual designer did not remove the need for debugging. I encountered issues with Base64 Service Bus content, HTTP body formatting, unsaved workflow changes, action references, and manager-decision state. Some errors were actually harder to diagnose because part of the logic was in the Logic App and part was in Azure Functions.

Overall, Logic Apps was faster for creating simple conditions and email actions, but Durable Functions gave me more confidence in the complete workflow because the orchestration logic was centralized in code.

## 2. Testability

Durable Functions was clearly easier to test locally. I could run Azurite, start the Functions host, and use `test-durable.http` to start orchestrations, send manager decisions, and query orchestration status. Most of the logic could be tested without using the Azure portal.

Version B depended much more heavily on deployed Azure resources. The complete workflow required Service Bus, Logic Apps, Outlook, Azure Functions, and Table Storage. I could test the validation and manager-decision Functions locally with `test-expense.http`, but I could not realistically reproduce the full Logic App workflow using only local tools.

Automated testing would also be easier for Version A because Python functions can be covered with unit tests and orchestration behavior can be tested with mocks. Logic Apps can be tested, but the tests would normally involve deployed workflows, mocked connectors, or integration-test infrastructure.

For this assignment, I found Durable Functions more convenient for repeatable technical testing, while Logic Apps was easier for visually confirming the path that a particular request followed.

## 3. Error Handling

Durable Functions provided more direct control over failures, retries, exception handling, and workflow state. Activity functions can be wrapped in retry policies or exception handling, and the orchestrator can decide exactly what should happen after a failure. Durable Functions also persists orchestration history, so the workflow can resume after restarts instead of requiring the application to keep an active process running.

Logic Apps has useful built-in retry policies, run-after configuration, and detailed action status. These features are convenient because they can be configured without writing much code. However, once the workflow became more complex, I had to handle errors across several services. For example, the validation Function, HTTP actions, Outlook connector, Service Bus, and Table Storage could each fail independently.

For a development team that wants detailed programmatic recovery logic, I would prefer Durable Functions. For workflows made mostly from standard connectors where built-in retry behavior is sufficient, Logic Apps provides a convenient approach.

## 4. Human Interaction Pattern

This was the largest difference between the implementations.

Durable Functions handled manager approval naturally. The orchestrator created an external-event task and a durable timer, then waited for whichever completed first. The workflow did not need to continuously poll while waiting. The external event represented the manager response directly, and the timer represented the timeout.

Logic Apps did not provide an equivalent mechanism in the way I designed the project. I had to create a custom solution. The manager received Approve and Reject links, an Azure Function recorded the decision in Table Storage, the Logic App waited using a Delay action, and another HTTP request retrieved the saved decision.

This implementation worked, but it required more components and additional state management. It also demonstrated why Durable Functions is a strong option for stateful serverless workflows involving human approval and timeout behavior.

For this specific requirement, Durable Functions was significantly more natural.

## 5. Observability

Logic Apps had the best visual observability. Run History showed each action, its inputs and outputs, whether it succeeded, failed, or was skipped, and which condition branch was executed. This was extremely useful when verifying the six scenarios and taking screenshots for the assignment.

For example, I could open a successful run and immediately see that validation returned `true`, the amount condition evaluated to false, the manager decision evaluated to `approve`, and the approved branch completed.

Durable Functions also provides useful status information, including orchestration instance ID, runtime status, input, output, and execution history. During development I could query the status endpoint and inspect Function logs. However, understanding the overall workflow required more familiarity with the code and Durable Functions runtime.

Therefore, Logic Apps was better for visual troubleshooting and demonstrating the workflow, while Durable Functions gave more developer-oriented control through logs, status endpoints, and code.

## 6. Cost

The cost comparison depends on execution volume, workflow path, connector usage, memory allocation, and Function duration. The estimates below use a 30-day month and assume the requests are small, Function executions are short, and no Always Ready Functions instances are configured.

For Logic Apps Consumption, Microsoft currently lists workflow actions at **$0.000025 per execution after the first 4,000 actions per month**, and Standard connector calls at **$0.000125 per call**. Service Bus Standard is also required because topics are not available in the Basic tier. Service Bus Standard has a base charge, while its first 13 million messaging operations per month are included in that tier.

For Azure Functions Flex Consumption, Microsoft provides a monthly free grant of **250,000 executions and 100,000 GB-s** for on-demand execution. Storage is billed separately.

### Approximate monthly workload

| Volume | Monthly expenses |
|---|---:|
| 100 expenses/day | ~3,000 |
| 10,000 expenses/day | ~300,000 |

For a rough Logic Apps estimate, I assumed an average of approximately eight metered workflow actions and three Standard connector calls per expense. Actual execution counts vary because manager-approved workflows use more actions than auto-approved requests.

At **100 expenses/day**, approximately 24,000 Logic App actions would execute each month. After the first 4,000 free actions, the action cost would be about **$0.50 USD/month**. About 9,000 Standard connector calls would cost approximately **$1.13 USD/month**. Therefore, the Logic Apps usage portion would be roughly **$1.63 USD/month, plus the Service Bus Standard base charge, Function execution, storage, and any other connector-related charges**.

At **10,000 expenses/day**, approximately 2.4 million Logic App actions would execute each month. The action portion would be about **$59.90 USD/month**, while about 900,000 Standard connector calls would be approximately **$112.50 USD/month**. This gives roughly **$172.40 USD/month for Logic Apps actions and Standard connector calls alone**, before the Service Bus Standard base charge, Functions, and storage.

Version A has fewer separate Azure services. At 100 expenses/day, the number of Function executions would remain well below the Flex Consumption monthly free execution grant under the assumptions used here, so compute cost would be minimal and storage would be the main small additional charge. At 10,000 expenses/day, the workload could exceed the free execution grant depending on the average number of orchestrator and activity executions per request, but the cost would still be primarily based on actual Function execution and GB-s consumption rather than a large number of paid workflow connector actions.

Based on this design, I expect Version A to be cheaper for the high-volume case, while the difference matters much less at 100 requests per day. These figures are estimates only; production pricing should be recalculated in the Azure Pricing Calculator using the selected region, subscription offer, actual execution duration, and measured connector/action counts.

---

# Recommendation

For a production implementation of this expense approval workflow, I would choose **Azure Durable Functions**.

The strongest reason is the manager approval requirement. Durable Functions models this requirement directly with the Human Interaction pattern. The orchestrator can wait for a manager external event and a durable timer at the same time without requiring a continuously running process. This keeps the approval and timeout behavior inside one orchestration model and avoids adding extra state-management components.

My Version B implementation worked correctly, but implementing the manager interaction required a Logic App, email links, HTTP Functions, Table Storage, a delay, and a decision lookup. That increased the number of components and created more integration points where configuration or formatting errors could occur. I experienced several of these issues during implementation, including Service Bus message encoding and HTTP request-body behavior.

I would also choose Durable Functions because local testing was easier and the orchestration logic can be version-controlled, reviewed, and tested as Python code. At higher transaction volumes, I would also expect the code-first solution to have a cost advantage because Logic Apps charges for workflow actions and connector calls.

I would choose **Logic Apps instead** when the workflow is primarily integration-focused, uses many SaaS or Azure connectors, and needs to be understood or maintained by teams that prefer a visual workflow. Logic Apps also provides excellent visual run history, which made individual workflow executions very easy to inspect.

---

# Screenshots

Version B evidence is stored under:

```text
version-b-logic-apps/screenshots/
```

The screenshots include:

- Logic App Run History
- Condition branch execution
- Approved email
- Rejected email
- Escalated email
- Service Bus topic subscription message counts

---

# Repository Structure

```text
CST8917-FinalProject-JingjingDuan/
├── README.md
├── version-a-durable-functions/
│   ├── function_app.py
│   ├── requirements.txt
│   ├── host.json
│   ├── local.settings.example.json
│   └── test-durable.http
├── version-b-logic-apps/
│   ├── function_app.py
│   ├── requirements.txt
│   ├── local.settings.example.json
│   ├── test-expense.http
│   └── screenshots/
└── presentation/
    ├── slides.pptx
    └── video-link.md
```

---

# References

- Microsoft Learn. [Azure Durable Functions overview](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview)
- Microsoft Learn. [Durable Functions human interaction pattern](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview#human)
- Microsoft Learn. [Azure Logic Apps documentation](https://learn.microsoft.com/azure/logic-apps/)
- Microsoft Learn. [Azure Service Bus messaging overview](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-messaging-overview)
- Microsoft Azure. [Azure Functions pricing](https://azure.microsoft.com/pricing/details/functions/)
- Microsoft Azure. [Azure Logic Apps pricing](https://azure.microsoft.com/pricing/details/logic-apps/)
- Microsoft Azure. [Azure Service Bus pricing](https://azure.microsoft.com/pricing/details/service-bus/)
- Microsoft Azure. [Azure Table Storage pricing](https://azure.microsoft.com/pricing/details/storage/tables/)
- Microsoft Azure. [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)

---

# AI Disclosure

Generative AI tools were used during this project as a learning and development assistant. AI was used to help explain Azure Durable Functions and Logic Apps concepts, troubleshoot implementation issues, review code, suggest testing steps, and assist with drafting and editing project documentation.

All generated suggestions were reviewed, adapted, implemented, and tested by me. I verified the workflow behavior using my own Azure resources and completed the six required test scenarios for both implementations. The final technical decisions, implementation, testing, screenshots, comparison, and presentation are my own work.
