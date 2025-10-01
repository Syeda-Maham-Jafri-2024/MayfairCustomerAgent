import logging
import asyncio
import json
import os
from pathlib import Path
import random
from openai import OpenAI
from openai import AsyncOpenAI
import requests
from dotenv import load_dotenv
from urllib.parse import urlencode
from livekit.agents import (
    Agent,
    RunContext,
    function_tool,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    AutoSubscribe,
    RoomInputOptions,
)
from livekit.agents import metrics
from livekit.plugins import openai, silero
from livekit.agents import BackgroundAudioPlayer, AudioConfig, BuiltinAudioClip
from livekit.agents.llm import ChatMessage
from context import CONTEXT
from datetime import datetime
from livekit import rtc
import re
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
import re

logger = logging.getLogger("mayfairtech-voice-agent")
load_dotenv(dotenv_path=".env")

if not hasattr(RunContext, "session_data"):
    RunContext.session_data = {}
# Contact form schema
FORM_SCHEMA = {
    "name": "Full Name",
    "email": "Email Address",
    "phone": "Phone Number (optional)",
    "subject": "Subject",
    "message": "Message",
}

CONTACT_INFO = {
    "address": "123 Innovation Avenue, Karachi, Pakistan",
    "phone": "+92 21 3567 8910",
    "email": "support@mayfairtech.ai",
    "office_hours": "Mon–Fri: 9:00 AM – 6:00 PM, Sat: 10:00 AM – 2:00 PM, Sun: Closed",
}

UPSELL_MAP = {
        "smartphones": ["Screen Protector", "Phone Case", "Wireless Charger"],
        "laptops": ["Laptop Bag", "Wireless Mouse", "Cooling Pad"],
        "headphones": ["Carrying Case", "Audio Cable", "Extra Ear Cushions"],
        "smartwatches": ["Extra Straps", "Screen Guard", "Wireless Charger"],
        "smart_home": ["Smart Bulb", "Smart Plug"],
        "accessories": ["USB-C Cable", "Portable Power Bank"],
}

