import logging
import asyncio
from livekit import api  # <-- Add this import (LiveKit server-side SDK)
from livekit.plugins import noise_cancellation
from livekit.api import DeleteRoomRequest
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
from datetime import datetime, timedelta
from livekit import rtc
import re
from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional
import re

logger = logging.getLogger("mayfairtech-voice-agent")
load_dotenv(dotenv_path=".env")

if not hasattr(RunContext, "session_data"):
    RunContext.session_data = {}

SESSION_DURATION_MINUTES = 25  # session limit

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
            {
                "model": "Apple Watch Series 9",
                "colors": ["Black", "Pink"],
                "price": 450,
            },
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
            {
                "model": "K380 Wireless Keyboard",
                "colors": ["Blue", "White"],
                "price": 40,
            },
        ],
        "Audionic": [
            {"model": "Power Bank 10000mAh", "colors": ["Black"], "price": 25},
            {
                "model": "Bluetooth Speaker Alien-2",
                "colors": ["Red", "Black"],
                "price": 45,
            },
        ],
        "Generic": [
            {"model": "Screen Protector", "colors": ["Transparent"], "price": 10},
            {"model": "Phone Case", "colors": ["Black", "Blue", "Red"], "price": 20},
            {"model": "Laptop Bag", "colors": ["Black", "Gray"], "price": 40},
            {"model": "Cooling Pad", "colors": ["Black"], "price": 25},
            {"model": "Carrying Case", "colors": ["Black"], "price": 15},
            {"model": "Extra Ear Cushions", "colors": ["Black"], "price": 10},
            {
                "model": "Extra Straps",
                "colors": ["Black", "White", "Pink"],
                "price": 15,
            },
            {"model": "Screen Guard", "colors": ["Transparent"], "price": 8},
            {"model": "Smart Bulb", "colors": ["White"], "price": 25},
            {"model": "Smart Plug", "colors": ["White"], "price": 30},
            {"model": "USB-C Cable", "colors": ["White", "Black"], "price": 12},
            {"model": "Portable Power Bank", "colors": ["Black"], "price": 35},
        ],
    },
}

SHIPPING_COUNTRIES = {
    "Pakistan": 0.00,
    "United States": 0.15,
    "United Kingdom": 0.12,
    "UK": 0.12,
    "UAE": 0.10,
    "United Arab Emirates": 0.10,
    "Germany": 0.14,
    "India": 0.08,
    "Canada": 0.16,
}

ORDERS = {}


LOG_FILE = "session_summary.json"

import re


