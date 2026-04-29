import json
import os
import ssl
import urllib.error
import urllib.request

from flask import current_app, jsonify, render_template, request, session

from db import execute_db, query_db, rows_to_dicts

try:
    import certifi
except ImportError:  # pragma: no cover - optional dependency
    certifi = None


CHATBOT_SYSTEM = {
    'en': (
        "You are MigrantSafe Assistant, a warm and practical guide for migrant workers in Malaysia. "
        "Answer questions about agent verification, recruitment fees, work documents, reporting abuse, "
        "worker rights, contracts, and scams. Use short paragraphs and simple language. "
        "If the user appears in danger or exploited, include the JTKSM hotline: 03-8000 8000. "
        "Do not give legal or medical advice. Always respond in English only. "
        "Do not answer romance, dating, sexual, or unrelated personal relationship questions; redirect to MigrantSafe topics."
    ),
    'ms': (
        "Anda ialah MigrantSafe Assistant untuk pekerja asing di Malaysia. "
        "Jawab tentang pengesahan ejen, yuran pengambilan, dokumen kerja, hak pekerja, kontrak, "
        "dan cara membuat laporan. Guna bahasa mudah dan ringkas. "
        "Jika pengguna berada dalam bahaya atau dieksploitasi, berikan hotline JTKSM: 03-8000 8000. "
        "Jangan beri nasihat perundangan atau perubatan. Jawab dalam Bahasa Melayu sahaja. "
        "Jangan jawab soalan romantik, dating, seksual, atau hubungan peribadi yang tidak berkaitan; arahkan kepada topik MigrantSafe."
    ),
    'bn': (
        "You are MigrantSafe Assistant for Bangla-speaking migrant workers in Malaysia. "
        "Answer about agent verification, recruitment fees, work documents, worker rights, contracts, "
        "and reporting scams or abuse. Use very simple language. "
        "If the user appears in danger or exploited, include the JTKSM hotline: 03-8000 8000. "
        "Do not give legal or medical advice. Respond in Bangla only. "
        "Do not answer romance, dating, sexual, or unrelated personal relationship questions; redirect to MigrantSafe topics."
    ),
}

CHAT_CONTEXT_LIMIT = 12
MAX_USER_MESSAGE_LENGTH = 1000
MAX_BOT_MESSAGE_LENGTH = 2000


