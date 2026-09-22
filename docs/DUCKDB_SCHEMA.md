# DuckDB schema dump

DuckDB path: C:\Users\USER\Documents\EVKIN_ABSENSI_v1.5 update terbaru\EVKIN_ABSENSI_v1.5 diocode\backend\data\EVKIN_MASTER.duckdb

## Tables in database:

- absensi_hasil
- absensi_raw
- anomali
- audit_log
- bnba
- final_absensi
- final_combined_skp
- final_kombinasi
- final_skp
- hitung_harian
- import_batch
- master_data
- master_jabatan
- master_sdm
- master_tukin
- master_unit_kerja
- pengembalian_tukin
- pengembalian_uang_makan
- processing_jobs
- raw_import
- rekap_pengembalian
- rekap_sdm
- rekonsiliasi
- workflow_config
- workflow_flags
- workflow_meta


## Table: workflow_config

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | 0 | VARCHAR | False | None | False |


Row count: 1



## Table: master_data

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | nip | VARCHAR | False | None | False |

| 1 | nama | VARCHAR | False | None | False |

| 2 | jabatan | VARCHAR | False | None | False |

| 3 | tukin | BIGINT | False | None | False |


Row count: 1



## Table: raw_import

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: hitung_harian

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: rekap_sdm

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: final_absensi

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: anomali

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: final_skp

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: final_kombinasi

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0



## Table: final_combined_skp

| cid | name | type | notnull | default | pk |

|---:|---|---|---:|---|---:|

| 0 | _empty | VARCHAR | False | None | False |


Row count: 0