#  ------------------------- Models ---------------------------------------------
class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str | None = None
    subject: str
    message: str

    # --- Validators ---
    @field_validator("name")
    def validate_name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be empty.")
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters long.")
        return v.strip()

    @field_validator("phone")
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        pattern = re.compile(r"^\+?[0-9\s\-]{7,15}$")
        if not pattern.match(v):
            raise ValueError("Invalid phone number format.")
        return v.strip()

    @field_validator("subject")
    def validate_subject(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Subject cannot be empty.")
        if len(v) < 3:
            raise ValueError("Subject must be at least 3 characters long.")
        return v.strip()

    @field_validator("message")
    def validate_message(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message cannot be empty.")
        if len(v) < 10:
            raise ValueError("Message must be at least 10 characters long.")
        return v.strip()


class ComplaintModel(BaseModel):
    name: str
    email: EmailStr
    order_id: Optional[str]
    complaint: str

    @field_validator("complaint")
    def complaint_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Complaint cannot be empty")
        return v


class OrderItem(BaseModel):
    category: str
    brand: str
    model: str
    quantity: int = 1
    color: Optional[str] = None


class OrderRequest(BaseModel):
    name: str
    email: EmailStr
    country: str
    items: list[OrderItem]

    @field_validator("name")
    def validate_name(cls, v):
        if not v.strip().replace(" ", "").isalpha():
            raise ValueError("Name must contain only letters and spaces.")
        return v

    @field_validator("country")
    def validate_country(cls, v):
        # Normalize both to lowercase for comparison
        normalized_v = v.strip().lower()
        valid_countries = {k.lower(): k for k in SHIPPING_COUNTRIES.keys()}

        if normalized_v not in valid_countries:
            raise ValueError(
                f"Sorry, we currently do not ship to '{v}'. "
                f"Available destinations: {', '.join(SHIPPING_COUNTRIES.keys())}"
            )

        # Return the properly formatted name (original from dict)
        return valid_countries[normalized_v]


#  ------------------------- Helper functions ----------------------------------


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


from openai import OpenAI

client = OpenAI()

# ----------------------------------- AGENT CLASS -----------------------------------


class MayfairTechAgent(Agent):
    def __init__(self, voice: str = "cedar") -> None:
        stt = openai.STT(
            model="gpt-4o-transcribe",
            language="en",
            prompt="ALways transcribe in English or Urdu",
        )
        llm_inst = openai.LLM(model="gpt-4.1")
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
        max_price: Optional[float] = None,
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
        search_categories = (
            [category.lower()]
            if category and category.lower() in categories
            else categories
        )

        for cat in search_categories:
            for brand_name, items in PRODUCTS[cat].items():
                if brand and brand.lower() != brand_name.lower():
                    continue
                for item in items:
                    if color and color.lower() not in [
                        c.lower() for c in item["colors"]
                    ]:
                        continue
                    if max_price and item["price"] > max_price:
                        continue
                    results.append(
                        f"{brand_name} {item['model']} "
                        f"(Colors: {', '.join(item['colors'])}, Price: ${item['price']})"
                    )

        if results:
            return "Here are the products matching your search:\n- " + "\n- ".join(
                results
            )
        else:
            return (
                "No exact matches found. You can explore these categories instead:\n"
                + ", ".join(categories)
            )

    # ------------------ FLOW 6: Contact Us Form ------------------
    @function_tool()
    async def contact_company(
        self, context: RunContext, contact: ContactRequest
    ) -> dict:
        """
        Situation:
            Called when the user provides details to contact the company.
            Returns a preview of the contact request and requires explicit confirmation.
        Args:
            context (RunContext): conversation context
            contact (ContactRequest): validated contact request
        Returns:
            dict: {
                "contact_id": str,
                "summary": str,
                "requires_confirmation": True
            }
        """
        logger.info(
            f"Creating contact request preview for {contact.name} <{contact.email}>"
        )

        contact_id = f"CTC{random.randint(10000, 99999)}"

        summary_lines = [
            f"Contact Request Preview (ID: {contact_id})",
            f"Name: {contact.name}",
            f"Email: {contact.email}",
            f"Phone: {contact.phone or 'Not provided'}",
            f"Subject: {contact.subject}",
            f"Message: {contact.message}",
            "",
            "Please confirm to finalize submitting this contact request.",
        ]
        summary = "\n".join(summary_lines)

        # save pending contact in session (until user confirms)
        context.session_data["pending_contact"] = {
            "id": contact_id,
            "request": contact.model_dump(),
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

        logger.info(f"Pending contact request saved: {contact_id}")

        return {
            "contact_id": contact_id,
            "summary": summary,
            "requires_confirmation": True,
        }

    @function_tool()
    async def confirm_contact_request(self, action: str, context: RunContext) -> dict:
        """
        Confirm or cancel the pending contact request, then handle emails if confirmed.

        Args:
            action (str): Either "confirm" or "cancel".
            context (RunContext): The current run context for the agent.

        Returns:
            dict: Result of the operation with status and message.
        """
        pending = context.session_data.get("pending_contact")
        if not pending:
            return {"error": "No pending contact request to process."}

        if action.lower() == "confirm":
            pending["status"] = "confirmed"
            context.session_data["last_contact"] = pending
            context.session_data.pop("pending_contact", None)

            # --- Email Sending ---
            request = pending["request"]
            user_email = request["email"]
            company_email = os.getenv(
                "COMPANY_EMAIL", "syeda.maham.jafri.2024@gmail.com"
            )

            # Email to user
            user_subject = "✅ Your Contact Request Has Been Received"
            user_body = (
                f"Hi {request['name']},\n\n"
                f"Thank you for contacting us regarding '{request['subject']}'. "
                "Our team will review your message and get back to you shortly.\n\n"
                "Best regards,\nMayFairTech"
            )
            send_email(user_email, user_subject, user_body)

            # Email to company
            company_subject = f"📩 New Contact Request from {request['name']}"
            company_body = (
                f"New contact request submitted:\n\n"
                f"Name: {request['name']}\n"
                f"Email: {request['email']}\n"
                f"Phone: {request['phone']}\n"
                f"Subject: {request['subject']}\n"
                f"Message:\n{request['message']}\n\n"
                f"Request ID: {pending['id']}"
            )
            send_email(company_email, company_subject, company_body)

            logger.info(f"Contact request confirmed and emails sent: {pending['id']}")

            return {
                "contact_id": pending["id"],
                "status": "confirmed",
                "message": "Your contact request has been submitted and a confirmation email has been sent.",
            }

        elif action.lower() == "cancel":
            context.session_data.pop("pending_contact", None)
            logger.info("Pending contact request cancelled by user.")
            return {
                "status": "cancelled",
                "message": "Your contact request has been cancelled.",
            }

        else:
            return {"error": "Invalid action. Use 'confirm' or 'cancel'."}

    # -------------------- FLOW 7: Registering Complaints -------------------
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
        user_body = (
            f"Dear {complaint.name},\n\n"
            f"Your complaint has been registered successfully.\n\n"
            f"Details:\n"
            f"Order ID: {complaint.order_id or 'N/A'}\n"
            f"Complaint: {complaint.complaint}\n\n"
            f"Our support team will contact you soon.\n\n"
            f"Best Regards,\nCustomer Support"
        )
        company_body = (
            f"A new complaint has been recieved\n"
            f"Details:\n"
            f"Order ID: {complaint.order_id or 'N/A'}\n"
            f"Complaint: {complaint.complaint}\n\n"
        )

        COMPANY_COMPLAINT_EMAIL = "syeda.maham.jafri.2024@gmail.com"
        user_sent = send_email(complaint.email, "Complaint Registered", user_body)
        company_sent = send_email(
            COMPANY_COMPLAINT_EMAIL,
            f"New Complaint from {complaint.name}",
            company_body,
        )

        if user_sent and company_sent:
            return "✅ Your complaint has been registered and a copy has been sent to your email and our support team."
        elif user_sent:
            return (
                "⚠️ Complaint registered and sent to you, but failed to notify support."
            )
        elif company_sent:
            return "⚠️ Complaint registered and sent to support, but failed to send copy to your email."
        else:
            return "⚠️ Complaint registered locally, but email sending failed."

    # -------------------- FLOW 7: Placing Orders-------------------
    @function_tool()
    async def place_order(self, context: RunContext, request: OrderRequest) -> dict:
        """
        Calls browse_products to check first whether what the user is ordering is available
        Creates or updates an order preview for tech products.
        Checks product & country validity, calculates subtotal, shipping, total cost,
        and saves the preview to session memory for later modification or confirmation.
        """
        subtotal = 0
        upsell_suggestions = []

        # --- Step 1: Normalize and validate country ---
        normalized_country = request.country.strip().title()
        if normalized_country not in SHIPPING_COUNTRIES:
            return {
                "status": "error",
                "message": f"❌ Sorry, we currently do not ship to '{request.country}'. "
                f"Available destinations: {', '.join(SHIPPING_COUNTRIES.keys())}",
            }

        # --- Helper to find product in catalog ---
        def find_product(category, brand, model, color=None):
            category = category.lower()
            if category not in PRODUCTS:
                return None
            for b, items in PRODUCTS[category].items():
                if b.lower() != brand.lower():
                    continue
                for item in items:
                    if item["model"].lower() == model.lower():
                        if color and color.lower() not in [
                            c.lower() for c in item["colors"]
                        ]:
                            continue
                        return item
            return None

        # --- Step 2: Validate requested items ---
        valid_items = []
        missing_items = []
        for item in request.items:
            product = find_product(item.category, item.brand, item.model, item.color)
            if not product:
                missing_items.append(f"{item.brand} {item.model} ({item.category})")
            else:
                valid_items.append((item, product))

        # --- Step 3: Handle unavailable products ---
        if missing_items:
            context.session_data.pop("pending_order", None)
            unavailable_list = "\n- ".join(missing_items)
            suggestions = await self.browse_products(context, category=None)
            return {
                "status": "error",
                "message": (
                    f"❌ The following products are not available:\n"
                    f"- {unavailable_list}\n\n"
                    f"You can explore these instead:\n\n{suggestions}"
                ),
            }

        # --- Step 4: Check for existing pending order ---
        pending = context.session_data.get("pending_order")
        if not pending:
            # Create a new order
            order_id = f"ORD{random.randint(1000, 9999)}"
            items_dict = {}
            for item, product in valid_items:
                subtotal += product["price"] * item.quantity
                items_dict[f"{item.brand} {item.model}"] = item.quantity
                if item.category in UPSELL_MAP:
                    upsell_suggestions.extend(UPSELL_MAP[item.category])

            shipping_rate = SHIPPING_COUNTRIES[normalized_country]
            shipping_cost = subtotal * shipping_rate
            total_cost = subtotal + shipping_cost

            pending = {
                "id": order_id,
                "name": request.name,
                "email": request.email,
                "country": normalized_country,
                "items": items_dict,
                "subtotal": subtotal,
                "shipping_cost": shipping_cost,
                "total": total_cost,
                "status": "Pending Confirmation",
            }
        else:
            # Merge new items into existing order
            for item, product in valid_items:
                key = f"{item.brand} {item.model}"
                existing_qty = pending["items"].get(key, 0)
                pending["items"][key] = existing_qty + item.quantity
                if item.category in UPSELL_MAP:
                    upsell_suggestions.extend(UPSELL_MAP[item.category])

            # --- Recalculate subtotal from scratch (to avoid double-counting) ---
            new_subtotal = 0
            for model_name, qty in pending["items"].items():
                # Find matching product from catalog to get price
                brand, model = model_name.split(" ", 1)
                for category, brands in PRODUCTS.items():
                    if brand in brands:
                        for prod in brands[brand]:
                            if prod["model"].lower() == model.lower():
                                new_subtotal += prod["price"] * qty

            pending["subtotal"] = new_subtotal

            # Recalculate shipping and total
            rate = SHIPPING_COUNTRIES.get(pending["country"], 0)
            pending["shipping_cost"] = pending["subtotal"] * rate
            pending["total"] = pending["subtotal"] + pending["shipping_cost"]
            # for item, product in valid_items:
            #     key = f"{item.brand} {item.model}"
            #     existing_qty = pending["items"].get(key, 0)
            #     pending["items"][key] = existing_qty + item.quantity
            #     pending["subtotal"] += product["price"] * item.quantity
            #     if item.category in UPSELL_MAP:
            #         upsell_suggestions.extend(UPSELL_MAP[item.category])

            # # Recalculate shipping and total
            # rate = SHIPPING_COUNTRIES.get(pending["country"], 0)
            # pending["shipping_cost"] = pending["subtotal"] * rate
            # pending["total"] = pending["subtotal"] + pending["shipping_cost"]

        # Save updated order to session and ORDERS dict
        ORDERS[pending["id"]] = pending
        context.session_data["pending_order"] = pending

        # --- Step 5: Generate summary text ---
        summary_lines = [
            f"🧾 **Order Preview (ID: {pending['id']})**",
            f"Name: {pending['name']}",
            f"Email: {pending['email']}",
            f"Country: {pending['country']}",
            "",
            "📦 **Items Ordered:**",
        ]
        for model, qty in pending["items"].items():
            summary_lines.append(f"- {model}, Qty: {qty}")

        summary_lines.append("")
        summary_lines.append(f"Subtotal: ${pending['subtotal']:.2f}")
        summary_lines.append(f"Shipping: ${pending['shipping_cost']:.2f}")
        summary_lines.append(f"💰 **Total: ${pending['total']:.2f}**")

        if upsell_suggestions:
            summary_lines.append("")
            summary_lines.append("💡 You might also like:")
            for suggestion in upsell_suggestions[:5]:
                summary_lines.append(f"- {suggestion}")

        return {
            "status": "success",
            "order_id": pending["id"],
            "summary": "\n".join(summary_lines),
            "requires_confirmation": True,
        }

    # -------- ADD ITEM TO ORDER -------- #
    @function_tool()
    async def add_item_to_order(
        self,
        context: RunContext,
        category: str,
        brand: str,
        model: str,
        quantity: int = 1,
        color: Optional[str] = None,
    ) -> str:
        """
        Adds an additional item (e.g., from upsell suggestions) to the existing pending order.
        Automatically handles cases where the brand is missing by falling back to 'Generic'.
        Recalculates total (including shipping) after update.
        """
        pending = context.session_data.get("pending_order")
        if not pending:
            return "❌ No active order found to modify."

        # --- Brand fallback ---
        if not brand or brand.strip() == "":
            found_brand = None
            for b_name, items in PRODUCTS.get(category.lower(), {}).items():
                for item in items:
                    if item["model"].lower() == model.lower():
                        found_brand = b_name
                        break
                if found_brand:
                    break
            brand = found_brand or "Generic"

        # --- Find product ---
        def find_product(category, brand, model, color=None):
            category = category.lower()
            if category not in PRODUCTS:
                return None
            for b, items in PRODUCTS[category].items():
                if b.lower() != brand.lower():
                    continue
                for item in items:
                    if item["model"].lower() == model.lower():
                        if color and color.lower() not in [
                            c.lower() for c in item["colors"]
                        ]:
                            continue
                        return item
            return None

        product = find_product(category, brand, model, color)
        if not product:
            return f"❌ Could not find {brand} {model} in our catalog."

        # --- Update pending order ---
        key = f"{brand} {model}"
        existing_qty = pending["items"].get(key, 0)
        pending["items"][key] = existing_qty + quantity
        pending["subtotal"] += product["price"] * quantity

        # Recalculate shipping + total
        shipping_rate = SHIPPING_COUNTRIES.get(pending["country"], 0.00)
        pending["shipping_cost"] = pending["subtotal"] * shipping_rate
        pending["total"] = pending["subtotal"] + pending["shipping_cost"]

        # Save updated order
        ORDERS[pending["id"]] = pending
        context.session_data["pending_order"] = pending

        return (
            f"✅ Added {quantity} × {brand} {model} to your order.\n"
            f"💰 Subtotal: ${pending['subtotal']:.2f}\n"
            f"🚚 Shipping: ${pending['shipping_cost']:.2f}\n"
            f"💵 New Total: ${pending['total']:.2f}"
        )

    # -------- CONFIRM ORDER -------- #
    @function_tool()
    async def confirm_order(self, context: RunContext) -> str:
        """
        Confirms and finalizes the pending order, then sends confirmation emails.
        """
        pending = context.session_data.get("pending_order")
        if not pending:
            return "❌ No pending order found."

        order_date = datetime.now()
        delivery_days = random.randint(3, 10)  # delivery window between 3–10 days
        delivery_date = order_date + timedelta(days=delivery_days)

        items_formatted = "\n".join(
            [f"   • {model} — Qty: {qty}" for model, qty in pending["items"].items()]
        )

        # Store them in the order dict
        pending["order_date"] = order_date.strftime("%B %d, %Y")
        pending["delivery_date"] = delivery_date.strftime("%B %d, %Y")

        pending["status"] = "confirmed"
        ORDERS[pending["id"]] = pending
        context.session_data.pop("pending_order", None)

        msg = (
            f"✅ Order Confirmed!\n\n"
            f"ID: {pending['id']}\n"
            f"Customer: {pending['name']}\n"
            f"Email: {pending['email']}\n"
            f"Country: {pending['country']}\n"
            # f"Items: {pending['items']}\n"
            f"Items Ordered:\n{items_formatted}\n\n"
            f"Subtotal: ${pending['subtotal']:.2f}\n"
            f"Shipping: ${pending['shipping_cost']:.2f}\n"
            f"Total: ${pending['total']:.2f}\n"
            f"Order Placed On: {pending['order_date']}\n"
            f"Estimated Delivery Date: {pending['delivery_date']}\n\n"
            f"Status: Confirmed"
        )

        # Send confirmation to both customer and MayfairTech team
        send_email(pending["email"], "Your Order Confirmation - MayfairTech", msg)
        send_email(
            "syeda.maham.jafri.2024@gmail.com", "New Customer Order Received", msg
        )

        return msg


# ------------------ AGENT LIFECYCLE ------------------
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    # Wait for the first participant
    participant = await ctx.wait_for_participant()
    logger.info(f"Starting voice assistant for participant {participant.identity}")

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        min_endpointing_delay=0.9,
        max_endpointing_delay=5.0,
    )

    agent = MayfairTechAgent()
    usage_collector = metrics.UsageCollector()
    conversation_log = []

    # Collect metrics
    @session.on("metrics_collected")
    def on_agent_metrics(agent_metrics: metrics.AgentMetrics):
        usage_collector.collect(agent_metrics)

    @agent.llm.on("metrics_collected")
    def on_llm_metrics(llm_metrics: metrics.LLMMetrics):
        usage_collector.collect(llm_metrics)

    @agent.stt.on("metrics_collected")
    def on_stt_metrics(stt_metrics: metrics.STTMetrics):
        usage_collector.collect(stt_metrics)

    @agent.tts.on("metrics_collected")
    def on_tts_metrics(tts_metrics: metrics.TTSMetrics):
        usage_collector.collect(tts_metrics)

    # Log conversation turns
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

    # --- Call lifecycle tracking
    @ctx.room.on("participant_connected")
    def on_connected(remote: rtc.RemoteParticipant):
        logger.info("👤 Participant connected.")
        ctx.call_start = datetime.utcnow()
        logger.info(f"-------- Call Started ------- {ctx.call_start}")

    @ctx.room.on("participant_disconnected")
    def on_finished(remote: rtc.RemoteParticipant):
        call_start = getattr(ctx, "call_start", None)
        call_end = datetime.utcnow()
        duration_minutes = (
            (call_end - call_start).total_seconds() / 60.0 if call_start else 0.0
        )

        summary = usage_collector.get_summary()
        record = {
            "session_id": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
            "metrics": summary.__dict__ if hasattr(summary, "__dict__") else summary,
            "duration_minutes": duration_minutes,
            "conversation": conversation_log,
        }

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False)
            f.write("\n")

        logger.info(f"✅ Record saved to JSON: {record['session_id']}")

    # ----- Session Timeout Logic + Room Deletion -----
    async def end_session_after_timeout():
        await asyncio.sleep(SESSION_DURATION_MINUTES * 60)
        logger.warning(
            "⏰ Session time limit reached. Ending session and deleting room..."
        )

        try:
            await session.stop()
            logger.info("🧩 Agent session stopped.")
        except Exception as e:
            logger.error(f"⚠️ Error stopping session: {e}")

        # Disconnect participants
        try:
            for p in list(ctx.room.remote_participants.values()):
                logger.info(f"Disconnecting participant: {p.identity}")
                await p.disconnect()
            logger.info("✅ All participants disconnected.")
        except Exception as e:
            logger.error(f"⚠️ Error disconnecting participants: {e}")

        # Delete the room server-side using LiveKit API
        try:
            lkapi = api.LiveKitAPI(
                url=os.getenv("LIVEKIT_API_URL"),
                api_key=os.getenv("LIVEKIT_API_KEY"),
                api_secret=os.getenv("LIVEKIT_API_SECRET"),
            )
            # Use DeleteRoomRequest per docs
            req = DeleteRoomRequest(room=ctx.room.name)
            await lkapi.room.delete_room(req)
            logger.info(f"💣 Room '{ctx.room.name}' deleted successfully from server.")
        except Exception as e:
            logger.error(f"⚠️ Error deleting room via API: {e}")

        # Disconnect local room connection
        try:
            await ctx.room.disconnect()
            logger.info("🏁 Local room connection closed.")
        except Exception as e:
            logger.error(f"⚠️ Error closing local room connection: {e}")

    # Start background timeout task
    asyncio.create_task(end_session_after_timeout())

    # --- Start agent session
    ctx.call_start = datetime.utcnow()
    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # --- Background ambient sounds
    background_audio = BackgroundAudioPlayer(
        ambient_sound=AudioConfig(BuiltinAudioClip.OFFICE_AMBIENCE, volume=0.6),
        thinking_sound=[
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING, volume=0.7),
            AudioConfig(BuiltinAudioClip.KEYBOARD_TYPING2, volume=0.6),
        ],
    )
    await background_audio.start(room=ctx.room, agent_session=session)

    # --- Initial greeting
    await session.say("Hi, I’m your MayfairTech Assistant! How can I help you today?")


