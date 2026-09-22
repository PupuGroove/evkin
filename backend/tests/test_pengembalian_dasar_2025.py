from io import BytesIO

import duckdb
import pytest
from openpyxl import Workbook

from backend.pengembalian_dasar_2025 import DasarPengembalian2025Service, PERIODE_ID, SOURCE_TYPE
from backend.pengembalian_archive import ArchiveService
from backend.pengembalian_progress import ProgressService


HEADERS = ["NIP","Nama","Provinsi","Kabupaten/Kota","Tahun SP2D","Nama Bank","Nomor Rekening",
    "Final Oktober","Final November","Final Desember","Final Total Pengembalian","Send Tahap I",
    "Debit Tahap I 2025","NTPN Tahap I 2025","Gagal Tahap I","Keterangan Gagal Tahap I",
    "Send Tahap II","Debit Tahap II 2025","NTPN Tahap II 2025","Send Tahap III",
    "Debit Tahap III 2025","NTPN Tahap III 2025","Send Tahap IV","Debit Tahap IV2025",
    "NTPN Tahap IV 2025","Total Progress 2025","Sisa Kewajiban","Status Progress",
    "Status Master","Batch BPK","Kode Anak Satker"]


def workbook(year=2025, total=600, stages=(100,100,100,300), reference_total=None,
             reference_remaining=None, add_stage_five=False, second_row=False):
    wb=Workbook();ws=wb.active;ws.title="BNBA PROGRESS"
    ws.append(["Judul"]);ws.append(["Periode Oktober November Desember 2025"]);ws.append([])
    headers=list(HEADERS)
    if add_stage_five: headers += ["Send Tahap V","Debit Tahap V 2025","NTPN Tahap V 2025"]
    ws.append(headers)
    def values(nip="199001012025211001"):
        progress=sum(stages) + (50 if add_stage_five else 0)
        result=[nip,"PEGAWAI","JAWA BARAT","KAB. BANDUNG",year,"BANK MANDIRI","123456",
            100,200,300,total,stages[0],stages[0],"N1",0,None,stages[1],stages[1],"N2",
            stages[2],stages[2],"N3",stages[3],stages[3],"N4",
            progress if reference_total is None else reference_total,
            max(total-progress,0) if reference_remaining is None else reference_remaining,
            "SUMBER SAJA","PENGEMBALIAN","BATCH 1 SEND BPK","P6"]
        if add_stage_five: result += [50,50,"N5"]
        return result
    ws.append(values())
    if second_row: ws.append(values("199001012025211002"))
    stream=BytesIO();wb.save(stream);return stream.getvalue()


def service(tmp_path):
    return DasarPengembalian2025Service(tmp_path/"dasar.duckdb")


def test_valid_preview_is_read_only_and_maps_months_and_dynamic_stages(tmp_path):
    svc=service(tmp_path);content=workbook(add_stage_five=True)
    conn=duckdb.connect(svc.db_path)
    before=[conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
            ("pengembalian_archive_import","pengembalian_master_obligation","pengembalian_progress_transaction")]
    conn.close()
    preview=svc.preview(content,"dasar.xlsx")
    assert preview["valid"] is True
    assert preview["source_type"] == SOURCE_TYPE
    assert preview["summary"]["total_oktober"] == 100
    assert preview["summary"]["total_november"] == 200
    assert preview["summary"]["total_desember"] == 300
    assert preview["summary"]["progress_per_tahap"] == {"1":1,"2":1,"3":1,"4":1,"5":1}
    conn=duckdb.connect(svc.db_path)
    after=[conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
           ("pengembalian_archive_import","pengembalian_master_obligation","pengembalian_progress_transaction")]
    conn.close();assert after == before


