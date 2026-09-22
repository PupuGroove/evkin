"""Period-keyed review of canonical SDM, approved SKP and attendance.

This projection never modifies approved assessments or historical payments.
Both the paginated screen and full Excel export use the same calculation.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import hashlib
import json
import re
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
import duckdb
import pandas as pd

from backend.shared_master import SharedMasterService
from backend.tukin_annual import PREDICATE_RATES


def number(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def money(value):
    return int(value.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def keyed(rows):
    counts = Counter(str(row.get('nip') or '').strip() for row in rows)
    return ({str(row.get('nip') or '').strip(): row for row in rows},
            {nip for nip, count in counts.items() if count > 1})


def resolve_gross(person, *sources):
    """Resolve the gross Tukin while keeping Master SDM as the preferred source."""
    master_source = person.get('_profile_source') if person else None
    candidates = [
        (master_source or 'MASTER SDM', person.get('tukin_gross') if person else None),
    ]
    for source_name, source in sources:
        if source:
            candidates.append((source_name, source.get('tukin_gross')))
            candidates.append((source_name, source.get('tukin')))
            candidates.append((source_name, source.get('tukinBruto')))
    valid = []
    for source_name, value in candidates:
        parsed = number(value)
        if parsed is not None and parsed >= 0:
            valid.append((parsed, source_name))
            if parsed > 0:
                return parsed, source_name
    if valid:
        return valid[0]
    return None, ''


def combine(master, attendance, assessments, history, period, conditions=()):
    attendance_map, attendance_duplicates = keyed(attendance)
    assessment_map, assessment_duplicates = keyed(assessments)
    history_map, history_duplicates = keyed(history)
    conditions_by_nip = {}
    for condition in conditions:
        conditions_by_nip.setdefault(str(condition.get('nip') or '').strip(), []).append(condition)
    output = []
    # Keep unmatched source NIPs visible as well as every canonical SDM.
    for nip in sorted(set(master) | set(attendance_map) | set(assessment_map) | set(history_map)):
        if not nip:
            continue
        person = master.get(nip, {})
        absence = attendance_map.get(nip)
        skp = assessment_map.get(nip)
        previous_skp = history_map.get(nip)
        issues = []
        gross, gross_source = resolve_gross(person, ('FINAL/HISTORI', absence), ('SKP', skp), ('HISTORI SKP', previous_skp))
        if not person:
            issues.append('NIP tidak ditemukan di Master SDM periode ini')
        if gross is None or gross < 0:
            gross = None
            issues.append('Tukin bruto belum valid')
        abs_rate = number(absence.get('potPct')) if absence else None
        if nip in attendance_duplicates:
            issues.append('NIP absensi duplikat'); abs_rate = None
        if abs_rate is None or not 0 <= abs_rate <= 100:
            abs_rate = None
            issues.append('Final Absensi belum tersedia/valid')
        predicate = ''
        skp_rate = None
        report_status = ''
        if nip in assessment_duplicates or nip in history_duplicates:
            issues.append('NIP penilaian SKP duplikat')
        elif skp and skp.get('review_status') == 'APPROVED':
            predicate = str(skp.get('final_predicate') or '').strip().upper()
            report_status = str(skp.get('report_status') or '')
            skp_rate = number(PREDICATE_RATES.get(predicate))
            # Verified non-submission/exception rules are calculated by the SKP
            # service, not inferred from a blank or '-' in an imported file.
            if report_status != 'SUBMITTED':
                skp_rate = number(previous_skp.get('skp_reduction_rate')) if previous_skp else None
        else:
            issues.append('SKP belum tersedia/disetujui')
        if skp_rate is None or not 0 <= skp_rate <= 100:
            skp_rate = None
            if 'SKP belum tersedia/disetujui' not in issues:
                issues.append('Predikat/aturan potongan SKP belum valid')
        abs_deduction = money(gross * Decimal('.30') * abs_rate / 100) if gross is not None and abs_rate is not None else None
        skp_deduction = money(gross * Decimal('.70') * skp_rate / 100) if gross is not None and skp_rate is not None else None
        # Recalculate from the canonical gross and percentages, never reweight
        # a previously weighted nominal attendance deduction.
        total = abs_deduction + skp_deduction if abs_deduction is not None and skp_deduction is not None else None
        eligible = person.get('eligible') is True
        unpaid = person.get('eligible') is False
        held = False
        skp_blocked = False
        if not eligible:
            issues.append(str(person.get('eligibility_reason') or (
                'Master SDM: tidak berhak Tukin' if person.get('eligible') is False
                else 'Kelayakan Master SDM periode ini belum tersedia')))
        if previous_skp and previous_skp.get('payment_eligible') is False:
            eligible = False
            skp_blocked = True
            issues.append('SKP: pembayaran ditahan/tidak memenuhi syarat')
        for condition in conditions_by_nip.get(nip, []):
            if (str(condition.get('nip') or '').strip() == nip
                    and condition.get('status') == 'APPROVED'
                    and condition.get('payment_effect') in {'HOLD','UNPAID'}):
                eligible = False
                unpaid = unpaid or condition.get('payment_effect') == 'UNPAID'
                held = held or condition.get('payment_effect') == 'HOLD'
                issues.append('Keputusan kondisi: ' + str(condition.get('payment_effect')) + ' — ' + str(condition.get('reason') or ''))
        complete = gross is not None and total is not None and not attendance_duplicates.intersection({nip}) and not assessment_duplicates.intersection({nip}) and not history_duplicates.intersection({nip})
        output.append({
            'assessment_period':period, 'nip':nip,
            'nama':person.get('nama') or (skp or absence or {}).get('nama') or '',
            'jabatan':person.get('jabatan') or '', 'unit':person.get('unit') or '',
            'tukin_gross':money(gross) if gross is not None else None,
            'tukin_gross_source': gross_source,
            'skp_component':money(gross * Decimal('.70')) if gross is not None else None,
            'attendance_component':money(gross * Decimal('.30')) if gross is not None else None,
            'predicate_skp':predicate.title(), 'report_status':report_status,
            'skp_rate':float(skp_rate) if skp_rate is not None else None,
            'attendance_rate':float(abs_rate) if abs_rate is not None else None,
            'skp_deduction':skp_deduction, 'attendance_deduction':abs_deduction,
            'total_deduction':total,
            'calculated_entitlement':max(0, money(gross)-total) if complete else None,
            'payable_estimate':max(0, money(gross)-total) if complete and eligible else None,
            'status':'LENGKAP' if complete and eligible else 'PERLU REVIEW',
            'data_complete':bool(complete), 'payment_block':'HOLD' if held else 'UNPAID' if unpaid else 'HOLD' if skp_blocked else '',
            'wilayah_3t':'3T' if person.get('wilayah_3t') is True else 'NON 3T' if person else '',
            'status_tendik':person.get('status_tendik') or '',
            'issues':'; '.join(issues), 'master_version':person.get('master_version'),
        })
    return output


def build(db_path, period):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', period):
        raise ValueError('Periode penilaian harus YYYY-MM')
    master = SharedMasterService(db_path).snapshot_map(period, fallback_latest_profile=True)
    with duckdb.connect(db_path) as conn:
        def read(table, period_column=None):
            exists = conn.execute('SELECT count(*) FROM information_schema.tables WHERE table_name=?', [table]).fetchone()[0]
            if not exists:
                return []
            columns = {row[0] for row in conn.execute(f'DESCRIBE "{table}"').fetchall()}
            if period_column and period_column not in columns:
                return []
            query = f'SELECT * FROM "{table}"'
            params = []
            if period_column:
                query += f' WHERE "{period_column}"=?'; params = [period]
            frame = conn.execute(query, params).fetchdf()
            return frame.astype(object).where(pd.notnull(frame), None).to_dict('records')
        raw_final = read('final_absensi')
        archived = read('tukin_final_monthly', 'assessment_period')
        assessments = read('skp_assessment_monthly', 'assessment_period')
        history = read('tukin_skp_monthly', 'assessment_period')
        conditions = read('skp_condition_decision', 'assessment_period')
        adjustments = read('tukin_combined_adjustment', 'assessment_period')
        periods = read('tukin_period', 'assessment_period')
        attendance = [{**row, '_source':'Final Absensi Workflow'} for row in raw_final if str(row.get('bulan') or row.get('monthKey') or '') == period]
        # Keep prior imported/saved monthly results for NIPs outside this
        # flexible workflow batch. Current matching-period rows take priority.
        live_nips = {str(row.get('nip') or '').strip() for row in attendance}
        attendance += [{**row, 'potPct':row.get('attendance_reduction_rate'), '_source':'Histori Absensi Bulanan'} for row in archived
                       if row.get('assessment_period') == period and str(row.get('nip') or '').strip() not in live_nips]
    rows = combine(master, attendance, assessments, history, period, conditions)
    source_map, _ = keyed(attendance)
    adjustment_map, _ = keyed(adjustments)
    archived_map, _ = keyed(archived)
    assessment_sources = {}
    condition_sources = {}
    for item in assessments:
        assessment_sources.setdefault(str(item.get('nip') or '').strip(), []).append(item)
    for item in conditions:
        condition_sources.setdefault(str(item.get('nip') or '').strip(), []).append(item)
    for row in rows:
        source = source_map.get(row['nip'])
        row['attendance_participant'] = source is not None
        row['workflow_participant'] = row['nip'] in live_nips
        row['attendance_source'] = source.get('_source', '') if source else ''
        # Include approved source records so a changed decision requires review,
        # even when it happens to produce the same monetary result.
        row['source_fingerprint'] = fingerprint([row, source,
            sorted(assessment_sources.get(row['nip'], []), key=lambda r: fingerprint([r])),
            sorted(condition_sources.get(row['nip'], []), key=lambda r: fingerprint([r]))])
        apply_adjustment(row, adjustment_map.get(row['nip']))
        row['period_status'] = periods[0].get('status') if periods else 'DRAFT'
        row['period_locked'] = row['period_status'] in {'LOCKED','HISTORICAL_LOCKED','PAID'} or (archived_map.get(row['nip']) or {}).get('payment_status') in {'PAID','LOCKED','HISTORICAL_LOCKED'}
    return rows


def apply_adjustment(row, adjustment=None):
    row.update(manual_adjustment=0, adjustment_reason='', adjustment_actor='',
               adjustment_stale=False, final_tukin=row['payable_estimate'],
               payment_status='SIAP DIREVIEW' if row['payable_estimate'] is not None else 'BELUM LENGKAP / DITAHAN')
    if row.get('data_complete') and row.get('payment_block') == 'UNPAID':
        row.update(final_tukin=0, payment_status='TIDAK DIBAYARKAN')
    elif row.get('payment_block') == 'HOLD':
        row['payment_status'] = 'DITAHAN'
    if not adjustment:
        return
    amount = number(adjustment.get('amount'))
    row.update(manual_adjustment=float(amount) if amount is not None else None,
               adjustment_reason=adjustment.get('reason', ''), adjustment_actor=adjustment.get('actor', ''))
    if amount == 0:
        return  # An audited cancellation must not hold later calculations.
    stale = adjustment.get('source_fingerprint') != row['source_fingerprint']
    final = number(row['payable_estimate'])
    final = final + amount if final is not None and amount is not None else None
    if stale or final is None or not 0 <= final <= row['tukin_gross']:
        row.update(adjustment_stale=True, final_tukin=None, status='PERLU REVIEW', payment_status='PENYESUAIAN PERLU REVIEW')
        row['issues'] = '; '.join(filter(None, [row['issues'], 'Periksa ulang penyesuaian: sumber berubah atau nominal tidak valid']))
    else:
        row['final_tukin'] = money(final)


def select_scope(rows, scope):
    if scope not in {'workflow', 'attendance', 'all'}:
        raise ValueError('Cakupan harus workflow, attendance atau all')
    if scope == 'workflow':
        return [row for row in rows if row.get('workflow_participant')]
    return [row for row in rows if row.get('attendance_participant')] if scope == 'attendance' else rows


def ensure_adjustment_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS tukin_combined_adjustment (
        assessment_period VARCHAR, nip VARCHAR, amount BIGINT, reason VARCHAR, actor VARCHAR,
        source_fingerprint VARCHAR, updated_at TIMESTAMP DEFAULT now(),
        PRIMARY KEY (assessment_period, nip))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS tukin_combined_adjustment_audit (
        id VARCHAR PRIMARY KEY, assessment_period VARCHAR, nip VARCHAR,
        old_value VARCHAR, new_value VARCHAR, actor VARCHAR, created_at TIMESTAMP DEFAULT now())''')


def save_adjustment(db_path, payload):
    period = str(payload.get('assessment_period') or '')
    nip = str(payload.get('nip') or '').strip()
    amount = number(payload.get('amount'))
    actor = str(payload.get('actor') or '').strip()
    reason = str(payload.get('reason') or '').strip()
    if amount is None or amount != amount.to_integral_value() or not actor or not reason:
        raise ValueError('Nominal harus rupiah bulat; petugas dan alasan wajib diisi')
    if len(actor) > 150 or len(reason) > 2000:
        raise ValueError('Nama petugas maksimal 150 dan alasan maksimal 2000 karakter')
    # Runtime DATABASE_GATE serializes this operation with source changes.
    # Adjustment and audit are committed atomically.
    with duckdb.connect(db_path) as conn:
        ensure_adjustment_schema(conn)
        conn.execute('BEGIN TRANSACTION')
        try:
            has_periods = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='tukin_period'").fetchone()[0]
            lock = conn.execute('SELECT status FROM tukin_period WHERE assessment_period=?', [period]).fetchone() if has_periods else None
            if lock and lock[0] in {'LOCKED', 'HISTORICAL_LOCKED', 'PAID'}:
                raise ValueError('Periode terkunci atau sudah dibayar')
            row = next((r for r in build(db_path, period) if r['nip'] == nip), None)
            cancelling = row and amount == 0 and bool(row['adjustment_reason'])
            if not row or not row['attendance_participant'] or (row['payable_estimate'] is None and not cancelling):
                raise ValueError('Penyesuaian memerlukan peserta absensi dengan Master dan SKP lengkap serta layak dibayar')
            if row['period_locked']:
                raise ValueError('Hasil bulanan terkunci atau sudah dibayar')
            if payload.get('expected') != fingerprint([row]):
                raise ValueError('Data berubah. Hitung Gabungan kembali sebelum menyimpan penyesuaian')
            final = Decimal(row['payable_estimate']) + amount if row['payable_estimate'] is not None else None
            if not cancelling and (final is None or not 0 <= final <= row['tukin_gross']):
                raise ValueError('Final setelah penyesuaian harus antara nol dan Tukin bruto')
            old = conn.execute('SELECT amount,reason,actor,source_fingerprint FROM tukin_combined_adjustment WHERE assessment_period=? AND nip=?', [period,nip]).fetchone()
            old = dict(zip(['amount','reason','actor','source_fingerprint'], old)) if old else None
            new = {'amount':int(amount), 'reason':reason, 'actor':actor, 'source_fingerprint':row['source_fingerprint']}
            conn.execute('''INSERT INTO tukin_combined_adjustment VALUES (?,?,?,?,?,?,now())
                ON CONFLICT (assessment_period,nip) DO UPDATE SET amount=excluded.amount,
                reason=excluded.reason,actor=excluded.actor,source_fingerprint=excluded.source_fingerprint,updated_at=now()''',
                [period,nip,int(amount),reason,actor,row['source_fingerprint']])
            conn.execute('INSERT INTO tukin_combined_adjustment_audit VALUES (?,?,?,?,?,?,now())',
                [str(uuid.uuid4()),period,nip,json.dumps(old,default=str),json.dumps(new),actor])
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
    return {'status':'ok'}


def fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')).hexdigest()


COLUMNS = {
    'assessment_period':'Periode Penilaian', 'nip':'NIP', 'nama':'Nama', 'jabatan':'Jabatan', 'unit':'Unit',
    'tukin_gross':'Tukin Bruto', 'skp_component':'Komponen SKP 70%', 'attendance_component':'Komponen Absensi 30%',
    'predicate_skp':'Predikat SKP', 'report_status':'Status Laporan SKP', 'skp_rate':'Potongan SKP (%)',
    'attendance_rate':'Potongan Absensi (%)', 'skp_deduction':'Nominal Potongan SKP',
    'attendance_deduction':'Nominal Potongan Absensi', 'total_deduction':'Total Potongan',
    'calculated_entitlement':'Hasil Perhitungan', 'payable_estimate':'Estimasi Dibayar',
    'status':'Kelengkapan', 'issues':'Perlu Diperiksa', 'master_version':'Versi Master',
    'attendance_source':'Sumber Absensi', 'manual_adjustment':'Penyesuaian (Rp)',
    'adjustment_reason':'Alasan Penyesuaian', 'adjustment_actor':'Petugas Penyesuaian',
    'final_tukin':'Final Dasar Tukin', 'tukin_gross_source':'Sumber Tukin Bruto',
    'payment_status':'Status Pembayaran / Review',
    'wilayah_3t':'Wilayah 3T', 'status_tendik':'Status Tendik', 'period_status':'Status Periode',
}


def create_router(db_path_getter):
    router = APIRouter(prefix='/api/tukin/combined', tags=['tukin-combined'])

    @router.get('')
    def preview(assessment_period: str, page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=500), q: str = '', scope: str = 'all'):
        try:
            rows = select_scope(build(db_path_getter(), assessment_period), scope)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        summary = {'total':len(rows), 'complete':sum(row['status']=='LENGKAP' for row in rows),
                   'review':sum(row['status']!='LENGKAP' for row in rows)}
        filtered = [row for row in rows if not q or q.lower() in (row['nip']+' '+str(row['nama'])).lower()]
        start = (page-1)*per_page
        visible = [{**row, 'edit_token':fingerprint([row])} for row in filtered[start:start+per_page]]
        return {'rows':visible, 'total':len(filtered), 'summary':summary, 'page':page,
                'fingerprint':fingerprint(rows), 'scope':scope}

    @router.post('/adjustment')
    def adjust(payload: dict):
        try:
            return save_adjustment(db_path_getter(), payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get('/adjustment/audit')
    def adjustment_audit(assessment_period: str, nip: str):
        with duckdb.connect(db_path_getter()) as conn:
            if not conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='tukin_combined_adjustment_audit'").fetchone()[0]:
                return {'rows':[]}
            data = conn.execute('''SELECT old_value,new_value,actor,created_at
                FROM tukin_combined_adjustment_audit WHERE assessment_period=? AND nip=?
                ORDER BY created_at DESC''', [assessment_period,nip]).fetchall()
        return {'rows':[{'old_value':json.loads(r[0]),'new_value':json.loads(r[1]),'actor':r[2],'created_at':str(r[3])} for r in data]}

    @router.get('/export')
    def export(assessment_period: str, expected: str = '', scope: str = 'all'):
        try:
            rows = select_scope(build(db_path_getter(), assessment_period), scope)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if expected and expected != fingerprint(rows):
            raise HTTPException(409, 'Data berubah setelah tampilan dimuat. Klik Hitung Gabungan lagi sebelum ekspor.')
        output = io.BytesIO()
        frame = pd.DataFrame(rows, columns=COLUMNS).rename(columns=COLUMNS)
        with pd.ExcelWriter(output, engine='xlsxwriter', engine_kwargs={'options':{'strings_to_formulas':False, 'strings_to_urls':False}}) as writer:
            frame.to_excel(writer, sheet_name='Gabungan SKP Absensi', index=False)
            sheet = writer.sheets['Gabungan SKP Absensi']
            sheet.freeze_panes(1, 3)
            sheet.autofilter(0, 0, len(rows), len(COLUMNS)-1)
            sheet.set_column(0, 1, 22); sheet.set_column(2, 4, 30); sheet.set_column(5, 18, 23)
            sheet.set_column(18, 18, 65)
            sheet.set_column(20, len(COLUMNS)-1, 26)
            numeric_format = writer.book.add_format({'num_format':'#,##0'})
            for key in ['tukin_gross','skp_component','attendance_component','skp_deduction','attendance_deduction','total_deduction','calculated_entitlement','payable_estimate','manual_adjustment','final_tukin']:
                col = list(COLUMNS).index(key)
                sheet.set_column(col, col, 23, numeric_format)
        output.seek(0)
        return StreamingResponse(output, media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            headers={'Content-Disposition':f'attachment; filename="REVIEW_GABUNGAN_{assessment_period}.xlsx"'})
    return router
