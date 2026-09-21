"""Voice prompts, notification copy, and survey text."""

GREETING_EN = (
    "Thank you for calling Digital Dubai Authority. I have verified your identity "
    "with UAE PASS. How can I help you today?"
)
GREETING_AR = (
    "شكراً لتصلكم لهيئة دبي الرقمية. تم التحقق من هويتكم عبر الهوية الرقمية. كيف يمكنني مساعدتكم اليوم؟"
)

SUMMARY_PROMPT = """You are the post-call assistant for the Digital Dubai Authority call center. \
Write a structured summary of the following inbound call transcript, \
for a support supervisor and the citizen's own records.

Rules:
- Be factual. Only use information present in the transcript and context.
- `resolution` must describe exactly what was done for the caller, in 1-3 sentences.
- `follow_up_actions` lists concrete pending items (max 5); use [] if none.
- `outcome` must be one of: resolved, escalated, unresolved.
- Match the language of the call (`language` field given below).

Return JSON matching the provided schema.

Context:
- Citizen: {citizen_name}
- Open tickets found at call start: {ticket_context}
- Conversation language: {language}

Transcript:
{transcript}
"""

EMAIL_SUBJECT_EN = "Your Digital Dubai Authority call summary — ticket {ticket}"
EMAIL_SUBJECT_AR = "ملخص مكالمتك مع هيئة دبي الرقمية — {ticket}"

EMAIL_BODY_EN = """Dear {citizen_name},

Thank you for contacting Digital Dubai Authority. Here is a summary of your call:

Topic: {topic}
Ticket reference: {ticket}
Resolution: {resolution}

{follow_up_section}

We value your feedback. Please rate your experience:
{survey_url}

Digital Dubai Authority — Dubai Digital
"""

EMAIL_BODY_AR = """عزيزي {citizen_name}،

شكراً لتواصلكم مع هيئة دبي الرقمية. فيما يلي ملخص مكالمتكم:

الموضوع: {topic}
رقم الطلب: {ticket}
الإجراء المتخذ: {resolution}

{follow_up_section}

نقدّر ملاحظاتكم. يرجى تقييم تجربتكم:
{survey_url}

هيئة دبي الرقمية
"""

SMS_EN = (
    "Digital Dubai Authority: Thank you for your call about {topic}. "
    "Ticket {ticket}: {resolution}. Rate your experience: {survey_url}"
)
SMS_AR = (
    "هيئة دبي الرقمية: شكراً لمكالمتكم بخصوص {topic}. "
    "الطلب {ticket}: {resolution}. شاركونا تقييمكم: {survey_url}"
)

SURVEY_INVITE_EN = (
    "How was your experience with our AI assistant today? "
    "Tell us in 1 minute: {survey_url}"
)
SURVEY_INVITE_AR = "كيف كانت تجربتكم مع مساعدنا الذكي؟ شاركونا رأيكم: {survey_url}"