OFFLINE_TOPICS = [
    {
        'primary': {
            'en': ['fee', 'fees', 'upfront', 'overcharge', 'recruitment fee', 'pay agent', 'deposit'],
            'ms': ['yuran', 'bayaran', 'caj', 'deposit', 'ejen minta bayar'],
            'bn': ['fi', 'fee', 'taka', 'agent ke taka', 'ogrim', 'payment', 'ফি', 'টাকা', 'অগ্রিম', 'পেমেন্ট'],
        },
        'secondary': {
            'en': ['money', 'pay', 'charge', 'rm', 'cost', 'expensive'],
            'ms': ['wang', 'duit', 'bayar', 'kos', 'mahal'],
            'bn': ['taka', 'payment', 'khoroch', 'dam', 'খরচ', 'দাম', 'পে'],
        },
        'answers': {
            'en': (
                "Recruitment fees should be paid by the employer, not the worker. "
                "If an agent asks you for large upfront payments, do not pay immediately. "
                "Save any messages or receipts, report the agent on MigrantSafe, and call JTKSM at 03-8000 8000."
            ),
            'ms': (
                "Yuran pengambilan sepatutnya dibayar oleh majikan, bukan pekerja. "
                "Jika ejen meminta bayaran pendahuluan yang besar, jangan terus bayar. "
                "Simpan mesej atau resit sebagai bukti, laporkan di MigrantSafe, dan hubungi JTKSM di 03-8000 8000."
            ),
            'bn': (
                "Recruitment fee niyogkorta dewar kotha, shromiker noy. "
                "Jodi agent boro ogrim taka chai, sathe sathe diben na. "
                "Message ba receipt rakhun, MigrantSafe e report korun, ebong JTKSM 03-8000 8000 e call korun."
            ),
        },
    },
    {
        'primary': {
            'en': ['verify agent', 'check agent', 'real agent', 'fake agent', 'legit agent', 'license'],
            'ms': ['semak ejen', 'ejen sah', 'ejen palsu', 'lesen ejen', 'pengesahan ejen'],
            'bn': ['agent check', 'asal agent', 'vuya agent', 'license', 'verify agent', 'এজেন্ট', 'লাইসেন্স', 'ভুয়া', 'যাচাই'],
        },
        'secondary': {
            'en': ['verify', 'legit', 'real', 'fake', 'scam', 'trustworthy'],
            'ms': ['semak', 'sah', 'palsu', 'scam', 'tipu'],
            'bn': ['check', 'real', 'fake', 'scam', 'thik agent', 'আসল', 'নকল', 'স্ক্যাম'],
        },
        'answers': {
            'en': (
                "Check the agent on MigrantSafe before paying anything. "
                "Verified means admin-checked, pending means still under review, and reported means complaints were filed. "
                "You can also verify through JTKSM at 03-8000 8000."
            ),
            'ms': (
                "Semak ejen di MigrantSafe sebelum membuat bayaran. "
                "Disahkan bermaksud telah disemak admin, pending masih dalam semakan, dan dilaporkan bermaksud ada aduan. "
                "Anda juga boleh semak dengan JTKSM di 03-8000 8000."
            ),
            'bn': (
                "Taka dewar agey MigrantSafe e agent check korun. "
                "Verified mane admin check koreche, pending mane review cholche, ar reported mane complaint ache. "
                "JTKSM 03-8000 8000 eo check korte paren."
            ),
        },
    },
    {
        'primary': {
            'en': ['passport', 'salary', 'worker rights', 'abuse', 'threat', 'harass'],
            'ms': ['pasport', 'gaji', 'hak pekerja', 'ancaman', 'didera', 'ganggu'],
            'bn': ['passport', 'betan', 'rights', 'nirjaton', 'voy deya', 'threat', 'পাসপোর্ট', 'বেতন', 'অধিকার', 'নির্যাতন'],
        },
        'secondary': {
            'en': ['rights', 'pay me', 'employer', 'unsafe', 'forced'],
            'ms': ['hak', 'majikan', 'selamat', 'paksa'],
            'bn': ['odhikar', 'malik', 'jor kore', 'nirapod na', 'মালিক', 'জোর', 'হুমকি'],
        },
        'answers': {
            'en': (
                "You have the right to keep your passport, receive full salary on time, and work without abuse or threats. "
                "If these rights are violated, report it on MigrantSafe and contact JTKSM at 03-8000 8000."
            ),
            'ms': (
                "Anda berhak menyimpan pasport sendiri, menerima gaji penuh tepat masa, dan bekerja tanpa ancaman atau penderaan. "
                "Jika hak ini dilanggar, laporkan di MigrantSafe dan hubungi JTKSM di 03-8000 8000."
            ),
            'bn': (
                "Apnar odhikar holo nijer passport rakha, somoy moto puro betan paoa, ebong voy ba nirjaton chara kaj kora. "
                "Odhikar bhong hole MigrantSafe e report korun ebong JTKSM 03-8000 8000 e jogajog korun."
            ),
        },
    },
    {
        'primary': {
            'en': ['visa', 'permit', 'fomema', 'document', 'contract', 'work permit'],
            'ms': ['visa', 'permit', 'fomema', 'dokumen', 'kontrak', 'permit kerja'],
            'bn': ['visa', 'permit', 'fomema', 'document', 'contract', 'work permit', 'ভিসা', 'পারমিট', 'ডকুমেন্ট', 'চুক্তি'],
        },
        'secondary': {
            'en': ['paper', 'passport', 'medical', 'job contract'],
            'ms': ['dokumen kerja', 'pasport', 'medical', 'surat'],
            'bn': ['kagoj', 'passport', 'medical', 'chakrir chukti', 'কাগজ', 'মেডিকেল', 'চাকরির চুক্তি'],
        },
        'answers': {
            'en': (
                "To work legally in Malaysia, you usually need a valid passport, VP(TE) work permit processing, "
                "FOMEMA medical clearance, and a written employment contract you understand."
            ),
            'ms': (
                "Untuk bekerja secara sah di Malaysia, anda biasanya memerlukan pasport sah, proses permit kerja VP(TE), "
                "kelulusan perubatan FOMEMA, dan kontrak kerja bertulis yang anda faham."
            ),
            'bn': (
                "Malaysia te boidho vabe kaj korte hole shadharonoto valid passport, VP(TE) permit process, "
                "FOMEMA medical clearance, ebong bujhte paren emon likhito contract dorkar."
            ),
        },
    },
    {
        'primary': {
            'en': ['report agent', 'complaint', 'fraud', 'cheated', 'report abuse'],
            'ms': ['lapor ejen', 'aduan', 'penipuan', 'lapor', 'buat laporan'],
            'bn': ['report agent', 'obijog', 'fraud', 'thokese', 'report', 'রিপোর্ট', 'অভিযোগ', 'প্রতারণা', 'ঠকেছে'],
        },
        'secondary': {
            'en': ['report', 'complain', 'scam', 'lied'],
            'ms': ['lapor', 'adu', 'tipu', 'scam'],
            'bn': ['report', 'complaint', 'scam', 'mithya', 'স্ক্যাম', 'মিথ্যা'],
        },
        'answers': {
            'en': (
                "To report an unethical agent, log in, open the report form, choose the issue type, and describe what happened clearly. "
                "Admins review reports, and urgent cases should also be reported to JTKSM at 03-8000 8000."
            ),
            'ms': (
                "Untuk melaporkan ejen tidak beretika, log masuk, buka borang laporan, pilih jenis isu, dan terangkan apa yang berlaku dengan jelas. "
                "Admin akan menyemak laporan, dan kes mendesak juga perlu dilaporkan kepada JTKSM di 03-8000 8000."
            ),
            'bn': (
                "Onaitik agent report korte login korun, report form khulun, issue type nin, ar ki ghoteche sheta bistarito likhun. "
                "Admin review korbe, ar joruri obosthay JTKSM 03-8000 8000 e o jogajog korun."
            ),
        },
    },
]