if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )

# --------------------- Sample Conversation between the User and the MayfairTech Agent ------------------------
"""
🥇 1. Get Company Info
   - User: What does MayfairTech do?
     Tool Called: get_company_info(query="What does MayfairTech do?")
     Agent Response:
     MayfairTech is a technology solutions company specializing in AI-driven automation,
     software development, and cloud infrastructure services. We help businesses scale
     through intelligent, data-backed systems.

   - User: Who founded MayfairTech and when?
     Tool Called: get_company_info(query="Who founded MayfairTech and when?")
     Agent Response:
     MayfairTech was founded in 2016 by a team of software engineers and AI researchers.
     The company started as a small tech consultancy and has grown into a global firm
     serving clients across multiple industries.

🥈 2. Leadership Team
   - User: Who are the key leaders at MayfairTech?
     Tool Called: get_leadership_team()
     Agent Response:
     Here’s our leadership team:
     • Sarah Malik – CEO  
     • Hamza Qureshi – CTO  
     • Ayesha Rehman – Head of Marketing  
     • Ali Raza – CFO  

🥉 3. Customer Support (Contact Info)
   - User: How can I reach your support team?
     Tool Called: get_contact_info()
     Agent Response:
     You can reach us at:
     📞 +92 21 3456 7890  
     ✉️ support@mayfairtech.ai  
     🕒 Office Hours: Mon–Fri, 9 AM – 6 PM

   - User: What’s your office address?
     Tool Called: get_contact_info(field="address")
     Agent Response:
     Our main office is located at:
     MayfairTech Pvt. Ltd.  
     22 Innovation Avenue, Karachi, Pakistan.

🏅 4. Order Tracking
   - User: Can you check my order status? My order ID is ORD456.
     Tool Called: track_order_status(order_id="ORD456")
     Agent Response:
     Order **ORD456** is currently: **In Transit**.

   - User: Check order ORD999.
     Tool Called: track_order_status(order_id="ORD999")
     Agent Response:
     ❌ Sorry, I couldn’t find any order with ID **ORD999**. Please check if it’s correct.

🎯 5. Browse Products
   - User: What products do you have?
     Tool Called: browse_products()
     Agent Response:
     Here are the product categories you can explore:
     Smartphones, Laptops, Smartwatches, and Accessories.

   - User: Show me Apple smartphones under $1000 in black.
     Tool Called: browse_products(category="smartphones", brand="Apple", color="Black", max_price=1000)
     Agent Response:
     Here are the products matching your search:
     - Apple iPhone 13 (Colors: Black, Blue, Price: $899)
     - Apple iPhone SE (Colors: Black, Red, Price: $499)

💬 6. Contact Company
   - User: I want to contact you about a product partnership.
     Tool Called: contact_company(contact={
         "name": "Areeba Khan",
         "email": "areeba.khan@example.com",
         "phone": "0321-5678901",
         "subject": "Product Partnership",
         "message": "We’re interested in discussing a collaboration opportunity."
     })
     Agent Response:
     Contact Request Preview (ID: CTC12345)
     Name: Areeba Khan
     Email: areeba.khan@example.com
     Phone: 0321-5678901
     Subject: Product Partnership
     Message: We’re interested in discussing a collaboration opportunity.

     Please confirm to finalize submitting this contact request.

   - User: Yes, please confirm it.
     Tool Called: confirm_contact_request(action="confirm")
     Agent Response:
     Your contact request has been submitted and a confirmation email has been sent to you.

🧾 7. Register Complaint
   - User: I want to report a problem with my order.
     Tool Called: register_complaint(complaint={
         "name": "Ahmed Raza",
         "email": "ahmed.raza@example.com",
         "order_id": "ORD654",
         "complaint": "Received the wrong laptop model."
     })
     Agent Response:
     📝 Complaint Preview:
     Name: Ahmed Raza
     Email: ahmed.raza@example.com
     Order ID: ORD654
     Complaint: Received the wrong laptop model.

     ✅ Please confirm if you want to register this complaint.

   - User: Yes, register it.
     Tool Called: register_complaint(confirm=True)
     Agent Response:
     ✅ Your complaint has been registered and a copy has been sent to your email and our support team.

📦 8. Place Order
   - User: I want to order a Samsung Galaxy S22.
     Tool Called: place_order(request={
         "name": "Sara Khan",
         "email": "sara.khan@example.com",
         "country": "Pakistan",
         "items": [{"category": "smartphones", "brand": "Samsung", "model": "Galaxy S22", "quantity": 1}]
     })
     Agent Response:
     🧾 Order Preview (ID: ORD4321)
     👤 Customer: Sara Khan <sara.khan@example.com>
     🌍 Shipping Destination: Pakistan
     Items Ordered:
       • Samsung Galaxy S22 x1

     💰 Subtotal: $899.00
     🚚 Shipping Cost: $45.00
     💵 Total: $944.00

     💡 You might also like: Galaxy Buds, Wireless Charger

     Please confirm to finalize your order.

   - User: Add Galaxy Buds to my order.
     Tool Called: add_item_to_order(category="accessories", brand="Samsung", model="Galaxy Buds", quantity=1)
     Agent Response:
     ✅ Added 1 × Samsung Galaxy Buds to your order.
     💰 Subtotal: $1,098.00
     🚚 Shipping: $55.00
     💵 New Total: $1,153.00

   - User: Confirm my order.
     Tool Called: confirm_order()
     Agent Response:
     ✅ Order Confirmed!
     ID: ORD4321
     Customer: Sara Khan
     Items: {'Samsung Galaxy S22': 1, 'Samsung Galaxy Buds': 1}
     Subtotal: $1,098.00
     Shipping: $55.00
     Total: $1,153.00
     Status: Confirmed

"""
