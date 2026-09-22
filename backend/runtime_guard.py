"""One server per database; one in-process database operation at a time."""
import atexit
import asyncio
import functools
import os
from pathlib import Path
import threading

DATABASE_GATE = threading.Lock()
_owners = {}
_reset_in_progress = False
_reset_epoch = 0


def claim_database(path):
    key = str(Path(path).resolve()).casefold()
    if key in _owners:
        return
    lock_path = Path(str(Path(path).resolve()) + '.server.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, 'a+b')
    try:
        if lock_path.stat().st_size == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError('Database sudah dimiliki backend lain. Gunakan server EVKIN yang sudah aktif; jangan jalankan server kedua.') from exc
    _owners[key] = handle


@atexit.register
def release_databases():
    for handle in _owners.values():
        handle.close()
    _owners.clear()


def database_job(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        with DATABASE_GATE:
            return function(*args, **kwargs)
    return run


async def serialize_database_requests(request, call_next):
    global _reset_in_progress, _reset_epoch
    request_epoch = _reset_epoch
    if _reset_in_progress and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail': 'Reset aplikasi sedang berlangsung. Tunggu lalu muat ulang halaman.'}, status_code=409)
    if request.scope.get('evkin_database_gate'):
        return await call_next(request)
    path = request.url.path
    # Polling/health and job dispatch use SQLite only and must stay responsive
    # while a DuckDB job owns the gate. Export download is an immutable file.
    exempt = (path in {'/health', '/api/health', '/api/info', '/api/ping', '/', '/index.html'}
              or path.startswith('/assets/') or path.startswith('/api/jobs')
              or path == '/api/compute/harians')
    if exempt:
        return await call_next(request)
    while not DATABASE_GATE.acquire(blocking=False):
        await asyncio.sleep(.05)
    try:
        if request_epoch != _reset_epoch and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail': 'Reset terjadi saat permintaan menunggu. Muat ulang halaman sebelum mengubah data.'}, status_code=409)
        request.scope['evkin_database_gate'] = True
        is_reset = path == '/api/admin/reset-operational/confirm'
        if is_reset:
            _reset_in_progress = True
            _reset_epoch += 1
        return await call_next(request)
    finally:
        if path == '/api/admin/reset-operational/confirm':
            _reset_in_progress = False
        DATABASE_GATE.release()
