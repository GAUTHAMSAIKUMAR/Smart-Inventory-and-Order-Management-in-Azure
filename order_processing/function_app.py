import azure.functions as func
import logging
import json
from sqlalchemy import create_engine, text
import os
import certifi
from fpdf import FPDF
from azure.storage.blob import BlobServiceClient
from io import BytesIO
from datetime import datetime
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import requests

# ---------------- ENVIRONMENT CONFIG ----------------
DATABASE_URL = os.getenv("DATABASE_URL")
SERVICE_BUS_CONN = os.getenv("SERVICE_BUS_CONNECTION_STRING")
BLOB_CONN_STR = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

#  NEW: Logic App URL
LOGIC_APP_URL = os.getenv("LOGIC_APP_URL")

# ---------------- DATABASE SETUP ----------------
ssl_args = {"ssl": {"ca": certifi.where()}}
engine = create_engine(DATABASE_URL, connect_args=ssl_args, pool_pre_ping=True, future=True)

# ---------------- BLOB STORAGE SETUP ----------------
blob_service_client = BlobServiceClient.from_connection_string(BLOB_CONN_STR)
container_name = "invoices"

try:
    blob_service_client.create_container(container_name)
except Exception:
    pass

# ---------------- SERVICE BUS CLIENT ----------------
def send_to_confirmation_queue(order_id):
    message_data = {"order_id": order_id}
    with ServiceBusClient.from_connection_string(SERVICE_BUS_CONN) as client:
        sender = client.get_queue_sender(queue_name="order-confirmation-queue")
        with sender:
            sender.send_messages(ServiceBusMessage(json.dumps(message_data)))
            logging.info(f"📨 Sent confirmation trigger for order_id={order_id}")


# ---------------- FUNCTION APP ----------------
app = func.FunctionApp()


