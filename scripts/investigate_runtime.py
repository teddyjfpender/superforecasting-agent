#!/usr/bin/env python3
"""Bounded stdlib reproductions. Run with the affected Python in an isolated process.

No credentials, network requests or live profiles. JSON records platform/library
identity and subprocess outcomes; a clean stress run is not proof of absence.
"""
import concurrent.futures
import json
import os
import platform
import signal
import sqlite3
import ssl
import subprocess
import sys
import threading


def tls_worker():
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: ssl.create_default_context().cert_store_stats(), range(int(os.environ.get('FORECAST_REPRO_CALLS', '80')))))


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == 'tls':
            tls_worker()
        elif sys.argv[1] == 'environment':
            stop = threading.Event()
            def mutate_environment():
                for index in range(10000):
                    if stop.is_set():
                        return
                    key = 'FORECAST_REPRO_' + str(index)
                    os.environ[key] = 'x' * 80
                    if index > 100:
                        os.environ.pop('FORECAST_REPRO_' + str(index - 100), None)
            worker = threading.Thread(target=mutate_environment)
            worker.start()
            try:
                tls_worker()
            finally:
                stop.set()
                worker.join()
        elif sys.argv[1] == 'shutdown':
            started = threading.Event()
            def background():
                started.set()
                tls_worker()
            threading.Thread(target=background, daemon=True).start()
            started.wait(2)
        return
    report = dict(python=sys.version, platform=platform.platform(), openssl=ssl.OPENSSL_VERSION,
                  sqlite=sqlite3.sqlite_version, certificates=ssl.get_default_verify_paths()._asdict(), runs=[])
    for mode in ('tls', 'shutdown', 'environment'):
        for index in range(int(os.environ.get('FORECAST_REPRO_REPEATS', '8'))):
            try:
                result = subprocess.run([sys.executable, '-X', 'faulthandler', __file__, mode],
                                        capture_output=True, text=True, timeout=25)
                report['runs'].append(dict(mode=mode, index=index, exit=result.returncode, stderr=result.stderr[-8000:]))
            except subprocess.TimeoutExpired:
                report['runs'].append(dict(mode=mode, index=index, timeout=True))
    if hasattr(signal, 'SIGALRM'):
        class Deadline(BaseException):
            pass
        def interrupt(*_):
            raise Deadline('real SIGALRM inside authorizer')
        old = signal.signal(signal.SIGALRM, interrupt)
        with sqlite3.connect(':memory:') as conn:
            def authorizer(*_):
                signal.raise_signal(signal.SIGALRM)
                return sqlite3.SQLITE_OK
            conn.set_authorizer(authorizer)
            try:
                conn.execute('SELECT 1')
            except BaseException as exc:
                report['sqlite_signal_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            finally:
                conn.set_authorizer(None)
        # Load the exact connection implementation without importing the app
        # or needing third-party packages in the reproduction container.
        import importlib.util
        from pathlib import Path
        source = Path(__file__).resolve().parents[1] / 'forecasting/ledger/sqlite_runtime.py'
        if source.is_file():
            spec = importlib.util.spec_from_file_location('ledger_sqlite_runtime', source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            conn = sqlite3.connect(':memory:', factory=module.LedgerConnection)
            conn.set_authorizer(authorizer)
            try:
                conn.execute('SELECT 1')
            except BaseException as exc:
                report['sqlite_fixed_signal_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            finally:
                conn.set_authorizer(None)
            report['sqlite_fixed_reusable'] = conn.execute('SELECT 1').fetchone()[0] == 1
            conn.close()
        signal.signal(signal.SIGALRM, old)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
