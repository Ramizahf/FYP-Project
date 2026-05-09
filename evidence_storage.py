import base64
import json
import mimetypes
import os
from datetime import datetime
from io import BytesIO
from uuid import uuid4

from flask import current_app, send_file, send_from_directory
from werkzeug.utils import secure_filename


def make_report_evidence_record(upload, report_id):
    """Return a JSON-serializable evidence record that survives serverless deploys."""
    original_name = secure_filename(upload.filename)
    if not original_name:
        extension = upload.filename.rsplit('.', 1)[1].lower()
        original_name = f"evidence.{extension}"

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    stored_name = f"report_{report_id}_{timestamp}_{uuid4().hex[:8]}_{original_name}"
    content = upload.read()
    upload.stream.seek(0)
    content_type = (
        upload.mimetype
        or mimetypes.guess_type(original_name)[0]
        or 'application/octet-stream'
    )

    return {
        'storage': 'database',
        'filename': original_name,
        'stored_name': stored_name,
        'content_type': content_type,
        'data': base64.b64encode(content).decode('ascii'),
    }


def parse_report_evidence_entries(evidence_path):
    """Return normalized report evidence entries from legacy paths or DB records."""
    if not evidence_path:
        return []

    try:
        raw_entries = json.loads(evidence_path)
    except (TypeError, ValueError):
        raw_entries = [evidence_path]

    if not isinstance(raw_entries, list):
        return []

    entries = []
    for entry in raw_entries:
        if isinstance(entry, dict) and entry.get('storage') == 'database':
            entries.append({
                'storage': 'database',
                'filename': entry.get('filename') or entry.get('stored_name') or 'evidence',
                'stored_name': entry.get('stored_name') or entry.get('filename') or 'evidence',
                'content_type': entry.get('content_type') or 'application/octet-stream',
                'data': entry.get('data') or '',
            })
        elif isinstance(entry, str):
            entries.append({
                'storage': 'filesystem',
                'path': entry,
                'filename': os.path.basename(entry),
            })
    return entries


def evidence_entry_filename(entry):
    return entry.get('filename') or os.path.basename(entry.get('path', '')) or 'evidence'


def send_report_evidence_entry(entry):
    if entry.get('storage') == 'database':
        data = base64.b64decode(entry.get('data') or '')
        return send_file(
            BytesIO(data),
            mimetype=entry.get('content_type') or 'application/octet-stream',
            download_name=evidence_entry_filename(entry),
            as_attachment=False,
        )

    filename = os.path.basename(entry.get('path', ''))
    return send_from_directory(current_app.config['REPORT_EVIDENCE_FOLDER'], filename)