#  Function 1: Process Order
# ===================================================================
@app.service_bus_queue_trigger(
    arg_name="azservicebus",
    queue_name="orders-queue",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def process_order(azservicebus: func.ServiceBusMessage):
    body = azservicebus.get_body().decode("utf-8")
    logging.info("📦 Order message received: %s", body)

    try:
        order_event = json.loads(body)
        order_id = order_event["order_id"]
        warehouse_id = order_event["warehouse_id"]
        items = order_event["items"]

        with engine.begin() as conn:

            # Create or update order
            existing = conn.execute(
                text("SELECT order_id FROM orders WHERE order_id = :oid"),
                {"oid": order_id}
            ).fetchone()

            if not existing:
                conn.execute(
                    text("""
                        INSERT INTO orders (order_id, warehouse_id, status)
                        VALUES (:oid, :wid, 'reserved')
                    """),
                    {"oid": order_id, "wid": warehouse_id}
                )
                logging.info(f"🆕 Inserted new order {order_id}")
            else:
                conn.execute(
                    text("UPDATE orders SET status = 'reserved' WHERE order_id = :oid"),
                    {"oid": order_id}
                )
                logging.info(f"🔄 Updated order {order_id} to reserved")

            # Update inventory
            for item in items:
                product_id = item["product_id"]
                order_qty = item["quantity"]

                current_stock = conn.execute(
                    text("""
                        SELECT quantity FROM inventory
                        WHERE product_id = :pid AND warehouse_id = :wid
                    """),
                    {"pid": product_id, "wid": warehouse_id}
                ).scalar()

                if current_stock is None:
                    continue

                if current_stock < order_qty:
                    conn.execute(
                        text("UPDATE orders SET status = 'failed' WHERE order_id = :oid"),
                        {"oid": order_id}
                    )
                    continue

                remaining_qty = current_stock - order_qty

                conn.execute(
                    text("""
                        UPDATE inventory
                        SET quantity = :remaining
                        WHERE product_id = :pid AND warehouse_id = :wid
                    """),
                    {"remaining": remaining_qty, "pid": product_id, "wid": warehouse_id}
                )

                conn.execute(
                    text("""
                        INSERT INTO order_items (order_id, product_id, quantity, price)
                        VALUES (:oid, :pid, :qty, :price)
                        ON DUPLICATE KEY UPDATE quantity = :qty, price = :price
                    """),
                    {
                        "oid": order_id,
                        "pid": product_id,
                        "qty": order_qty,
                        "price": item["price"]
                    }
                )

        logging.info(f"✅ Inventory updated for Order {order_id}")

        # Send confirmation queue
        send_to_confirmation_queue(order_id)

    except Exception as e:
        logging.error(f"❌ Error in process_order: {str(e)}")
        raise


# ===================================================================
#  NEW PREMIUM PDF DESIGN
# ===================================================================
class InvoicePDF(FPDF):
    def __init__(self):
        super().__init__()
        font_dir = os.path.dirname(os.path.abspath(__file__))
        self.add_font("DejaVu", "", os.path.join(font_dir, "DejaVuSans.ttf"), uni=True)
        self.add_font("DejaVu", "B", os.path.join(font_dir, "DejaVuSans-Bold.ttf"), uni=True)
        self.set_auto_page_break(auto=True, margin=15)

        self.primary = (30, 64, 175)
        self.dark = (15, 23, 42)
        self.alt = (240, 248, 255)
        self.gray = (180, 180, 180)

    def header(self):
        self.set_fill_color(*self.primary)
        self.rect(0, 0, 210, 30, "F")
        self.set_font("DejaVu", "B", 18)
        self.set_text_color(255, 255, 255)
        self.set_y(7)
        self.cell(0, 10, "SYED SAAD|SMART INVENTORY PVT.LTD.", 0, 1, "C")
        self.set_font("DejaVu", "", 11)
        self.cell(0, 8, "Smart Inventory & Order Management", 0, 1, "C")
        self.ln(6)

    def footer(self):
        self.set_y(-20)
        self.set_draw_color(*self.gray)
        self.line(10, self.get_y(), 200, self.get_y())
        self.set_font("DejaVu", "", 9)
        self.set_text_color(90, 90, 90)
        self.ln(2)
        self.cell(0, 8, "Thank you for choosing SMART INVENTORY PVT. LTD.!", 0, 1, "C")
        self.cell(0, 6, "Support: support@smartinventory.com", 0, 0, "C")


# ===================================================================
#  Function 2: Confirm Order + Generate PDF + Send to Logic App
# ===================================================================
@app.service_bus_queue_trigger(
    arg_name="azservicebus",
    queue_name="order-confirmation-queue",
    connection="SERVICE_BUS_CONNECTION_STRING"
)
def confirm_order(azservicebus: func.ServiceBusMessage):
    body = azservicebus.get_body().decode("utf-8")
    logging.info("📥 Confirmation event: %s", body)

    try:
        event = json.loads(body.replace("'", '"'))
        order_id = event["order_id"]

        with engine.begin() as conn:
            order = conn.execute(
                text("SELECT * FROM orders WHERE order_id = :oid"),
                {"oid": order_id}
            ).mappings().first()

            items = conn.execute(
                text("SELECT product_id, quantity, price FROM order_items WHERE order_id = :oid"),
                {"oid": order_id}
            ).mappings().all()

            total_amount = sum(float(i["quantity"]) * float(i["price"]) for i in items)

            conn.execute(
                text("UPDATE orders SET status='confirmed' WHERE order_id=:oid"),
                {"oid": order_id}
            )
            conn.execute(
                text("INSERT INTO invoice(order_id, created_at) VALUES (:oid, NOW())"),
                {"oid": order_id}
            )

        # Create PDF
        pdf = InvoicePDF()
        pdf.add_page()

        pdf.set_fill_color(*pdf.dark)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 14)
        pdf.cell(0, 12, "INVOICE", 0, 1, "C", fill=True)
        pdf.ln(4)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("DejaVu", "", 11)
        pdf.set_fill_color(*pdf.alt)
        pdf.rect(10, pdf.get_y(), 190, 28, "F")
        pdf.ln(2)
        pdf.cell(95, 8, f"Invoice Number: INV-{order_id:04}", 0, 0)
        pdf.cell(95, 8, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}", 0, 1)
        pdf.cell(95, 8, f"Order ID: {order_id}", 0, 0)
        pdf.cell(95, 8, f"Warehouse: {order['warehouse_id']}", 0, 1)
        pdf.ln(6)

        pdf.set_font("DejaVu", "B", 12)
        pdf.cell(0, 10, "Billing Details", 0, 1)
        pdf.set_font("DejaVu", "", 11)

        pdf.set_fill_color(*pdf.alt)
        pdf.rect(10, pdf.get_y(), 190, 20, "F")
        pdf.ln(2)
        pdf.cell(0, 8, "Customer Name : SYED SAAD", 0, 1)
        pdf.cell(0, 8, "Customer Email : saad@example.com", 0, 1)
        pdf.ln(5)

        pdf.set_font("DejaVu", "B", 12)
        pdf.set_fill_color(*pdf.primary)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(50, 10, "Product ID", 1, 0, "C", True)
        pdf.cell(40, 10, "Quantity", 1, 0, "C", True)
        pdf.cell(50, 10, "Price", 1, 0, "C", True)
        pdf.cell(50, 10, "Total", 1, 1, "C", True)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("DejaVu", "", 11)
        toggle = True

        for item in items:
            pid = item["product_id"]
            qty = item["quantity"]
            price = item["price"]
            total = qty * price

            if toggle:
                pdf.set_fill_color(*pdf.alt)
                fill = True
            else:
                fill = False
            toggle = not toggle

            pdf.cell(50, 10, str(pid), 1, 0, "C", fill)
            pdf.cell(40, 10, str(qty), 1, 0, "C", fill)
            pdf.cell(50, 10, f"{price:.2f}", 1, 0, "C", fill)
            pdf.cell(50, 10, f"{total:.2f}", 1, 1, "C", fill)

        pdf.set_fill_color(*pdf.primary)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("DejaVu", "B", 12)
        pdf.cell(140, 12, "Grand Total", 1, 0, "R", True)
        pdf.cell(50, 12, f"₹ {total_amount:.2f}", 1, 1, "C", True)

        pdf_bytes = pdf.output(dest="S").encode("latin1")
        blob_name = f"invoice_order_{order_id}.pdf"

        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(BytesIO(pdf_bytes), overwrite=True)
        blob_url = blob_client.url

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE orders SET invoice_blob=:url WHERE order_id=:oid"),
                {"url": blob_url, "oid": order_id}
            )

        logging.info(f"✅ Invoice uploaded: {blob_url}")

        #  NEW: Call Logic App to send email
        if LOGIC_APP_URL:
            payload = {
                "order_id": order_id,
                "invoice_url": blob_url
            }
            requests.post(LOGIC_APP_URL, json=payload)
            logging.info("📨 Logic App triggered for email sending")

        else:
            logging.error(" LOGIC_APP_URL missing in settings")

    except Exception as e:
        logging.error(f" Error in confirm_order: {str(e)}")
        raise