PRODUCTS = {
    "smartphones": {
        "Apple": [
            {"model": "iPhone 15 Pro", "colors": ["Black", "Silver"], "price": 1200},
            {"model": "iPhone 14", "colors": ["Blue", "Midnight"], "price": 900},
        ],
        "Samsung": [
            {"model": "Galaxy S23", "colors": ["Black", "Green"], "price": 1000},
            {"model": "Galaxy A54", "colors": ["White", "Black"], "price": 500},
        ],
        "Nokia": [
            {"model": "Nokia G50", "colors": ["Blue", "Midnight Sun"], "price": 350},
            {"model": "Nokia X20", "colors": ["Nordic Blue"], "price": 400},
        ],
        "Oppo": [
            {"model": "Oppo Reno 8", "colors": ["Black", "Gold"], "price": 550},
            {"model": "Oppo A57", "colors": ["Green", "Black"], "price": 250},
        ],
        "Realme": [
            {"model": "Realme 10 Pro", "colors": ["Blue", "Black"], "price": 400},
            {"model": "Realme C55", "colors": ["Yellow", "Black"], "price": 200},
        ],
        "Honor": [
            {"model": "Honor 90", "colors": ["Emerald Green", "Black"], "price": 500},
            {"model": "Honor X8", "colors": ["Silver", "Black"], "price": 300},
        ],
    },

    "laptops": {
        "Apple": [
            {"model": "MacBook Air M2", "colors": ["Gray", "Silver"], "price": 1500},
            {"model": "MacBook Pro 14", "colors": ["Silver"], "price": 2200},
        ],
        "Dell": [
            {"model": "XPS 13", "colors": ["Silver"], "price": 1400},
            {"model": "Inspiron 15", "colors": ["Black"], "price": 800},
        ],
        "HP": [
            {"model": "HP Pavilion 15", "colors": ["Silver"], "price": 750},
            {"model": "HP Spectre x360", "colors": ["Black"], "price": 1600},
        ],
        "Lenovo": [
            {"model": "ThinkPad X1 Carbon", "colors": ["Black"], "price": 1700},
            {"model": "IdeaPad 3", "colors": ["Gray"], "price": 600},
        ],
        "Huawei": [
            {"model": "MateBook D15", "colors": ["Gray"], "price": 900},
            {"model": "MateBook X Pro", "colors": ["Silver"], "price": 1800},
        ],
    },

    "headphones": {
        "Sony": [
            {"model": "WH-1000XM5", "colors": ["Black", "Silver"], "price": 400},
            {"model": "WF-C700N (Earbuds)", "colors": ["Black", "White"], "price": 120},
        ],
        "Apple": [
            {"model": "AirPods Pro 2", "colors": ["White"], "price": 250},
            {"model": "AirPods Max", "colors": ["Gray", "Pink"], "price": 600},
        ],
        "Audionic": [
            {"model": "Audionic Airbud 550", "colors": ["Black"], "price": 40},
            {"model": "Audionic Blue Beats B-747", "colors": ["Blue"], "price": 30},
        ],
    },

    "smartwatches": {
        "Apple": [
            {"model": "Apple Watch Series 9", "colors": ["Black", "Pink"], "price": 450},
            {"model": "Apple Watch SE", "colors": ["Silver", "White"], "price": 300},
        ],
        "Samsung": [
            {"model": "Galaxy Watch 6", "colors": ["Black", "Silver"], "price": 350},
            {"model": "Galaxy Watch 5 Pro", "colors": ["Gray"], "price": 400},
        ],
        "Huawei": [
            {"model": "Huawei Watch GT 3", "colors": ["Brown", "Black"], "price": 280},
            {"model": "Huawei Watch Fit", "colors": ["Pink", "Black"], "price": 150},
        ],
        "Amazfit": [
            {"model": "Amazfit GTS 4", "colors": ["Black", "Gold"], "price": 200},
            {"model": "Amazfit Bip 3", "colors": ["Blue", "Black"], "price": 80},
        ],
    },

    "smart_home": {
        "Google": [
            {"model": "Nest Hub", "colors": ["White", "Charcoal"], "price": 100},
            {"model": "Nest Mini", "colors": ["Gray", "Black"], "price": 50},
        ],
        "Amazon": [
            {"model": "Echo Dot 5th Gen", "colors": ["Black", "Blue"], "price": 60},
            {"model": "Echo Show 8", "colors": ["White", "Black"], "price": 120},
        ],
        "Xiaomi": [
            {"model": "Mi Smart Speaker", "colors": ["Black", "White"], "price": 80},
            {"model": "Mi Smart Clock", "colors": ["White"], "price": 60},
        ],
    },
    
    "accessories": {
        "Belkin": [
            {"model": "Wireless Charger", "colors": ["White"], "price": 50},
            {"model": "MagSafe 3-in-1 Dock", "colors": ["Black"], "price": 120},
        ],
        "Logitech": [
            {"model": "MX Master 3S Mouse", "colors": ["Black"], "price": 100},
            {"model": "K380 Wireless Keyboard", "colors": ["Blue", "White"], "price": 40},
        ],
        "Audionic": [
            {"model": "Power Bank 10000mAh", "colors": ["Black"], "price": 25},
            {"model": "Bluetooth Speaker Alien-2", "colors": ["Red", "Black"], "price": 45},
        ],
        "Generic": [
            {"model": "Screen Protector", "colors": ["Transparent"], "price": 10},
            {"model": "Phone Case", "colors": ["Black", "Blue", "Red"], "price": 20},
            {"model": "Laptop Bag", "colors": ["Black", "Gray"], "price": 40},
            {"model": "Cooling Pad", "colors": ["Black"], "price": 25},
            {"model": "Carrying Case", "colors": ["Black"], "price": 15},
            {"model": "Extra Ear Cushions", "colors": ["Black"], "price": 10},
            {"model": "Extra Straps", "colors": ["Black", "White", "Pink"], "price": 15},
            {"model": "Screen Guard", "colors": ["Transparent"], "price": 8},
            {"model": "Smart Bulb", "colors": ["White"], "price": 25},
            {"model": "Smart Plug", "colors": ["White"], "price": 30},
            {"model": "USB-C Cable", "colors": ["White", "Black"], "price": 12},
            {"model": "Portable Power Bank", "colors": ["Black"], "price": 35},
        ]
    },
}

