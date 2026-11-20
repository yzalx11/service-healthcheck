"""Run a disposable Redis, worker and beat against the real Django tasks."""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime, time as daytime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CHILD_SETUP = """
import os
from pathlib import Path
from healthcheck import settings
settings.DATABASES["default"]["NAME"] = Path(os.environ["HEALTHCHECK_TEST_DB"])
"""


def launch(stack, workspace, name, arguments, env):
    output = stack.enter_context((workspace / f"{name}.log").open("w", encoding="utf-8"))
    process = subprocess.Popen(
        arguments, cwd=workspace, env=env, stdout=output, stderr=subprocess.STDOUT
    )
    stack.callback(stop, process)
    return process


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_until(predicate, processes, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for name, process in processes.items():
            if process.poll() is not None:
                raise RuntimeError(f"{name} exited with status {process.returncode}")
        if predicate():
            return
        time.sleep(0.25)
    raise TimeoutError("The Celery chain did not complete before the timeout.")


def verify(redis_server):
    from cryptography.fernet import Fernet
    from redis import Redis
    from redis.exceptions import ConnectionError

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    with tempfile.TemporaryDirectory(prefix="healthcheck-chain-") as temp:
        workspace = Path(temp)
        key = Fernet.generate_key()
        env = os.environ.copy()
        env.update(
            PYTHONPATH=str(ROOT),
            PYTHONUNBUFFERED="1",
            DJANGO_SETTINGS_MODULE="healthcheck.settings",
            HEALTHCHECK_TEST_DB=str(workspace / "acceptance.sqlite3"),
            CELERY_BROKER_URL=f"redis://127.0.0.1:{port}/0",
            PROBE_TOKEN_ENCRYPTION_KEY=key.decode("ascii"),
        )
        os.environ.update({name: env[name] for name in (
            "DJANGO_SETTINGS_MODULE", "CELERY_BROKER_URL", "PROBE_TOKEN_ENCRYPTION_KEY",
        )})

        import django
        from django.core.management import call_command
        from django.db import connections
        from django.utils import timezone
        from healthcheck import settings

        settings.DATABASES["default"]["NAME"] = workspace / "acceptance.sqlite3"
        django.setup()

        from inspection.models import DailyHealthRate, Environment, InspectionResult, Service, Team

        try:
            call_command("migrate", verbosity=0)
            service = Service.objects.create(
                name="chain-test",
                environment=Environment.objects.create(name="test"),
                team=Team.objects.create(name="Acceptance"),
                origin="http://127.0.0.1:9001",
            )
            yesterday = timezone.localdate() - timedelta(days=1)
            sample_time = datetime.combine(yesterday, daytime(12), timezone.get_default_timezone())
            for outcome in (InspectionResult.Outcome.HEALTHY, InspectionResult.Outcome.TIMEOUT):
                result = InspectionResult.objects.create(service=service, outcome=outcome, duration_ms=10)
                InspectionResult.objects.filter(pk=result.pk).update(checked_at=sample_time)

            def verify_database():
                service.refresh_from_db()
                report = DailyHealthRate.objects.filter(service=service, date=yesterday).first()
                if not service.token_ciphertext or report is None:
                    return False
                assert len(Fernet(key).decrypt(service.token_ciphertext)) == 43
                assert (report.successful_checks, report.total_checks, report.health_rate) == (1, 2, 0.5)
                return True

            with ExitStack() as stack:
                redis_process = launch(stack, workspace, "redis", [
                    redis_server, "--bind", "127.0.0.1", "--port", str(port),
                    "--save", "", "--appendonly", "no",
                ], env)
                client = stack.enter_context(Redis(host="127.0.0.1", port=port, protocol=2))

                def redis_ready():
                    try:
                        return client.ping()
                    except ConnectionError:
                        return False

                processes = {"redis": redis_process}
                wait_until(redis_ready, processes, timeout=10)
                processes["worker"] = launch(stack, workspace, "worker", [
                    sys.executable, "-c", CHILD_SETUP + """
from healthcheck.celery import app
app.worker_main(["worker", "--pool=solo", "--loglevel=INFO", "--without-mingle",
                 "--without-gossip", "--without-heartbeat"])
""",
                ], env)
                processes["beat"] = launch(stack, workspace, "beat", [
                    sys.executable, "-c", CHILD_SETUP + """
from datetime import timedelta
from healthcheck.celery import app
for entry in app.conf.beat_schedule.values():
    entry["schedule"] = timedelta(seconds=2)
app.start(["beat", "--loglevel=INFO", "--max-interval=1"])
""",
                ], env)
                wait_until(verify_database, processes)
                print("PASS: beat -> Redis -> worker -> database (Token rotation and daily health rate)")
        except Exception:
            for log in sorted(workspace.glob("*.log")):
                print(f"--- {log.name} ---", file=sys.stderr)
                print(log.read_text(encoding="utf-8", errors="replace")[-6000:], file=sys.stderr)
            raise
        finally:
            connections.close_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redis-server", required=True, type=lambda value: Path(value).resolve(strict=True))
    verify(str(parser.parse_args().redis_server))
