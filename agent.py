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

import re


#  ------------------------- Models ---------------------------------------------
# class ContactForm(BaseModel):
#     Name: str = Field(
#         ..., max_length=50, description="Full name of the user. Max Length: 50"
#     )
#     Email: EmailStr = Field(..., description="Valid email address of the user")
#     Phone: Optional[str] = Field(
#         None,
#         pattern=r"^\+?\d{10,15}$",  # ✅ changed from regex → pattern
#         description="Phone number of the user (optional). Must be 10–15 digits, with optional leading +",
#     )
#     Subject: str = Field(
#         ...,
#         max_length=100,
#         description="Subject line of the contact message. Max Length: 100",
#     )
#     Message: str = Field(
#         ..., max_length=1000, description="The main message body. Max Length: 1000"
#     )


#  ------------------------- Helper functions -----------------------------------
def is_valid_email(email: str) -> bool:
    pattern = r"^[\w\.-]+@[\w\.-]+\.\w{2,}$"
    return bool(re.match(pattern, email))


def is_valid_phone(phone: str) -> bool:
    # Example: accept numbers with optional +country code, spaces, or dashes
    pattern = r"^\+?\d{7,15}$"
    # Remove spaces or dashes for checking
    phone_clean = phone.replace(" ", "").replace("-", "")
    return bool(re.match(pattern, phone_clean))


def get_next_field(current_field: str, data: dict) -> str | None:
    """
    Returns the next field key from FORM_SCHEMA order.
    Skips over optional fields if they already have a value.
    """
    order = list(FORM_SCHEMA.keys())
    try:
        idx = order.index(current_field)
    except ValueError:
        return None

    for next_idx in range(idx + 1, len(order)):
        next_field = order[next_idx]
        # If already filled, skip
        if next_field in data and data[next_field].strip():
            continue
        return next_field

    return None


# def send_email_to_user(to_email: str, form_data: dict):
#     sender_email = "procrastinalot@gmail.com"
#     sender_password = os.getenv("EMAIL_APP_PASSWORD")  # store your app password in .env
#     subject = "Your MayfairTech Contact Form Submission"

#     body = f"""
#     Hi {form_data.get('name')},

#     Thank you for contacting MayfairTech.ai. Here is a summary of your submitted form:

#     Name: {form_data.get('name')}
#     Email: {form_data.get('email')}
#     Phone: {form_data.get('phone')}
#     Subject: {form_data.get('subject')}
#     Message: {form_data.get('message')}

#     Our team will get back to you shortly.

#     Best regards,
#     MayfairTech.ai
#     """

#     msg = MIMEMultipart()
#     msg['From'] = sender_email
#     msg['To'] = to_email
#     msg['Subject'] = subject
#     msg.attach(MIMEText(body, 'plain'))

#     try:
#         with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
#             server.login(sender_email, sender_password)
#             server.send_message(msg)
#         logger.info(f"✅ Email sent to {to_email}")
#     except Exception as e:
#         logger.error(f"❌ Failed to send email to {to_email}: {e}")

from openai import OpenAI

client = OpenAI()


def is_message_appropriate(message: str) -> bool:
    """
    Returns True if message passes moderation, False otherwise
    """
    response = client.moderations.create(model="omni-moderation-latest", input=message)
    # Access via attributes
    results = response.results[0]  # use .results, not ["results"]
    return not results.flagged


