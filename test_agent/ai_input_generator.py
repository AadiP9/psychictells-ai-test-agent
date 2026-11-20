"""
ai_input_generator.py
Generates test inputs for PsychicTells automation tests.

Phase 1: Static test data — Ask-a-Question flow
Phase 2: Extended static data — Auth, Chat, Payment flows
         Gemini integration placeholder ready to enable.
"""

import random


# ── Phase 1 — Ask a Question ───────────────────────────────────────────────────

STATIC_NORMAL = [
    {"question": "Will my relationship improve in the next 6 months?",   "category": "Love & Relationships", "label": "Relationship future"},
    {"question": "Should I accept the new job offer I received last week?","category": "Career",              "label": "Job offer decision"},
    {"question": "What financial changes should I prepare for this year?", "category": "Finance",             "label": "Financial outlook"},
    {"question": "Can you tell me about my spiritual path ahead?",         "category": "Spirituality",        "label": "Spiritual guidance"},
    {"question": "Will my health improve and what should I focus on?",     "category": "Health",              "label": "Health guidance"},
    {"question": "Is now a good time to start my own business?",           "category": "Career",              "label": "Business timing"},
    {"question": "Will I reconnect with someone from my past?",            "category": "Love & Relationships","label": "Reconnection"},
    {"question": "What should I know about my family dynamics this year?", "category": "Family",              "label": "Family dynamics"},
]

STATIC_EDGE = [
    {"question": "A" * 1000,                                               "category": "Love & Relationships","label": "Very long text (1 000 chars)"},
    {"question": "Will I find love? 💖✨🔮🌙⭐💫🌟🔯🙏",                  "category": "Love & Relationships","label": "Emoji-rich question"},
    {"question": "What's my future? <script>alert(1)</script>",            "category": "Career",              "label": "XSS attempt in question"},
    {"question": "'; DROP TABLE questions; --",                             "category": "Finance",             "label": "SQL injection attempt"},
    {"question": "¿Cuál es mi futuro? Quel est mon avenir? Wie ist meine Zukunft?","category": "Spirituality","label": "Multi-language (ES/FR/DE)"},
    {"question": "   \t\n   ",                                             "category": "Health",              "label": "Whitespace only"},
    {"question": "!@#$%^&*()_+-=[]{}|;':\",./<>?",                        "category": "Love & Relationships","label": "Special characters only"},
    {"question": "𝕎𝕚𝕝𝕝 𝕀 𝕗𝕚𝕟𝕕 𝕥𝕣𝕦𝕖 𝕝𝕠𝕧𝕖?",                    "category": "Love & Relationships","label": "Unicode fancy text"},
    {"question": "Will I find true love?" + " ✓" * 200,                   "category": "Love & Relationships","label": "Long with repeated unicode"},
    {"question": "\x00\x01\x02 null bytes test",                           "category": "Career",              "label": "Null byte injection"},
]