def _normalize_chat_language(language):
    """Restrict chat language values to the supported set."""
    return language if language in ('en', 'ms', 'bn') else 'en'


def _sanitize_guest_history(history):
    """Keep only the recent client-side turns needed for guest chat context."""
    cleaned_history = []
    for turn in history or []:
        role = (turn or {}).get('role', '')
        content = ((turn or {}).get('content', '') or '').strip()
        if role in ('user', 'assistant') and content:
            cleaned_history.append({'role': role, 'content': content[:MAX_BOT_MESSAGE_LENGTH]})
    return cleaned_history[-CHAT_CONTEXT_LIMIT:]


def _get_saved_chat_history(user_id):
    """Load all saved chat messages for one logged-in user."""
    if not user_id:
        return []

    rows = rows_to_dicts(query_db(
        "SELECT sender, message, language, created_at "
        "FROM chat_messages WHERE user_id = ? ORDER BY id ASC",
        (user_id,)
    ))
    return [
        {
            'sender': row['sender'],
            'message': row['message'],
            'language': _normalize_chat_language(row['language']),
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def _get_recent_chat_context(user_id):
    """Load the recent saved turns that should be sent back to the AI model."""
    if not user_id:
        return []

    rows = rows_to_dicts(query_db(
        "SELECT sender, message FROM chat_messages "
        "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, CHAT_CONTEXT_LIMIT)
    ))
    rows.reverse()

    conversation = []
    for row in rows:
        conversation.append({
            'role': 'assistant' if row['sender'] == 'bot' else 'user',
            'content': row['message'],
        })
    return conversation


def _save_chat_message(user_id, sender, message, language):
    """Persist one chat bubble for the logged-in user."""
    if not user_id:
        return

    max_length = MAX_USER_MESSAGE_LENGTH if sender == 'user' else MAX_BOT_MESSAGE_LENGTH
    execute_db(
        "INSERT INTO chat_messages (user_id, sender, message, language) VALUES (?, ?, ?, ?)",
        (user_id, sender, message[:max_length], _normalize_chat_language(language))
    )


def chatbot():
    """Chatbot page with saved history for logged-in users."""
    user_id = session.get('user_id')
    chat_history = _get_saved_chat_history(user_id)
    chat_language = chat_history[-1]['language'] if chat_history else 'en'
    return render_template(
        'chatbot.html',
        chat_history=chat_history,
        chat_language=chat_language,
        is_logged_in=bool(user_id),
    )


def chat_api():
    """
    Accepts: { "message": "...", "language": "en|ms|bn", "history": [...] }
    Returns: { "response": "..." }
    Logged-in users get persistent memory from the database.
    """
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    language = _normalize_chat_language(data.get('language', 'en'))
    history = data.get('history', [])

    if not message:
        return jsonify({'response': 'Please type a message.'}), 400

    user_id = session.get('user_id')
    if user_id:
        conversation_history = _get_recent_chat_context(user_id)
        _save_chat_message(user_id, 'user', message, language)
    else:
        conversation_history = _sanitize_guest_history(history)

    reply = get_bot_reply(message, language, conversation_history)

    if user_id:
        _save_chat_message(user_id, 'bot', reply, language)

    return jsonify({'response': reply})


def clear_chat_history():
    """Delete all saved chatbot messages for the current logged-in user."""
    user_id = session.get('user_id')
    if user_id:
        execute_db("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
    return jsonify({'ok': True})


def chat_health():
    """Simple live-provider diagnostic for the browser and local testing."""
    api_key, base_url, model = _chat_provider_config()

    if not api_key:
        return jsonify({
            'ok': False,
            'mode': 'missing_key',
            'model': model,
            'base_url': base_url,
            'message': 'Missing OPENCODE_API_KEY'
        }), 503

    ok, error_message = _probe_chat_provider(api_key, base_url, model)
    return jsonify({
        'ok': ok,
        'mode': 'live_api' if ok else 'live_api_error',
        'model': model,
        'base_url': base_url,
        'message': 'Live AI service reachable.' if ok else error_message,
    }), 200 if ok else 503


def get_bot_reply(message: str, language: str = 'en', history: list = None) -> str:
    """Call the configured OpenAI-compatible provider, or fall back to local FAQ answers."""
    language = _normalize_chat_language(language)
    guardrail_reply = _guardrail_reply(message, language)
    if guardrail_reply:
        return guardrail_reply

    quick_reply = _quick_local_reply(message, language)
    if quick_reply:
        return quick_reply

    api_key, base_url, model = _chat_provider_config()

    if api_key:
        system_prompt = CHATBOT_SYSTEM.get(language, CHATBOT_SYSTEM['en'])
        messages = [{'role': 'system', 'content': system_prompt}]

        if history:
            for turn in history[-CHAT_CONTEXT_LIMIT:]:
                role = turn.get('role', '')
                content = turn.get('content', '')
                if role in ('user', 'assistant') and content:
                    messages.append({'role': role, 'content': content})

        messages.append({'role': 'user', 'content': message})

        payload = json.dumps({
            'model': model,
            'messages': messages,
            'temperature': 0.7,
            'max_tokens': 600
        }).encode()

        try:
            data = _perform_chat_request(api_key, base_url, payload)
            choices = data.get('choices') or []
            if choices:
                content = choices[0].get('message', {}).get('content', '').strip()
                if content:
                    return content
            current_app.logger.warning("Chat API returned no message content.")
            return _offline_or_api_error_reply(message, language)
        except urllib.error.HTTPError as exc:
            error_body = _read_http_error_body(exc)
            current_app.logger.warning(
                "Chat API HTTP error %s: %s",
                exc.code,
                error_body[:1000]
            )
            return _offline_or_api_error_reply(message, language)
        except Exception as exc:
            current_app.logger.warning(f"Chat API error: {exc}")
            return _offline_or_api_error_reply(message, language)

    return _offline_reply(message, language)


def _chat_provider_config() -> tuple[str, str, str]:
    """Read OpenAI-compatible provider settings with common env aliases."""
    api_key = (
        os.environ.get('OPENCODE_API_KEY')
        or os.environ.get('OPENROUTER_API_KEY')
        or os.environ.get('OPENAI_API_KEY')
        or ''
    ).strip()
    base_url = (
        os.environ.get('OPENCODE_API_BASE_URL')
        or os.environ.get('OPENROUTER_BASE_URL')
        or os.environ.get('OPENAI_BASE_URL')
        or 'https://openrouter.ai/api/v1'
    ).strip().rstrip('/')
    model = (
        os.environ.get('OPENCODE_MODEL')
        or os.environ.get('OPENROUTER_MODEL')
        or os.environ.get('OPENAI_MODEL')
        or 'openai/gpt-oss-120b:free'
    ).strip()
    return api_key, base_url, model


def _perform_chat_request(api_key: str, base_url: str, payload: bytes) -> dict:
    """Execute one OpenAI-compatible chat completions call with explicit TLS settings."""
    req = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=payload,
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
            'HTTP-Referer': request.host_url.rstrip('/'),
            'Origin': request.host_url.rstrip('/'),
            'X-Title': 'MigrantSafe Chatbot',
            'User-Agent': 'MigrantSafe/1.0'
        }
    )
    ssl_context = (
        ssl.create_default_context(cafile=certifi.where())
        if certifi is not None
        else ssl.create_default_context()
    )

    # Some local/dev environments set HTTP(S)_PROXY to a closed proxy, which
    # makes urllib fail immediately before the request reaches the AI provider.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        urllib.request.HTTPSHandler(context=ssl_context),
    )
    with opener.open(req, timeout=20) as resp:
        return json.loads(resp.read())


