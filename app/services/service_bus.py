# import os
# from azure.servicebus import ServiceBusClient, ServiceBusMessage
# from dotenv import load_dotenv

# load_dotenv()

# # Service Bus connection
# CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING")

# # Default queue names
# ORDERS_QUEUE = os.getenv("ORDERS_QUEUE_NAME", "orders-queue")
# CONFIRMATION_QUEUE = os.getenv("CONFIRMATION_QUEUE_NAME", "order-confirmation-queue")


# def send_message(queue_name: str, message_data: dict):
#     """Generic message sender — can send to any queue."""
#     with ServiceBusClient.from_connection_string(CONN_STR) as client:
#         sender = client.get_queue_sender(queue_name)    
#         with sender:
#             message = ServiceBusMessage(str(message_data))
#             sender.send_messages(message)
#             print(f"✅ Sent message to queue: {queue_name} | Data: {message_data}")


# def publish_order_event(order_event: dict):
#     """
#     Compatibility function — still used by your FastAPI /orders route.
#     It always sends order events to the orders-queue.
#     """
#     send_message(ORDERS_QUEUE, order_event)

import os
import json  # ✅ Add JSON support
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from dotenv import load_dotenv

load_dotenv()

# Service Bus connection
CONN_STR = os.getenv("SERVICE_BUS_CONNECTION_STRING")

# Default queue names
ORDERS_QUEUE = os.getenv("ORDERS_QUEUE_NAME", "orders-queue")
CONFIRMATION_QUEUE = os.getenv("CONFIRMATION_QUEUE_NAME", "order-confirmation-queue")


def send_message(queue_name: str, message_data: dict):
    """Generic message sender — can send to any queue."""
    with ServiceBusClient.from_connection_string(CONN_STR) as client:
        sender = client.get_queue_sender(queue_name)
        with sender:
            # ✅ Use JSON, not str()
            message = ServiceBusMessage(json.dumps(message_data))
            sender.send_messages(message)
            print(f"✅ Sent message to queue: {queue_name} | Data: {json.dumps(message_data)}")


def publish_order_event(order_event: dict):
    """
    Compatibility function — still used by your FastAPI /orders route.
    It always sends order events to the orders-queue.
    """
    send_message(ORDERS_QUEUE, order_event)