SHIPPING_COUNTRIES = {
    "Pakistan": 0.00,
    "United States": 0.15,
    "USA": 0.15,
    "United Kingdom": 0.12,
    "UK": 0.12,
    "UAE": 0.10,
    "United Arab Emirates": 0.10,
    "Germany": 0.14,
    "India": 0.08,
    "Canada": 0.16,
}

AMBIENT_AUDIO_FILES = [
    "audio/ambience1.mp3",
    "audio/ambience2.mp3",
    "audio/ambience3.mp3",
    "audio/ambience4.mp3",
    "audio/ambience5.mp3",
    "audio/ambience6.mp3",
    "audio/ambience7.mp3",
    # ... up to 10–15
]

LOG_FILE = "session_summary.json"


# ====== Pydantic models for the Agent ======
class OrderRequest(BaseModel):
    """
    Structured order request. All fields validated.
    note: category will be normalized to lowercase to match PRODUCTS keys.
    """
    name: str
    email: EmailStr
    category: str
    brand: str
    model: str
    color: Optional[str] = None
    quantity: int
    country: str  # shipping destination (must be in SHIPPING_COUNTRIES)
    city: Optional[str] = None

    # validate category exists (normalize to lowercase)
    @validator("category")
    def _valid_category(cls, v):
        if not v:
            raise ValueError("Category is required.")
        cat = v.lower()
        if cat not in PRODUCTS:
            raise ValueError(f"Unknown category '{v}'. Available: {', '.join(PRODUCTS.keys())}")
        return cat

    @validator("brand")
    def _valid_brand(cls, v, values):
        cat = values.get("category")
        if not cat:
            raise ValueError("Category must be provided before brand.")
        brands = PRODUCTS[cat].keys()
        match = next((b for b in brands if b.lower() == v.lower()), None)
        if not match:
            raise ValueError(f"Brand '{v}' not found in category '{cat}'. Available: {', '.join(brands)}")
        return match  # canonical brand

    @validator("model")
    def _valid_model(cls, v, values):
        cat = values.get("category")
        brand = values.get("brand")
        if not (cat and brand):
            raise ValueError("Category and brand must be set before model.")
        items = PRODUCTS[cat][brand]
        match = next((it for it in items if it["model"].lower() == v.lower()), None)
        if not match:
            raise ValueError(f"Model '{v}' not found under {brand}. Available: {', '.join([it['model'] for it in items])}")
        return match["model"]  # canonical model string

    @validator("color")
    def _valid_color(cls, v, values):
        if v is None:
            return None
        cat = values.get("category")
        brand = values.get("brand")
        model = values.get("model")
        if not (cat and brand and model):
            raise ValueError("category/brand/model must be provided before color.")
        items = PRODUCTS[cat][brand]
        item = next((it for it in items if it["model"] == model), None)
        if not item:
            raise ValueError("Product not found for color validation.")
        colors = item.get("colors", [])
        match = next((c for c in colors if c.lower() == v.lower()), None)
        if not match:
            raise ValueError(f"Color '{v}' not available for {brand} {model}. Available: {', '.join(colors)}")
        return match  # canonical color

    @validator("quantity")
    def _valid_quantity(cls, v):
        if v is None or v < 1:
            raise ValueError("Quantity must be a positive integer (>=1).")
        return v

    @validator("country")
    def _valid_country(cls, v):
        if not v:
            raise ValueError("Country is required for shipping.")
        # canonicalize against SHIPPING_COUNTRIES keys (case-insensitive)
        match = next((k for k in SHIPPING_COUNTRIES.keys() if k.lower() == v.lower()), None)
        if not match:
            raise ValueError(f"Shipping not available to '{v}'. Supported: {', '.join(SHIPPING_COUNTRIES.keys())}")
        return match  # canonical country key


class ConfirmOrderRequest(BaseModel):
    """
    For confirming or cancelling a pending order.
    If order_id omitted, the function will look in context.session_data['pending_order'].
    """
    order_id: Optional[str] = None
    confirm: bool = True


class ComplaintModel(BaseModel):
    name: str
    email: EmailStr
    order_id: Optional[str]
    complaint: str

    @validator("complaint")
    def complaint_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Complaint cannot be empty")
        return v

#  ------------------------- Helper functions ----------------------------------

