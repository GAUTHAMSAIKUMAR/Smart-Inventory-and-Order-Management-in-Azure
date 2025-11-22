from fastapi import FastAPI
from app.routes import suppliers, products, warehouses, inventory, orders,auth_router
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
# from app import auth 
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "ssl": {"ca": "D:\\PROJECT\\certs\\DigiCertGlobalRootG2.crt.pem"}
    },
    pool_pre_ping=True,
)


app = FastAPI(title="Smart Inventory API")
app.include_router(auth_router.router)
app.include_router(suppliers.router)
app.include_router(products.router)
app.include_router(warehouses.router)
app.include_router(inventory.router)
app.include_router(orders.router)

@app.get("/")
def root():
    return {"message": "Smart Inventory & Order Management API is running"}