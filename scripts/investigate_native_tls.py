#!/usr/bin/env python3
"""Discriminating native TLS experiment, run only in a disposable Linux worker.

Each case gets a fresh interpreter. GDB captures native stacks and a core on
SIGSEGV/SIGABRT; the synthetic abort validates capture, not the TLS hypothesis.
No network, credentials, or forecast profile are used by the experiment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import ssl
import subprocess
import sys
import threading
import time


MODES = ('serial', 'concurrent', 'environment', 'environment-unset',
         'explicit-ca-environment', 'explicit-ca-environment-unset', 'shutdown')


def workload(mode, cafile):
    if mode == 'capture-selftest':
        os.abort()
    barrier = threading.Barrier(5)
    entered = threading.Event()
    stop = threading.Event()
    counts = {'contexts': 0, 'mutations': 0}
    count_lock = threading.Lock()
    unset = mode.endswith('-unset')
    if unset:
        # Prepopulate before any TLS initialization: this case isolates removal
        # and pointer shifting from growth/reallocation of the environ array.
        for i in range(10000):
            os.environ[f'FORECAST_TLS_REPRO_{i}'] = 'x' * 64

    def contexts():
        if mode == 'concurrent':
            barrier.wait(timeout=10)
        for _ in range(200):
            entered.set()
            # Explicit CA is a control for OpenSSL's default-path getenv calls.
            ctx = ssl.create_default_context(cafile=cafile if mode.startswith('explicit-ca-') else None)
            ctx.cert_store_stats()
            with count_lock:
                counts['contexts'] += 1

    def mutate():
        if not entered.wait(10):
            raise RuntimeError('TLS initialization did not overlap mutation')
        for i in range(10000):
            if stop.is_set():
                break
            if unset:
                os.environ.pop(f'FORECAST_TLS_REPRO_{i}', None)
            else:
                # Monotonic growth keeps testing reallocation; a bounded rolling
                # window only grows before most certificate calls have started.
                os.environ[f'FORECAST_TLS_REPRO_{i}'] = 'x' * 64
            counts['mutations'] += 1
            time.sleep(0)  # Let certificate loading overlap throughout the case.

    if mode == 'concurrent':
        workers = [threading.Thread(target=contexts) for _ in range(4)]
        for worker in workers:
            worker.start()
        barrier.wait(timeout=10)
        for worker in workers:
            worker.join()
    elif 'environment' in mode:
        worker = threading.Thread(target=mutate)
        worker.start()
        try:
            contexts()
        finally:
            stop.set()
            worker.join()
    elif mode == 'shutdown':
        threading.Thread(target=contexts, daemon=True).start()
        if not entered.wait(10):
            raise RuntimeError('TLS worker did not start')
        # Normal interpreter finalization with certificate loading in flight.
    else:
        contexts()
    print('WORKLOAD ' + json.dumps(counts), flush=True)
    if 'environment' in mode and not counts['mutations']:
        raise RuntimeError('Mutation case did not perform any mutations')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', choices=(*MODES, 'capture-selftest'))
    parser.add_argument('--cafile', default='/etc/ssl/certs/ca-certificates.crt')
    parser.add_argument('--output', type=Path, default=Path('native-tls-results'))
    args = parser.parse_args()
    if args.worker:
        workload(args.worker, args.cafile)
        return
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        parser.error('requires native Linux x86-64; do not substitute emulation')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    import _ssl
    # python-build-standalone can embed _ssl in the interpreter itself.
    ssl_extension = getattr(_ssl, '__file__', None)
    ssl_binary = ssl_extension or sys.executable
    report = {
        'python': sys.version, 'executable': sys.executable,
        'platform': platform.platform(), 'libc': platform.libc_ver(),
        'openssl': ssl.OPENSSL_VERSION, 'ssl_extension': ssl_extension,
        'ssl_binary': ssl_binary,
        'runner_image': os.environ.get('ImageVersion'),
        'original_runner_image': '20260907.300.1',
        'original_bundle_hash': None,
        'certificate_paths': ssl.get_default_verify_paths()._asdict(),
        'sha256': {}, 'cases': [],
    }
    for name, path in [('python', sys.executable), ('ssl', ssl_binary), ('ca', args.cafile)]:
        report['sha256'][name] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    (out / 'ca-certificates.crt').write_bytes(Path(args.cafile).read_bytes())
    (out / 'package-versions.txt').write_text(subprocess.check_output(
        ['dpkg-query', '-W', 'libc6', 'openssl', 'ca-certificates', 'gdb'], text=True))
    (out / 'linked-libraries.txt').write_text(subprocess.check_output(['ldd', ssl_binary], text=True))
    # Exceptions in worker threads must fail the case, rather than print a
    # traceback and let the interpreter report success.
    child_home = out / 'isolated-home'
    child_home.mkdir(exist_ok=True)
    child_env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(child_home), 'LANG': 'C.UTF-8'}
    for mode in ('capture-selftest', *MODES):
        core = out / f'{mode}.core'
        gdb_commands = out / f'{mode}.gdb'
        gdb_commands.write_text(
            'set pagination off\nset confirm off\nset print thread-events off\n'
            'handle SIGSEGV stop print nopass\nhandle SIGABRT stop print nopass\n'
            'run\nthread apply all bt full\ninfo sharedlibrary\n'
            f'generate-core-file {core}\nquit\n'
        )
        command = ['gdb', '--batch', '-x', str(gdb_commands), '--args', sys.executable,
                   '-X', 'faulthandler', str(Path(__file__).resolve()), '--worker', mode, '--cafile', args.cafile]
        try:
            child = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, env=child_env)
            try:
                stdout, stderr = child.communicate(timeout=90)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                raise
            log = stdout + stderr
            crashed = 'Program received signal' in log or 'received signal SIG' in log
            clean = 'exited normally' in log
            counts = next((json.loads(line.removeprefix('WORKLOAD '))
                           for line in log.splitlines() if line.startswith('WORKLOAD ')), None)
            case = {'mode': mode, 'gdb_exit': child.returncode, 'crashed': crashed,
                    'clean_exit': clean, 'core_captured': core.exists(), 'workload': counts}
        except subprocess.TimeoutExpired as exc:
            log = str(exc.stdout) + str(exc.stderr)
            case = {'mode': mode, 'timeout': True, 'core_captured': core.exists()}
        (out / f'{mode}.log').write_text(log)
        report['cases'].append(case)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(case), flush=True)
    if not report['cases'][0]['core_captured']:
        raise SystemExit('Native capture self-test failed')
    if any(not case.get('clean_exit') for case in report['cases'][1:]):
        raise SystemExit('One or more experiments crashed or were inconclusive; inspect artifacts')


if __name__ == '__main__':
    def fail_thread(args):
        import traceback
        traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)
        os._exit(2)
    threading.excepthook = fail_thread
    main()