def _find_product_entry(category: str, brand: str, model: str):
    """
    Returns the product dict for the given category/brand/model (canonical).
    Case-insensitive matching for brand/model.
    """
    cat = category.lower()
    if cat not in PRODUCTS:
        return None
    # find canonical brand
    brand_map = PRODUCTS[cat]
    matched_brand = next((b for b in brand_map.keys() if b.lower() == brand.lower()), None)
    if not matched_brand:
        return None
    # find model
    items = brand_map[matched_brand]
    matched_item = next((it for it in items if it["model"].lower() == model.lower()), None)
    return (matched_brand, matched_item) if matched_item else None


# small send-email helper (use your existing send_email function if present)
def send_email(to_email: str, subject: str, body: str) -> bool:
    """
    Simple SMTP-based sender. Uses EMAIL_USER and EMAIL_APP_PASSWORD from env (.env).
    Returns True if send succeeded, False otherwise.
    """
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    sender = os.getenv("EMAIL_USER")
    pwd = os.getenv("EMAIL_APP_PASSWORD")
    if not sender or not pwd:
        logger.warning("Email credentials not set; skipping email send.")
        return False

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, pwd)
            server.send_message(msg)
        logger.info(f"Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

async def rotate_ambience(background_audio, interval=180):
    """Randomly rotate ambience every `interval` seconds."""
    while True:
        new_file = random.choice(AMBIENT_AUDIO_FILES)
        print(f"🔊 Switching ambience to {new_file}")
        await background_audio.set_ambient(AudioConfig(new_file, volume=0.6))
        await asyncio.sleep(interval)

def save_complaint(data: ComplaintModel):
    """Save complaint to file"""
    record = {
        "name": data.name,
        "email": data.email,
        "order_id": data.order_id or "N/A",
        "complaint": data.complaint,
        "timestamp": datetime.utcnow().isoformat(),
    }
    with open("complaints.json", "a", encoding="utf-8") as f:
        json.dump(record, f)
        f.write("\n")
    return record

# ----------------------------------- AGENT CLASS -----------------------------------


class MayfairTechAgent(Agent):
    def __init__(self, voice: str = "cedar") -> None:
        stt = openai.STT(
            model="gpt-4o-transcribe",
            language="en",
            prompt="ALways transcribe in English or Urdu",
        )
        llm_inst = openai.LLM(model="gpt-4o")
        tts = openai.TTS(model="gpt-4o-mini-tts", voice=voice)
        silero_vad = silero.VAD.load()

        super().__init__(
            instructions=(f""" {CONTEXT}"""),
            stt=stt,
            llm=llm_inst,
            tts=tts,
            vad=silero_vad,
            allow_interruptions=True,
        )

    # ------------------ FLOW 1: Company Info ------------------
    @function_tool()
    async def get_company_info(self, query: str, context: RunContext) -> str:
        """
        Retrieves only the relevant company information section from about_company.md
        by letting the LLM select the best-matching Question, then returning the full Q/A.

        Args:
            query (str): The user's query related to the company.
            context (RunContext): The current run context for the agent.

        Returns:
            str: The most relevant Q/A pair from the company information markdown file.
        """

        fileloc = Path("info/")
        filenam = "about_company.md"

        with open(fileloc / filenam, "r", encoding="utf-8") as f:
            markdown_text = f.read()

        # --- Split into Q/A pairs ---
        sections = re.split(r"(## Q\d+:.*)", markdown_text)
        qa_pairs = {}
        for i in range(1, len(sections), 2):
            question = sections[i].strip()
            answer = sections[i + 1].strip() if i + 1 < len(sections) else ""
            qa_pairs[question] = answer

        # --- Just give questions to the LLM ---
        questions_only = "\n".join(list(qa_pairs.keys()))
        logger.info(f"Question list: {questions_only}")

        llm_prompt = f"""
        A user asked: "{query}"

        Here are the possible questions from the company info:

        {questions_only}

        Please return ONLY the most relevant question from the list above. 
        Do not return the answer, just the question as written.
        """

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a selector system."},
                {"role": "user", "content": llm_prompt},
            ],
            max_tokens=100,
        )

        selected_question = response.choices[0].message.content.strip()

        # --- Get the matching answer ---
        answer = qa_pairs.get(
            selected_question, "Sorry, I couldn’t find relevant company info."
        )

        result = f"{selected_question}\n{answer}"
        logger.info(f"Selected QA Pair: {result}")

        return result

    # ------------------ FLOW 2: Leadership Team ------------------
    @function_tool()
    async def get_leadership_team(self, context: RunContext) -> str:
        """
        Retrieves information about the leadership team from a markdown file.

        This function reads the contents of 'LeaderShipTeam.md' located in the 'Knowledge repo' directory and returns it as a string.

        Args:
            context (RunContext): The current run context for the agent.

        Returns:
            str: The contents of the leadership team markdown file.
        """
        logger.info("-------------------------------------")
        logger.info("Tool calling (Get Leader Info):")
        logger.info("-------------------------------------")
        fileloc = Path("info/")
        filenam = "leadership_team.md"
        with open(fileloc / filenam, "r", encoding="utf-8") as f:
            markdown_text = f.read()
        return markdown_text

    # ------------------ FLOW 3: Customer Support ------------------
    # @function_tool()
    # async def get_contact_info(self, context: RunContext, field: str = None) -> str:
    @function_tool()
    async def get_contact_info(
        self, context: RunContext, field: Optional[str] = None
    ) -> str:
        """
        Retrieves contact information.
        Args:
            field (str): 'phone', 'email', 'address', or 'office_hours'
        """
        logger.info("-------------------------------------")
        logger.info("Tool calling (Get Contact Info):")
        logger.info("-------------------------------------")

        if field and field in CONTACT_INFO:
            logger.info(CONTACT_INFO[field])
            return CONTACT_INFO[field]
        return CONTACT_INFO

    # ------------------ FLOW 4: Order Tracking ------------------
    @function_tool()
    async def track_order_status(self, order_id: str, context: RunContext) -> str:
        """
        Handles order tracking/status queries from the user.
        Asks for order ID, looks it up in a mapping, and returns status.
        If order ID is not found, return a random fallback status (not 'Delivered').

        Args:
            order_id (str): The order ID provided by the user, like "ORD123".
        Returns:
            str: The order's current status.
        """
        import random

        ORDER_STATUS = {
            "ORD123": "In Packaging",
            "ORD456": "In Transit",
            "ORD789": "Out for Delivery",
            "ORD321": "Pending Confirmation",
            "ORD654": "Processing",
            "ORD987": "Awaiting Pickup",
        }

        logger.info("-------------------------------------")
        logger.info(f"Tool calling (Track Order Status), order_id={order_id}")
        logger.info("-------------------------------------")

        if not order_id:
            return "Please provide your order ID so I can track it for you."

        order_id = order_id.strip().upper()
        status = ORDER_STATUS.get(order_id)

        if status:
            response = f"Order **{order_id}** is currently: **{status}**."
        else:
            response = f"❌ Sorry, I couldn’t find any order with ID **{order_id}**. Please check if it’s correct."

        logger.info(f"Order Response: {response}")
        return response

    # ------------------ FLOW 5: Browsing Products ------------------
    @function_tool()
    async def browse_products(
        self, 
        context: RunContext, 
        category: Optional[str] = None, 
        brand: Optional[str] = None, 
        color: Optional[str] = None, 
        max_price: Optional[float] = None
    ) -> str:
        """
        Allows the user to browse available products by category, brand, color, and price range.

        Situations:
            - When the user asks general product queries: "What gadgets do you have?"
            - When the user asks specific queries: "Show me Apple smartphones under $1000 in black."
            - When the user wants to filter by category, brand, color, or budget.

        Args:
            category (str, optional): Product category (e.g., 'smartphones', 'laptops').
            brand (str, optional): Brand name (e.g., 'Apple', 'Samsung').
            color (str, optional): Preferred color (e.g., 'Black', 'Silver').
            max_price (float, optional): Maximum budget for filtering results.

        Returns:
            str: A list of matching products, or suggestions if no exact match is found.
        """
        logger.info(
            f"Browsing products | category={category}, brand={brand}, color={color}, max_price={max_price}"
        )

        results = []
        categories = PRODUCTS.keys()

        # If category is specified, filter within it
        search_categories = [category.lower()] if category and category.lower() in categories else categories

        for cat in search_categories:
            for brand_name, items in PRODUCTS[cat].items():
                if brand and brand.lower() != brand_name.lower():
                    continue
                for item in items:
                    if color and color.lower() not in [c.lower() for c in item["colors"]]:
                        continue
                    if max_price and item["price"] > max_price:
                        continue
                    results.append(
                        f"{brand_name} {item['model']} "
                        f"(Colors: {', '.join(item['colors'])}, Price: ${item['price']})"
                    )

        if results:
            return "Here are the products matching your search:\n- " + "\n- ".join(results)
        else:
            return (
                "No exact matches found. You can explore these categories instead:\n"
                + ", ".join(categories)
            )
    
    # ------------------ FLOW 6: Placing Orders ------------------
    @function_tool()
    async def place_order(self, context: RunContext, order: OrderRequest) -> dict:
        """
        Situation:
            Called when user provides order details (name, email, category, brand, model, color, quantity, country).
            This returns an order preview and requires explicit confirmation to finalize.
        Args:
            context (RunContext): conversation context
            order (OrderRequest): validated order request
        Returns:
            dict: {
                "order_id": str,
                "summary": str,
                "base_price": float,
                "subtotal": float,
                "surcharge": float,
                "total": float,
                "requires_confirmation": True
            }
        """
        logger.info(f"Placing order preview for {order.name} | {order.brand} {order.model} x{order.quantity}")

        # get product entry (should exist thanks to validators)
        entry = _find_product_entry(order.category, order.brand, order.model)
        if not entry:
            msg = "Internal error: product not found."
            logger.error(msg)
            return {"error": msg}

        _, product = entry
        base_price = float(product["price"])
        subtotal = base_price * order.quantity

        surcharge_pct = SHIPPING_COUNTRIES.get(order.country, 0.0)
        surcharge_amount = round(subtotal * surcharge_pct, 2)
        total = round(subtotal + surcharge_amount, 2)

        order_id = f"ORD{random.randint(10000, 99999)}"

        summary_lines = [
            f"Order Preview (ID: {order_id})",
            f"Customer: {order.name} <{order.email}>",
            f"Product: {order.brand} {order.model} ({order.color or 'default'})",
            f"Quantity: {order.quantity}",
            f"Unit price: ${base_price}",
            f"Subtotal: ${subtotal}",
            f"Shipping to: {order.city or ''} {order.country}",
            f"Shipping surcharge: {int(surcharge_pct*100)}% (${surcharge_amount})",
            f"Total: ${total}",
            "",
            "Please confirm to finalize the order."
        ]
        summary = "\n".join(summary_lines)

        # save pending order in session (until user confirms)
        context.session_data["pending_order"] = {
            "id": order_id,
            "request": order.model_dump(),  # pydantic -> dict
            "base_price": base_price,
            "subtotal": subtotal,
            "surcharge": surcharge_amount,
            "total": total,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Pending order saved: {order_id}")

        return {
            "order_id": order_id,
            "summary": summary,
            "base_price": base_price,
            "subtotal": subtotal,
            "surcharge": surcharge_amount,
            "total": total,
            "requires_confirmation": True,
        }


    # ------------------ FLOW 7: Confirming Order ------------------
    @function_tool()
    async def confirm_order(self, context: RunContext, request: ConfirmOrderRequest) -> str:
        """
        Situation:
            Called when user confirms/cancels the previewed order.
        Args:
            context (RunContext): conversation context
            request (ConfirmOrderRequest): {order_id (optional), confirm: bool}
        Returns:
            str: final confirmation message (and will send receipt email if confirmed)
        """
        pending = None
        if request.order_id:
            # prefer provided id (but still validate it matches stored pending if any)
            pending_all = context.session_data.get("pending_order")
            if pending_all and pending_all.get("id") == request.order_id:
                pending = pending_all
        else:
            pending = context.session_data.get("pending_order")

        if not pending:
            logger.warning("No pending order found to confirm/cancel.")
            return "❌ No pending order found. Please create an order first."

        if not request.confirm:
            # cancel pending order
            context.session_data.pop("pending_order", None)
            logger.info(f"Pending order {pending['id']} cancelled by user.")
            return f"❌ Order {pending['id']} cancelled as requested."

        # finalize
        order_id = pending["id"]
        ORDERS[order_id] = {
            **pending,
            "status": "confirmed",
            "confirmed_at": datetime.utcnow().isoformat(),
        }

        # attempt to send receipt
        req = pending["request"]
        customer_email = req.get("email")
        receipt_body = (
            f"Thank you {req.get('name')}!\n\n"
            f"Your order {order_id} has been confirmed.\n\n"
            f"Item: {req.get('brand')} {req.get('model')} ({req.get('color') or 'default'})\n"
            f"Quantity: {req.get('quantity')}\n"
            f"Total paid: ${pending['total']}\n\n"
            "We'll notify you when your order ships.\n\n"
            "— MayfairTech Sales"
        )
        sent = send_email(customer_email, f"Receipt for {order_id}", receipt_body)
        if sent:
            logger.info(f"Receipt sent for order {order_id} to {customer_email}")
        else:
            logger.warning(f"Receipt NOT sent for order {order_id} to {customer_email}")

        # remove pending
        context.session_data.pop("pending_order", None)

        return f"✅ Order {order_id} confirmed! A receipt has been sent to {customer_email if sent else 'your email (failed to send)'}."

    # -------------------- FLOW 8: Upselling Products -------------------
    @function_tool()
    async def upsell(self, item: str, context: RunContext) -> str:
        """
        Suggests related products for upselling and updates the order preview
        if the user accepts.
        """
        suggestion_list = UPSELL_MAP.get(item, None)

        if not suggestion_list:
            return f"No related upsells found for {item}."

        # Collect only upsells that exist in PRODUCTS["accessories"]
        valid_suggestions = []
        for suggestion in suggestion_list:
            for brand, models in PRODUCTS["accessories"].items():
                for m in models:
                    if m["model"].lower() == suggestion.lower():
                        valid_suggestions.append(m)

        if not valid_suggestions:
            return f"No related upsells found for {item}."

        # If we already have an order preview in session, attach upsell suggestion
        if "order_preview" not in context.session_data:
            context.session_data["order_preview"] = {"items": [], "total": 0}

        # Build suggestion text for user
        suggestion_text = ", ".join([m["model"] for m in valid_suggestions])

        # Store available upsells in session so next user message can be matched
        context.session_data["pending_upsells"] = valid_suggestions

        return (
            f"💡 Many customers who bought {item} also added {suggestion_text}. "
            "Would you like to include one of these in your order?"
        )

    # -------------------- FLOW 9: Updating Order after Upselling Products -------------------
    @function_tool()
    async def add_upsell_to_order(self, upsell_item: str, context: RunContext) -> str:
        """
        Adds the selected upsell product into the current order preview.
        """
        upsells = context.session_data.get("pending_upsells", [])
        order = context.session_data.get("order_preview", {"items": [], "total": 0})

        match = None
        for u in upsells:
            if upsell_item.lower() in u["model"].lower():
                match = u
                break

        if not match:
            return f"Sorry, I couldn’t find {upsell_item} in available upsell options."

        # Add upsell item
        order["items"].append({"model": match["model"], "price": match["price"], "qty": 1})
        order["total"] += match["price"]

        # Update session
        context.session_data["order_preview"] = order
        context.session_data.pop("pending_upsells", None)  # clear after adding

        return (
            f"✅ Added {match['model']} (${match['price']}) to your order. "
            f"Your updated total is now ${order['total']}."
        )
   

    # -------------------- FLOW 10: Registering Complaints -------------------
    @function_tool()
    async def register_complaint(
        self,
        complaint: ComplaintModel,
        context: RunContext,
        confirm: Optional[bool] = False,
    ) -> str:
        """
        Register a customer complaint.
        Args:
            complaint (ComplaintModel): Validated complaint info.
            confirm (bool): If False, show preview. If True, save and send emails.
        """

        # Step 1: Preview if not confirmed
        if not confirm:
            preview = (
                f"📝 Complaint Preview:\n\n"
                f"Name: {complaint.name}\n"
                f"Email: {complaint.email}\n"
                f"Order ID: {complaint.order_id or 'N/A'}\n"
                f"Complaint: {complaint.complaint}\n\n"
                f"✅ Please confirm if you want to register this complaint."
            )
            return preview

        # Step 2: Save complaint
        record = save_complaint(complaint)

        # Step 3: Send emails
        body = (
            f"Dear {complaint.name},\n\n"
            f"Your complaint has been registered successfully.\n\n"
            f"Details:\n"
            f"Order ID: {complaint.order_id or 'N/A'}\n"
            f"Complaint: {complaint.complaint}\n\n"
            f"Our support team will contact you soon.\n\n"
            f"Best Regards,\nCustomer Support"
        )

        user_sent = send_email(complaint.email, "Complaint Registered", body)
        company_sent = send_email(COMPANY_COMPLAINT_EMAIL, f"New Complaint from {complaint.name}", body)

        if user_sent and company_sent:
            return "✅ Your complaint has been registered and a copy has been sent to your email and our support team."
        elif user_sent:
            return "⚠️ Complaint registered and sent to you, but failed to notify support."
        elif company_sent:
            return "⚠️ Complaint registered and sent to support, but failed to send copy to your email."
        else:
            return "⚠️ Complaint registered locally, but email sending failed."
    


# ------------------ AGENT LIFECYCLE ------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        min_endpointing_delay=0.9,
        max_endpointing_delay=5.0,
    )

    agent = MayfairTechAgent()
    usage_collector = metrics.UsageCollector()

    # Store conversation in memory
    conversation_log = []

    # --- Collect from session (AgentMetrics)
    @session.on("metrics_collected")
    def on_agent_metrics(agent_metrics: metrics.AgentMetrics):
        usage_collector.collect(agent_metrics)

    # --- Collect directly from engines
    @agent.llm.on("metrics_collected")
    def on_llm_metrics(llm_metrics: metrics.LLMMetrics):
        usage_collector.collect(llm_metrics)

    @agent.stt.on("metrics_collected")
    def on_stt_metrics(stt_metrics: metrics.STTMetrics):
        usage_collector.collect(stt_metrics)

    @agent.tts.on("metrics_collected")
    def on_tts_metrics(tts_metrics: metrics.TTSMetrics):
        usage_collector.collect(tts_metrics)

    # --- Capture conversation turns (FIXED)
    @session.on("user_message")
    def on_user_message(msg):
        if msg.text.strip():
            conversation_log.append(
                {
                    "role": "user",
                    "text": msg.text,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

    @session.on("assistant_message")
    def on_assistant_message(msg):
        if msg.text.strip():
            conversation_log.append(
                {
                    "role": "assistant",
                    "text": msg.text,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

    # --- Track call lifecycle
    @ctx.room.on("participant_connected")
    def on_connected(remote: rtc.RemoteParticipant):
        print("participant connected")
        ctx.call_start = datetime.utcnow()
        print("-------- Call Started -------", ctx.call_start)

    @ctx.room.on("participant_disconnected")
    def on_finished(remote: rtc.RemoteParticipant):
        call_start = getattr(ctx, "call_start", None)
        call_end = datetime.utcnow()

        if call_start:
            duration_minutes = (call_end - call_start).total_seconds() / 60.0
        else:
            duration_minutes = 0.0

        summary = usage_collector.get_summary()
        summary_dict = summary.__dict__ if hasattr(summary, "__dict__") else summary

        record = {
            "session_id": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
            "metrics": summary_dict,
            "duration_minutes": duration_minutes,
            "conversation": conversation_log,
        }

        # Append to JSON file (NDJSON style, one session per line)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")

        print("✅ Record saved to JSON:", record["session_id"])

    # --- Start the session
    ctx.call_start = datetime.utcnow()
    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(),
    )

    # # --- Background ambience + thinking sounds
    # background_audio = BackgroundAudioPlayer(
    #     ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.6),
    #     thinking_sound=[
    #         AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.7),
    #         AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.6),
    #     ],
    # )
    # await background_audio.start(room=ctx.room, agent_session=session)

    background_audio = BackgroundAudioPlayer(
        ambient_sound=AudioConfig(random.choice(AMBIENT_AUDIO_FILES), volume=0.6),
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.7),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.6),
        ],
    )

    await background_audio.start(room=ctx.room, agent_session=session)

    # Start background rotation loop
    asyncio.create_task(rotate_ambience(background_audio, interval=180))

    # --- Greeting
    await session.say("Hi, I’m your MayfairTech Assistant! How can I help you today?")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )


# okay so this is the code currently, now what i want is that once the form is submitted the user is emailed about this as well, so we can send an email (for now from a set gmail address) to user's email address