def test_commit_stores_obligation_progress_and_immutable_archive(tmp_path):
    svc=service(tmp_path);content=workbook()
    result=svc.commit(content,"dasar.xlsx","tester")
    assert result["obligations"] == 1 and result["transactions"] == 4
    conn=duckdb.connect(svc.db_path)
    obligation=conn.execute("""SELECT tahun_sp2d,final_tukin,final_uang_makan,final_total,
        sumber_sp2d,source_import_id FROM pengembalian_master_obligation""").fetchone()
    assert obligation[:5] == (2025,600,0,600,SOURCE_TYPE)
    stages=conn.execute("SELECT tahap,nominal_debit_tukin,ntpn FROM pengembalian_progress_transaction ORDER BY tahap").fetchall()
    assert stages == [(1,100,"N1"),(2,100,"N2"),(3,100,"N3"),(4,300,"N4")]
    archive=conn.execute("""SELECT source_type,source_row,tukin_pengembalian_oktober,tukin_pengembalian_november,
        tukin_pengembalian_desember,total_potongan_tukin FROM pengembalian_archive_data_awal""").fetchone()
    assert archive == (SOURCE_TYPE,5,100,200,300,600)
    conn.close()
    history=ArchiveService(svc.db_path).list("DATA_AWAL",{"import_id":obligation[5]})
    assert len(history)==1 and history[0]["nip"]=="199001012025211001"


def test_duplicate_file_does_not_duplicate_obligation_or_ledger(tmp_path):
    svc=service(tmp_path);content=workbook();svc.commit(content,"dasar.xlsx")
    assert svc.preview(content,"copy.xlsx")["duplicate_file"] is not None
    with pytest.raises(ValueError,match="SUDAH_PERNAH"):
        svc.commit(content,"copy.xlsx")
    conn=duckdb.connect(svc.db_path)
    assert conn.execute("SELECT count(*) FROM pengembalian_master_obligation").fetchone()[0]==1
    assert conn.execute("SELECT count(*) FROM pengembalian_progress_transaction").fetchone()[0]==4
    conn.close()


@pytest.mark.parametrize("content,error",[
    (workbook(year=2026),"TAHUN_SP2D_BUKAN_2025"),
    (workbook(total=601),"FINAL_TOTAL_TIDAK_COCOK"),
])
def test_wrong_year_and_total_mismatch_are_rejected_without_partial_commit(tmp_path,content,error):
    svc=service(tmp_path);preview=svc.preview(content,"invalid.xlsx")
    assert preview["valid"] is False
    assert error in str(preview["errors"])
    with pytest.raises(ValueError,match="IMPORT_TIDAK_VALID"):
        svc.commit(content,"invalid.xlsx")
    conn=duckdb.connect(svc.db_path)
    assert conn.execute("SELECT count(*) FROM pengembalian_archive_import").fetchone()[0]==0
    assert conn.execute("SELECT count(*) FROM pengembalian_progress_transaction").fetchone()[0]==0
    conn.close()


def test_derived_source_fields_never_override_calculated_progress_and_overpayment(tmp_path):
    svc=service(tmp_path);content=workbook(stages=(300,300,300,0),reference_total=1,reference_remaining=999)
    preview=svc.preview(content,"over.xlsx")
    assert preview["valid"] is True and preview["summary"]["jumlah_overpayment"] == 1
    assert "TOTAL_PROGRESS_REFERENSI_TIDAK_COCOK" in str(preview["warnings"])
    svc.commit(content,"over.xlsx")
    progress=ProgressService(svc.db_path).progress({"periode_id":PERIODE_ID},limit=10)["rows"][0]
    assert progress["kelebihan_bayar"] == 300
    assert progress["total_sisa_piutang"] == 0


def test_existing_archive_importer_remains_usable(tmp_path):
    svc=service(tmp_path)
    archive=ArchiveService(svc.db_path)
    result=archive.import_rows([{"NIP":"100","Tahun SP2D":2025,"Periode":"2025-01",
        "Komponen":"TUKIN","Total Tukin":100}],"DATA_AWAL",{"periode_id":"EXISTING"})
    assert result["status"] == "ok"
