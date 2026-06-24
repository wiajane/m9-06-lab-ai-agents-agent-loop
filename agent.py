import asyncio
import json
import os
from datetime import date, datetime

from dateutil.relativedelta import relativedelta
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from dotenv import load_dotenv
load_dotenv()

# Load orders data 
_ORDERS_PATH = os.path.join(os.path.dirname(__file__), "orders.json")
with open(_ORDERS_PATH) as _f:
    ORDERS: dict = json.load(_f)

# Tool 1 – lookup_order
def lookup_order(order_id: str) -> dict:
    """
    Look up an order by its ID.

    Returns item, price, purchase date, warranty_months, warranty_expiry, and
    whether the warranty is currently active. If the order is not found,
    returns an error key explaining that it does not exist.

    Args:
        order_id: The order identifier string, e.g. 'A1001'.
    """
    record = ORDERS.get(order_id.strip().upper())
    if record is None:
        return {"error": f"Order '{order_id}' was not found in the system."}

    purchased = datetime.strptime(record["purchased"], "%Y-%m-%d").date()
    expiry    = purchased + relativedelta(months=record["warranty_months"])
    still_ok  = expiry >= date.today()

    return {
        "order_id":        order_id.upper(),
        "item":            record["item"],
        "price":           record["price"],
        "purchased":       str(purchased),
        "warranty_months": record["warranty_months"],
        "warranty_expiry": str(expiry),
        "warranty_active": still_ok,
    }


# Tool 2 – calculate
def calculate(expression: str) -> dict:
    """
    Evaluate a simple arithmetic expression and return the numeric result.

    Args:
        expression: A Python-style arithmetic string such as '1200 * 2' or
                    '(30 + 80) / 2'.  Only numbers and the operators
                    + - * / ( ) . are accepted.
    """
    allowed = set("0123456789+-*/(). ")
    if not all(c in allowed for c in expression):
        return {"error": "Only numeric arithmetic expressions are permitted."}
    try:
        result = eval(expression, {"__builtins__": {}})  # noqa: S307
        return {"expression": expression, "result": result}
    except Exception as exc:
        return {"error": str(exc)}

# Agent
INSTRUCTIONS = """
You are a helpful customer-orders assistant.

Your responsibilities:
- Answer questions about customer orders using the `lookup_order` tool.
- Perform any arithmetic using the `calculate` tool — never compute numbers
  mentally.
- When a customer asks about a warranty, retrieve the order first, then use
  the `warranty_expiry` and `warranty_active` fields to give a precise answer
  including the exact expiry date.
- If `lookup_order` returns an "error" key, report clearly and honestly that
  the order does not exist. Never invent or guess order details.
- Show your reasoning concisely so the customer understands how you reached
  your answer.
"""

orders_agent = Agent(
    name="orders_assistant",
    model="gemini-2.0-flash",
    description="Customer orders assistant with lookup and calculation tools.",
    instruction=INSTRUCTIONS,
    tools=[lookup_order, calculate],
)


# Async runner
APP_NAME   = "orders_lab"
USER_ID    = "student"
SESSION_ID = "session_01"


async def run_goal(goal: str, label: str = "") -> str:
    """Send a goal to the agent, print the full trace, return the final answer."""
    session_service = InMemorySessionService()
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )

    runner = Runner(
        agent=orders_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )

    divider = "─" * 68
    print(f"\n{'═' * 68}")
    if label:
        print(f"  GOAL [{label}]")
    print(f'  "{goal}"')
    print(f"{'═' * 68}\n")

    content = types.Content(
        role="user",
        parts=[types.Part(text=goal)],
    )

    final_answer = ""
    step = 0

    for event in runner.run(
        user_id=USER_ID,
        session_id=SESSION_ID,
        new_message=content,
    ):
        # Tool call
        if event.get_function_calls():
            for fc in event.get_function_calls():
                step += 1
                print(f"[Step {step}] TOOL CALL  ▶  {fc.name}")
                print(f"           args    : {json.dumps(fc.args)}")

        # Tool result
        if event.get_function_responses():
            for fr in event.get_function_responses():
                print(f"           result  : {json.dumps(fr.response)}")
                print(divider)

        # Final answer
        if event.is_final_response():
            parts = event.content.parts if event.content else []
            final_answer = parts[0].text if parts else ""
            print(f"\n FINAL ANSWER:\n{final_answer}\n")

    return final_answer


async def main() -> None:
    # Required: multi-step goal 
    await run_goal(
        goal=(
            "I'm thinking of buying two more of order A1001. "
            "What would those two cost, and is the original still under warranty?"
        ),
        label="multi-step",
    )

    # Stretch: order that does not exist 
    await run_goal(
        goal="Can you tell me the details for order A9999?",
        label="stretch – unknown order",
    )


if __name__ == "__main__":
    asyncio.run(main())