STATIC_INVALID = [
    {"question": "",                                                        "category": "",                    "label": "Empty question + no category"},
    {"question": "hi",                                                      "category": "",                    "label": "Too short (2 chars), no category"},
    {"question": "?",                                                       "category": "",                    "label": "Single special char"},
    {"question": "spam spam spam buy now click here FREE MONEY!!!",         "category": "",                    "label": "Spam-like content"},
    {"question": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",                    "category": "",                    "label": "Repeated meaningless chars"},
    {"question": "12345",                                                   "category": "",                    "label": "Numbers only"},
]


# ── Phase 2 — User Auth ────────────────────────────────────────────────────────

AUTH_VALID_USERS = [
    {"name": "Aryaman Dastek",    "email": "aryaman.dastek.test@gmail.com", "password": "Test@1234",        "label": "Primary test user"},
    {"name": "Test User Alpha",   "email": "testuser.alpha@mailtest.com",   "password": "Alpha@5678",       "label": "Secondary test user"},
]

AUTH_INVALID_INPUTS = [
    {"email": "notanemail",                    "password": "Test@1234",    "label": "Invalid email format"},
    {"email": "missing@domain",                "password": "Test@1234",    "label": "Incomplete email domain"},
    {"email": "valid@email.com",               "password": "short",        "label": "Password too short"},
    {"email": "valid@email.com",               "password": "",             "label": "Empty password"},
    {"email": "",                              "password": "Test@1234",    "label": "Empty email"},
    {"email": "'; DROP TABLE users; --",       "password": "Test@1234",    "label": "SQL injection in email"},
    {"email": "<script>alert(1)</script>@x.com","password": "Test@1234",   "label": "XSS in email"},
    {"email": "a" * 256 + "@test.com",         "password": "Test@1234",    "label": "Extremely long email"},
]

AUTH_WEAK_PASSWORDS = [
    {"password": "12345678",    "label": "Numbers only"},
    {"password": "password",    "label": "Common word"},
    {"password": "aaaaaaaa",    "label": "Repeated characters"},
    {"password": "Pass1",       "label": "Too short with complexity"},
    {"password": " " * 10,     "label": "Spaces only"},
]


# ── Phase 2 — Chat ─────────────────────────────────────────────────────────────

CHAT_NORMAL_MESSAGES = [
    {"message": "Hello, I would like guidance on my love life.",             "label": "Greeting + love"},
    {"message": "Can you help me understand what's coming in my career?",    "label": "Career question"},
    {"message": "I'm feeling lost. What does my future hold?",               "label": "Emotional opener"},
    {"message": "Is this the right time to make a big investment?",          "label": "Finance question"},
    {"message": "Will I find peace in my family situation soon?",            "label": "Family question"},
]

CHAT_EDGE_MESSAGES = [
    {"message": "Hi! 😊🔮✨💫",                                              "label": "Emoji message"},
    {"message": "A" * 500,                                                   "label": "Very long message"},
    {"message": "<script>alert('xss')</script>",                             "label": "XSS in message"},
    {"message": "'; DROP TABLE messages; --",                                "label": "SQL injection in message"},
    {"message": "¿Me puedes ayudar? S'il vous plaît aidez-moi.",            "label": "Multi-language message"},
    {"message": "   ",                                                       "label": "Whitespace-only message"},
]


# ── Phase 2 — Payment ──────────────────────────────────────────────────────────

PAYMENT_TEST_CARDS = [
    # Stripe test cards — NEVER charge real money
    {"number": "4242424242424242", "expiry": "12/30", "cvv": "123", "label": "Stripe success card",          "expected": "success"},
    {"number": "4000000000000002", "expiry": "12/30", "cvv": "123", "label": "Stripe declined card",         "expected": "declined"},
    {"number": "4000000000009995", "expiry": "12/30", "cvv": "123", "label": "Stripe insufficient funds",    "expected": "declined"},
    {"number": "4000000000000069", "expiry": "12/30", "cvv": "123", "label": "Stripe expired card",          "expected": "declined"},
    {"number": "4000000000000127", "expiry": "12/30", "cvv": "123", "label": "Stripe incorrect CVV",         "expected": "declined"},
    {"number": "1234567890123456", "expiry": "12/30", "cvv": "123", "label": "Invalid card number format",   "expected": "invalid"},
    {"number": "0000000000000000", "expiry": "12/30", "cvv": "000", "label": "All zeros card",               "expected": "invalid"},
    {"number": "4242424242424242", "expiry": "01/20", "cvv": "123", "label": "Expired date",                 "expected": "declined"},
]

PAYMENT_INVALID_INPUTS = [
    {"number": "",                "expiry": "",      "cvv": "",    "label": "All empty fields"},
    {"number": "abcd efgh ijkl", "expiry": "ab/cd", "cvv": "xyz", "label": "Non-numeric card data"},
    {"number": "4242",           "expiry": "12/30",  "cvv": "123", "label": "Incomplete card number"},
    {"number": "4242424242424242","expiry": "",      "cvv": "123", "label": "Missing expiry"},
    {"number": "4242424242424242","expiry": "12/30", "cvv": "",    "label": "Missing CVV"},
]


# ── Generator class ────────────────────────────────────────────────────────────

class AITestInputGenerator:
    """
    Generates test inputs for PsychicTells automation.

    Phase 1  — static Ask-a-Question data.
    Phase 2  — extended static data for Auth, Chat, Payment.
    Future   — Gemini API integration (set GEMINI_API_KEY in .env).
    """

    def __init__(self):
        self.client = None   # Gemini client placeholder

    # ── Phase 1 ─────────────────────────────────────────────────────────────
    def get_normal_inputs(self, count: int = 5) -> list[dict]:
        return random.sample(STATIC_NORMAL, min(count, len(STATIC_NORMAL)))

    def get_edge_case_inputs(self, count: int = 5) -> list[dict]:
        return STATIC_EDGE[:count]

    def get_invalid_inputs(self, count: int = 4) -> list[dict]:
        return STATIC_INVALID[:count]

    def get_all_inputs(self) -> dict:
        return {
            "normal":    self.get_normal_inputs(5),
            "edge_case": self.get_edge_case_inputs(5),
            "invalid":   self.get_invalid_inputs(4),
        }

    # ── Phase 2 — Auth ──────────────────────────────────────────────────────
    def get_valid_users(self) -> list[dict]:
        return AUTH_VALID_USERS

    def get_invalid_auth_inputs(self) -> list[dict]:
        return AUTH_INVALID_INPUTS

    def get_weak_passwords(self) -> list[dict]:
        return AUTH_WEAK_PASSWORDS

    # ── Phase 2 — Chat ──────────────────────────────────────────────────────
    def get_chat_normal_messages(self) -> list[dict]:
        return CHAT_NORMAL_MESSAGES

    def get_chat_edge_messages(self) -> list[dict]:
        return CHAT_EDGE_MESSAGES

    # ── Phase 2 — Payment ───────────────────────────────────────────────────
    def get_payment_test_cards(self) -> list[dict]:
        return PAYMENT_TEST_CARDS

    def get_payment_invalid_inputs(self) -> list[dict]:
        return PAYMENT_INVALID_INPUTS

    # ── Phase 2 — Gemini stub ────────────────────────────────────────────────
    def _ai_generate(self, input_type: str, count: int) -> list[dict]:
        """Future Gemini-powered generation. Falls back to static today."""
        print("[AIGenerator] Gemini not configured — using static fallback data.")
        mapping = {
            "normal":    STATIC_NORMAL,
            "edge_case": STATIC_EDGE,
            "invalid":   STATIC_INVALID,
            "chat":      CHAT_NORMAL_MESSAGES,
            "payment":   PAYMENT_TEST_CARDS,
        }
        return mapping.get(input_type, [])[:count]
