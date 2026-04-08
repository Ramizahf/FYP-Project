import json
import os
import ssl
import urllib.error
import urllib.request

from flask import current_app, jsonify, render_template, request, session

from db import execute_db

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
        "Do not give legal or medical advice. Always respond in English."
    ),
    'ms': (
        "Anda ialah MigrantSafe Assistant untuk pekerja asing di Malaysia. "
        "Jawab tentang pengesahan ejen, yuran pengambilan, dokumen kerja, hak pekerja, kontrak, "
        "dan cara membuat laporan. Guna bahasa mudah dan ringkas. "
        "Jika pengguna berada dalam bahaya atau dieksploitasi, berikan hotline JTKSM: 03-8000 8000. "
        "Jangan beri nasihat perundangan atau perubatan. Jawab dalam Bahasa Melayu sahaja."
    ),
    'bn': (
        "You are MigrantSafe Assistant for Bangla-speaking migrant workers in Malaysia. "
        "Answer about agent verification, recruitment fees, work documents, worker rights, contracts, "
        "and reporting scams or abuse. Use very simple language. "
        "If the user appears in danger or exploited, include the JTKSM hotline: 03-8000 8000. "
        "Do not give legal or medical advice. Respond in Bangla."
    ),
}


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


def chatbot():
    """Public chatbot page."""
    return render_template('chatbot.html')


def chat_api():
    """
    Accepts: { "message": "...", "language": "en|ms|bn", "history": [...] }
    Returns: { "response": "..." }
    Logs every exchange to chatbot_logs table.
    """
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    language = data.get('language', 'en')
    history = data.get('history', [])

    if not message:
        return jsonify({'response': 'Please type a message.'}), 400

    reply = get_bot_reply(message, language, history)

    user_id = session.get('user_id')
    try:
        execute_db(
            "INSERT INTO chatbot_logs (user_id, message, response, language) VALUES (?, ?, ?, ?)",
            (user_id, message[:1000], reply[:2000], language)
        )
    except Exception:
        pass

    return jsonify({'response': reply})


def chat_health():
    """Simple live-provider diagnostic for the browser and local testing."""
    api_key = os.environ.get('OPENCODE_API_KEY', '').strip()
    model = os.environ.get('OPENCODE_MODEL', 'openai/gpt-oss-120b:free').strip()
    base_url = os.environ.get('OPENCODE_API_BASE_URL', 'https://openrouter.ai/api/v1').strip().rstrip('/')

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
    language = language if language in ('en', 'ms', 'bn') else 'en'
    api_key = os.environ.get('OPENCODE_API_KEY', '').strip()
    base_url = os.environ.get(
        'OPENCODE_API_BASE_URL',
        'https://openrouter.ai/api/v1'
    ).strip().rstrip('/')
    model = os.environ.get(
        'OPENCODE_MODEL',
        'openai/gpt-oss-120b:free'
    ).strip()

    if api_key:
        system_prompt = CHATBOT_SYSTEM.get(language, CHATBOT_SYSTEM['en'])
        messages = [{'role': 'system', 'content': system_prompt}]

        if history:
            for turn in history[-6:]:
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
            return _api_error_reply(language)
        except urllib.error.HTTPError as exc:
            error_body = _read_http_error_body(exc)
            current_app.logger.warning(
                "Chat API HTTP error %s: %s",
                exc.code,
                error_body[:1000]
            )
            return _api_error_reply(language)
        except Exception as exc:
            current_app.logger.warning(f"Chat API error: {exc}")
            return _api_error_reply(language)

    return _offline_reply(message, language)


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
    with urllib.request.urlopen(req, timeout=20, context=ssl_context) as resp:
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


def _api_error_reply(language: str) -> str:
    """Clear, localized message shown only when the live API was expected but failed."""
    replies = {
        'en': (
            "I could not reach the live AI service just now. "
            "Please try again in a moment. If this keeps happening, check the API key, model, and network connection."
        ),
        'ms': (
            "Saya tidak dapat menghubungi perkhidmatan AI langsung sebentar tadi. "
            "Sila cuba lagi sebentar lagi. Jika masalah ini berterusan, semak kunci API, model, dan sambungan rangkaian."
        ),
        'bn': (
            "Ami ekhono live AI service e jogajog korte parini. "
            "Doya kore ektu por abar cheshta korun. Jodi eta bar bar hoy, API key, model, ebong network connection check korun."
        ),
    }
    return replies.get(language, replies['en'])


def _offline_reply(message: str, language: str) -> str:
    """Scored offline fallback for core MigrantSafe support topics."""
    low = message.lower()
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
    app.add_url_rule('/api/chat/health', endpoint='chat_health', view_func=chat_health, methods=['GET'])