def _probe_chat_provider(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """Low-cost provider probe used by the health endpoint."""
    payload = json.dumps({
        'model': model,
        'messages': [{'role': 'user', 'content': 'Reply with exactly: OK'}],
        'temperature': 0,
        'max_tokens': 8
    }).encode()
    try:
        data = _perform_chat_request(api_key, base_url, payload)
        choices = data.get('choices') or []
        if choices and choices[0].get('message', {}).get('content', '').strip():
            return True, ''
        return False, 'Provider replied without usable message content.'
    except urllib.error.HTTPError as exc:
        body = _read_http_error_body(exc)
        return False, f'HTTP {exc.code}: {body[:300]}'
    except Exception as exc:
        return False, str(exc)


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    """Best-effort HTTP error body read for logging and diagnostics."""
    try:
        return exc.read().decode('utf-8', errors='replace')
    except Exception:
        return '<unreadable error body>'


def _detect_message_language(message: str) -> str | None:
    """Best-effort detection for supported chat languages only."""
    text = (message or '').strip().lower()
    if not text:
        return None

    if any('\u0980' <= char <= '\u09ff' for char in text):
        return 'bn'

    ms_markers = (
        'saya', 'awak', 'anda', 'boleh', 'tolong', 'terima kasih', 'selamat',
        'ejen', 'majikan', 'pekerja', 'gaji', 'yuran', 'dokumen', 'lapor',
        'penipuan', 'permit kerja', 'bahasa melayu'
    )
    en_markers = (
        'i ', 'you', 'can', 'how', 'what', 'why', 'where', 'when', 'agent',
        'worker', 'fee', 'fees', 'document', 'passport', 'salary', 'report',
        'contract', 'visa', 'permit', 'employer'
    )

    ms_score = sum(1 for word in ms_markers if word in text)
    en_score = sum(1 for word in en_markers if word in text)
    if ms_score > en_score and ms_score > 0:
        return 'ms'
    if en_score > 0:
        return 'en'
    return None


def _language_switch_reply(language: str, detected_language: str) -> str:
    replies = {
        'en': "Please switch the chat language first. I can only reply in the selected language.",
        'ms': "Sila tukar bahasa chat dahulu. Saya hanya boleh membalas dalam bahasa yang dipilih.",
        'bn': "Doya kore age chat language bodlan. Ami sudhu selected language e reply korte pari.",
    }
    return replies.get(language, replies['en'])


def _romance_guardrail_reply(language: str) -> str:
    replies = {
        'en': (
            "I can only help with MigrantSafe topics like agent checks, fees, documents, worker rights, "
            "and reporting abuse. For personal or romantic questions, please use another support channel."
        ),
        'ms': (
            "Saya hanya boleh membantu topik MigrantSafe seperti semakan ejen, yuran, dokumen, hak pekerja, "
            "dan laporan penderaan. Untuk soalan peribadi atau romantik, sila gunakan saluran lain."
        ),
        'bn': (
            "Ami sudhu MigrantSafe topic niye help korte pari, jemon agent check, fee, document, worker rights, "
            "ebong abuse report. Personal ba romantic proshner jonno onno support channel use korun."
        ),
    }
    return replies.get(language, replies['en'])


def _guardrail_reply(message: str, language: str) -> str | None:
    """Local guardrails that should not be sent to the live model."""
    low = (message or '').strip().lower()
    if not low:
        return None

    detected_language = _detect_message_language(low)
    if detected_language and detected_language != language:
        return _language_switch_reply(language, detected_language)

    romance_terms = (
        'love', 'crush', 'romantic', 'romance', 'dating', 'date me', 'girlfriend',
        'boyfriend', 'marry me', 'kiss', 'flirt', 'sex', 'sexy',
        'cinta', 'sayang', 'romantik', 'teman lelaki', 'teman wanita', 'janji temu',
        'kahwin', 'cium', 'seks',
        'prem', 'bhalobasha', 'valobasha', 'biye', 'chumu', 'girlfriend', 'boyfriend'
    )
    if any(term in low for term in romance_terms):
        return _romance_guardrail_reply(language)

    return None


def _quick_local_reply(message: str, language: str) -> str | None:
    """Instant local replies for tiny conversational turns that do not need AI."""
    low = (message or '').strip().lower()
    if not low:
        return None

    greeting_words = {
        'en': ('hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening'),
        'ms': ('hi', 'hai', 'helo', 'hello', 'selamat pagi', 'selamat petang', 'selamat malam'),
        'bn': ('hi', 'hello', 'assalamualaikum', 'salam'),
    }
    thanks_words = {
        'en': ('thanks', 'thank you', 'thx'),
        'ms': ('terima kasih', 'thanks', 'thank you'),
        'bn': ('thanks', 'thank you', 'dhonnobad', 'dhanyabad'),
    }
    goodbye_words = {
        'en': ('bye', 'goodbye', 'see you'),
        'ms': ('bye', 'selamat tinggal', 'jumpa lagi'),
        'bn': ('bye', 'goodbye', 'abar dekha hobe'),
    }

    def matches(words):
        return any(low == word or low.startswith(f'{word} ') for word in words)

    if matches(greeting_words.get(language, greeting_words['en'])):
        greetings = {
            'en': (
                "Hi, I am MigrantSafe Assistant. I can help with agent checks, fees, work documents, "
                "worker rights, and reporting unsafe treatment. What do you need help with?"
            ),
            'ms': (
                "Hai, saya MigrantSafe Assistant. Saya boleh bantu semak ejen, faham yuran, dokumen kerja, "
                "hak pekerja, dan laporan layanan tidak selamat. Apa yang anda perlukan?"
            ),
            'bn': (
                "Hi, ami MigrantSafe Assistant. Ami agent check, fee, work document, rights, "
                "ba unsafe treatment report korte shahajjo korte pari. Apnar ki shahajjo dorkar?"
            ),
        }
        return greetings.get(language, greetings['en'])

    if matches(thanks_words.get(language, thanks_words['en'])):
        replies = {
            'en': "You are welcome. Ask me anytime if you need help with an agent, fees, documents, rights, or reporting abuse.",
            'ms': "Sama-sama. Tanya saya bila-bila masa tentang ejen, yuran, dokumen, hak pekerja, atau laporan penderaan.",
            'bn': "Apnake shagotom. Agent, fee, document, rights, ba abuse report niye jekono somoy jiggesh korte paren.",
        }
        return replies.get(language, replies['en'])

    if matches(goodbye_words.get(language, goodbye_words['en'])):
        replies = {
            'en': "Take care. If you feel unsafe or exploited, contact JTKSM at 03-8000 8000.",
            'ms': "Jaga diri. Jika anda tidak selamat atau dieksploitasi, hubungi JTKSM di 03-8000 8000.",
            'bn': "Nijer kheyal rakhun. Unsafe ba exploited mone hole JTKSM 03-8000 8000 e contact korun.",
        }
        return replies.get(language, replies['en'])

    return None


def _api_error_reply(language: str) -> str:
    """Friendly localized message shown when live AI fails and no local topic matches."""
    replies = {
        'en': (
            "I am having trouble reaching the live AI service right now, but I can still help with common MigrantSafe topics. "
            "Ask me about checking an agent, recruitment fees, visa or documents, worker rights, or reporting abuse."
        ),
        'ms': (
            "Saya menghadapi masalah menghubungi perkhidmatan AI langsung sekarang, tetapi saya masih boleh membantu tentang topik biasa MigrantSafe. "
            "Tanya saya tentang semakan ejen, yuran pengambilan, visa atau dokumen, hak pekerja, atau laporan penderaan."
        ),
        'bn': (
            "Ami ekhono live AI service e jogajog korte parchhi na, kintu MigrantSafe er common topic niye shahajjo korte pari. "
            "Agent check, recruitment fee, visa ba document, worker rights, ba abuse report niye jiggesh korun."
        ),
    }
    return replies.get(language, replies['en'])


def _offline_or_api_error_reply(message: str, language: str) -> str:
    """Use local guidance when the live provider fails, then explain if no topic matched."""
    offline_reply = _offline_reply(message, language)
    clarifier = _offline_reply('', language)
    if offline_reply != clarifier:
        return offline_reply
    return _api_error_reply(language)


def _offline_reply(message: str, language: str) -> str:
    """Scored offline fallback for core MigrantSafe support topics."""
    low = (message or '').strip().lower()

    greeting_words = {
        'en': ('hi', 'hello', 'hey', 'good morning', 'good afternoon', 'good evening'),
        'ms': ('hi', 'hai', 'helo', 'selamat pagi', 'selamat petang', 'selamat malam'),
        'bn': ('hi', 'hello', 'assalamualaikum', 'salam'),
    }
    if low and any(low == word or low.startswith(f'{word} ') for word in greeting_words.get(language, greeting_words['en'])):
        greetings = {
            'en': (
                "Hi, I am MigrantSafe Assistant. I can help you check agents, understand fees, prepare work documents, "
                "know your rights, or report unsafe treatment. What do you need help with?"
            ),
            'ms': (
                "Hai, saya MigrantSafe Assistant. Saya boleh bantu semak ejen, faham yuran, sediakan dokumen kerja, "
                "kenal hak pekerja, atau laporkan layanan tidak selamat. Apa yang anda perlukan?"
            ),
            'bn': (
                "Hi, ami MigrantSafe Assistant. Ami agent check, fee, work document, rights, ba unsafe treatment report korte shahajjo korte pari. "
                "Apnar ki shahajjo dorkar?"
            ),
        }
        return greetings.get(language, greetings['en'])

    help_words = {
        'en': ('help', 'what can you do', 'what can i ask'),
        'ms': ('tolong', 'bantuan', 'apa boleh tanya'),
        'bn': ('help', 'shahajjo', 'ki jiggesh'),
    }
    if low and any(word in low for word in help_words.get(language, help_words['en'])):
        return _api_error_reply(language)

    best_score = 0
    best_topic = None

    for topic in OFFLINE_TOPICS:
        score = 0
        primary = set(topic['primary'].get(language, [])) | set(topic['primary'].get('en', []))
        secondary = set(topic['secondary'].get(language, [])) | set(topic['secondary'].get('en', []))

        for keyword in primary:
            if keyword in low:
                score += 2
        for keyword in secondary:
            if keyword in low:
                score += 1

        if score > best_score:
            best_score = score
            best_topic = topic

    if best_topic and best_score >= 1:
        return best_topic['answers'].get(language) or best_topic['answers']['en']

    clarifiers = {
        'en': (
            "Please ask about one of these topics so I can help more accurately: "
            "agent verification, recruitment fees, visa or documents, worker rights, or reporting abuse."
        ),
        'ms': (
            "Sila tanya tentang salah satu topik ini supaya saya boleh membantu dengan lebih tepat: "
            "pengesahan ejen, yuran pengambilan, visa atau dokumen, hak pekerja, atau laporan penderaan."
        ),
        'bn': (
            "Doya kore ei bishoygulor ekta niye proshno korun jate ami aro thik bhabe shahajjo korte pari: "
            "agent verification, recruitment fee, visa ba document, worker rights, ba abuse report."
        ),
    }
    return clarifiers.get(language, clarifiers['en'])


def register_chatbot_routes(app):
    """Register the chatbot page and API endpoints."""
    app.add_url_rule('/chatbot', endpoint='chatbot', view_func=chatbot)
    app.add_url_rule('/api/chat', endpoint='chat_api', view_func=chat_api, methods=['POST'])
    app.add_url_rule('/api/chat/history', endpoint='clear_chat_history', view_func=clear_chat_history, methods=['POST'])
    app.add_url_rule('/api/chat/health', endpoint='chat_health', view_func=chat_health, methods=['GET'])
