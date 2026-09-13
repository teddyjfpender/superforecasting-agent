"""Versioned, transactional transfer of archived bytes and source bindings.

Hashes prove integrity, never origin or historical availability. Imported source
claims remain imported; only an identical new HTTPS fetch can verify local origin.
"""
import base64
import hashlib
import json
from pathlib import Path
from forecasting.models import ValidationError, json_dumps, utc_now_iso

VERSION = 1
MAX_ARCHIVE_BYTES = 2_000_000


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS transferred_source_archives (
        evidence_id TEXT PRIMARY KEY REFERENCES evidence_items(id) ON DELETE CASCADE,
        sha256 TEXT NOT NULL, content BLOB NOT NULL, source_url TEXT NOT NULL,
        verification_status TEXT NOT NULL CHECK(verification_status IN ('imported', 'locally_reverified')),
        verified_at TEXT, provenance TEXT NOT NULL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS source_transfer_history (
        question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
        digest TEXT NOT NULL, imported_at TEXT NOT NULL, original_records TEXT NOT NULL,
        PRIMARY KEY(question_id, digest))''')


def export_sources(ledger, question_id, evidence):
    with ledger._connect() as conn:
        bindings = [dict(r) for r in conn.execute('SELECT * FROM applicability_bindings WHERE question_id=? ORDER BY rowid', (question_id,))]
        historical = [dict(r) for r in conn.execute('SELECT * FROM source_transfer_history WHERE question_id=? ORDER BY imported_at', (question_id,))]
        transferred = {r['evidence_id']: dict(r) for r in conn.execute('SELECT * FROM transferred_source_archives WHERE evidence_id IN (SELECT id FROM evidence_items WHERE question_id=?)', (question_id,))}
    archives = []
    for e in evidence:
        receipt = e.metadata.get('source_capture') or e.metadata.get('imported_source_capture')
        if e.id in transferred:
            record = transferred[e.id]
            raw, digest = bytes(record['content']), record['sha256']
            receipt = json.loads(record['provenance'])
        elif receipt and e.snapshot_path:
            path = Path(e.snapshot_path)
            if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise ValidationError('source archive unavailable or too large for portable export')
            raw = path.read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
        else:
            continue
        if receipt.get('sha256') != digest or hashlib.sha256(raw).hexdigest() != digest:
            raise ValidationError('source archive integrity mismatch during export')
        archives.append(dict(evidence_id=e.id, source_url=e.source_url, sha256=digest,
                             content_base64=base64.b64encode(raw).decode('ascii'), provenance=receipt))
    return dict(version=VERSION, bindings=bindings, archives=archives, history=historical)


def import_sources(ledger, conn, packet, *, conflict):
    transfer = packet.get('source_transfer')
    if transfer is None:
        return
    if not isinstance(transfer, dict) or type(transfer.get('version')) is not int or transfer['version'] != VERSION:
        raise ValidationError('unsupported source transfer version')
    for key in ('bindings', 'archives', 'history'):
        if not isinstance(transfer.get(key, []), list) or any(not isinstance(r, dict) for r in transfer.get(key, [])):
            raise ValidationError('source transfer ' + key + ' must be a list of objects')
    qid = packet['question']['id']
    from forecasting.applicability_facts import validate_fact_binding
    from forecasting.models import parse_timestamp
    for binding in transfer.get('bindings', []):
        if not isinstance(binding, dict) or binding.get('question_id') != qid:
            raise ValidationError('source binding belongs to another question')
        contract = binding.get('source_contract')
        if isinstance(contract, str):
            try:
                contract = json.loads(contract)
            except ValueError as exc:
                raise ValidationError('invalid source contract JSON') from exc
        validate_fact_binding(key=binding.get('fact_key'), source_url=binding.get('source_url'),
            value_pointer=binding.get('value_pointer'), observed_at_pointer=binding.get('observed_at_pointer'),
            value_type=binding.get('value_type'), max_age_seconds=binding.get('max_age_seconds'), source_contract=contract)
        if not isinstance(binding.get('id'), str) or not binding['id'].strip() or not parse_timestamp(binding.get('created_at'), field_name='binding created_at'):
            raise ValidationError('binding identity and timestamp are required')
        binding = {**binding, 'source_contract': binding.get('source_contract') if isinstance(binding.get('source_contract'), str) else json_dumps(contract) if contract else None}
        existing = conn.execute('SELECT * FROM applicability_bindings WHERE id=?', (binding['id'],)).fetchone()
        if existing:
            if dict(existing) != binding:
                raise ValidationError('conflicting source binding identity')
            continue
        columns = ('id', 'question_id', 'fact_key', 'source_url', 'value_pointer', 'observed_at_pointer', 'value_type', 'max_age_seconds', 'created_at', 'source_contract')
        conn.execute(f"INSERT INTO applicability_bindings ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", [binding.get(k) for k in columns])
    seen = set()
    for archive in transfer.get('archives', []):
        eid = archive.get('evidence_id')
        if eid in seen:
            raise ValidationError('duplicate source archive identity')
        seen.add(eid)
        e = ledger.get_evidence(eid)
        if e.question_id != qid or archive.get('source_url') != e.source_url:
            raise ValidationError('source archive scope mismatch')
        encoded = archive.get('content_base64')
        if not isinstance(encoded, str) or len(encoded) > (MAX_ARCHIVE_BYTES + 2) // 3 * 4:
            raise ValidationError('source archive too large or missing')
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValidationError('invalid source archive encoding') from exc
        digest = hashlib.sha256(raw).hexdigest()
        provenance = archive.get('provenance')
        if not isinstance(provenance, dict) or digest != archive.get('sha256') or digest != provenance.get('sha256') or provenance.get('url') != e.source_url:
            raise ValidationError('source archive integrity or provenance mismatch')
        existing = conn.execute('SELECT sha256, source_url FROM transferred_source_archives WHERE evidence_id=?', (eid,)).fetchone()
        if existing and tuple(existing) != (digest, e.source_url):
            raise ValidationError('conflicting transferred archive identity')
        if e.metadata.get('source_capture'):
            from forecasting.applicability_facts import verified_archive
            _, local_digest = verified_archive(e, e.source_url)
            if local_digest != digest:
                raise ValidationError('import conflicts with locally verified source')
            continue
        conn.execute('''INSERT OR IGNORE INTO transferred_source_archives
            (evidence_id,sha256,content,source_url,verification_status,provenance)
            VALUES (?,?,?,?,'imported',?)''', (eid,digest,raw,e.source_url,json_dumps(provenance)))
        # Never retain another machine's path as a local read capability.
        conn.execute('UPDATE evidence_items SET snapshot_path=NULL WHERE id=?', (eid,))
    original = {k: packet.get(k) for k in ('forecast_history', 'resolution', 'scores', 'postmortems', 'calibration_lessons', 'domain_error_profiles')}
    serialized = json_dumps(original)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    conn.execute('INSERT OR IGNORE INTO source_transfer_history VALUES (?,?,?,?)', (qid,digest,utc_now_iso(),serialized))
    for record in transfer.get('history', []):
        if not isinstance(record.get('original_records'), str) or record.get('question_id') != qid or hashlib.sha256(record['original_records'].encode()).hexdigest() != record.get('digest'):
            raise ValidationError('transfer history integrity mismatch')
        parse_timestamp(record.get('imported_at'), field_name='transfer imported_at')
        conn.execute('INSERT OR IGNORE INTO source_transfer_history VALUES (?,?,?,?)', (qid,record['digest'],record['imported_at'],record['original_records']))


def reverify_sources(ledger, question_id):
    """Re-fetch identical bytes. Do not backdate local verification to import claims."""
    from forecasting.applicability_facts import verified_archive
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = [dict(r) for r in conn.execute('SELECT * FROM transferred_source_archives WHERE evidence_id IN (SELECT id FROM evidence_items WHERE question_id=?)', (question_id,))]
    results = []
    for row in rows:
        if row['verification_status'] == 'locally_reverified':
            results.append(dict(evidence_id=row['evidence_id'], status='locally_reverified'))
            continue
        fetched = ledger.add_evidence(question_id=question_id, source_or_note=row['source_url'],
                                     metadata={'reverifies_evidence_id': row['evidence_id']})
        try:
            _, digest = verified_archive(fetched, row['source_url'])
            if digest != row['sha256']:
                raise ValidationError('canonical source changed; historical receipt cannot be locally verified')
            with ledger.transaction(immediate=True) as conn:
                conn.execute("UPDATE transferred_source_archives SET verification_status='locally_reverified', verified_at=? WHERE evidence_id=? AND sha256=?", (utc_now_iso(),row['evidence_id'],digest))
            results.append(dict(evidence_id=row['evidence_id'], status='locally_reverified'))
        except (ValidationError, OSError) as exc:
            results.append(dict(evidence_id=row['evidence_id'], status='imported', reason=str(exc)))
    return {'question_id': question_id, 'archives': results}
