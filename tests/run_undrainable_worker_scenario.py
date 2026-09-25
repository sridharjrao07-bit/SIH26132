import os
import sys
import threading
import time

from tests.test_forecast_lease import pg_concurrency_context


def main():
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        sys.exit("SUPABASE_DB_URL not in environment")

    row = {
        "market_id": sys.argv[1],
        "model_id": sys.argv[2],
        "commodity_id": sys.argv[3],
    }
    holder = "holder_xyz"

    # This should fail with RuntimeError and then hang the process
    # because the thread is non-daemon and never exits.
    with pg_concurrency_context(url, row, holder) as ctx:
        t2_finished = threading.Event()
        worker_started = threading.Event()

        def concurrent_update():
            worker_started.set()
            try:
                # Undrainable worker just loops
                while not t2_finished.is_set():
                    time.sleep(0.1)
            finally:
                t2_finished.set()

        t = threading.Thread(target=concurrent_update)
        ctx.t_b = t
        t.start()

        if not worker_started.wait(timeout=2.0):
            raise RuntimeError("Child worker failed to start")

        print("CHILD_READY_FOR_ERROR", flush=True)

        # We DO NOT set t2_finished here to simulate an undrainable worker


if __name__ == "__main__":
    main()