def detect_user_intent(user_input: str) -> str:
    """
    Uses an LLM to classify user intent for form confirmation.
    Returns: 'submit', 'cancel', or 'unknown'
    """
    intent_prompt = f"""
    You are an intent classifier for a contact form assistant.
    The user just previewed their form and now decides whether to submit it.

    Classify their intent as one of:
    - "submit"  → they want to send/confirm/submit
    - "cancel"  → they want to cancel/stop/discard
    - "unknown" → unclear or anything else

    User input: "{user_input}"
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # lightweight + cheap, adjust if needed
            messages=[
                {"role": "system", "content": "You are a strict intent classifier."},
                {"role": "user", "content": intent_prompt},
            ],
            max_tokens=2,
            temperature=0,
        )

        intent = response.choices[0].message.content.strip().lower()
        if intent in ["submit", "cancel"]:
            return intent
        return "unknown"

    except Exception as e:
        logger.error(f"OpenAI intent detection failed: {e}")
        return "unknown"


async def rotate_ambience(background_audio, interval=180):
    """Randomly rotate ambience every `interval` seconds."""
    while True:
        new_file = random.choice(AMBIENT_AUDIO_FILES)
        print(f"🔊 Switching ambience to {new_file}")
        await background_audio.set_ambient(AudioConfig(new_file, volume=0.6))
        await asyncio.sleep(interval)


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

    # ------------------ FLOW 5: Customer Support Form ------------------
    # @function_tool()
    # async def assist_contact_form(
    #     self, context: RunContext, form: ContactForm, user_input: str
    # ) -> str:
    #     """
    #     Assist the user in filling and submitting a structured contact form.

    #     Schema:
    #     --------
    #     The form follows the Pydantic model `ContactForm`:
    #             Name: str = Field(..., description="Full name of the user.")
    #             Email: EmailStr = Field(..., description="Valid email address.")
    #             Phone: Optional[str] = Field(None, description="Phone number (optional).")
    #             Subject: str = Field(..., description="Subject of the message.")
    #             Message: str = Field(..., description="Detailed message from the user.")

    #     Workflow:
    #     ---------
    #     1. **Preview Step**:
    #     - When the form is first received, the assistant shows the user a preview
    #         of the entered details (Name, Email, Phone, Subject, Message).
    #     - The assistant then asks: *"Would you like me to submit this form now?"*

    #     2. **Confirmation Step**:
    #     - The assistant waits for the user’s response.
    #     - The response is classified with LLM-powered intent detection
    #         (`detect_form_intent_llm()`).
    #     - Possible intents:
    #         - `"submit"` → form is confirmed and submitted.
    #         - `"cancel"` → form submission is canceled and cleared.
    #         - `"unknown"` → user’s response was unclear; the assistant re-asks.
    #     Returns:
    #     --------
    #     str : A human-readable message for the user indicating:
    #         - The form preview (first step).
    #         - Confirmation/cancelation/submission status.
    #     """
    #     logger.info("---------- Assist Contact Form ----------")
    #     logger.info(f"Form received: {form.model_dump()}")

    #     form_state = context.session_data.get("contact_form", {})

    #     # Step 1: Preview
    #     if not form_state.get("preview_shown"):
    #         context.session_data["contact_form"] = {
    #             "data": form.model_dump(),
    #             "preview_shown": True,
    #         }
    #         return (
    #             f"Here’s what I got:\n\n"
    #             f"- **Name:** {form.Name}\n"
    #             f"- **Email:** {form.Email}\n"
    #             f"- **Phone:** {form.Phone or '(skipped)'}\n"
    #             f"- **Subject:** {form.Subject}\n"
    #             f"- **Message:** {form.Message}\n\n"
    #             "Would you like me to submit this form now? (yes/no)"
    #         )

    #     logger.info("----------------- Detecting User's Intent ----------------")

    #     # Step 2: Confirmation
    #     user_input = form.UserReply or ""
    #     intent = detect_user_intent(user_input)

    #     if intent == "submit":
    #         logger.info("✅ Form confirmed by user, submitting...")
    #         context.session_data.pop("contact_form", None)
    #         return "✅ Your contact form has been submitted successfully!"
    #     elif intent == "cancel":
    #         logger.info("❌ User canceled the form")
    #         context.session_data.pop("contact_form", None)
    #         return "❌ The form has been canceled. Do you want me to help with something else?"
    #     else:
    #         return "I wasn’t sure — would you like me to submit the form now? (yes/no)"


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
