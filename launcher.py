"""Headless entry point for packaged macOS and Windows builds."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import uvicorn

from runtime import AlreadyRunningError, detect_lan_ip, local_port_in_use, runtime


GRACEFUL_SHUTDOWN_SECONDS = 8


class LeftoverAchievementsServer(uvicorn.Server):
    async def shutdown(self, sockets=None) -> None:
        # Uvicorn waits for persistent HTTP connections before it sends the
        # lifespan shutdown event. Wake SSE streams first to avoid that cycle.
        from app import begin_application_shutdown

        begin_application_shutdown()
        await super().shutdown(sockets=sockets)


def configure_logging() -> logging.Logger:
    runtime.ensure_runtime_directories()
    runtime.logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime.logs_dir / "leftover-achievements.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    if runtime.is_pi_appliance:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root_logger.addHandler(console_handler)
    return logging.getLogger("leftover-achievements.launcher")


def backend_urls() -> tuple[str, str | None]:
    local_url = f"http://127.0.0.1:{runtime.port}/"
    lan_ip = detect_lan_ip()
    lan_url = f"http://{lan_ip}:{runtime.port}/" if lan_ip else None
    return local_url, lan_url


def create_backend_server() -> uvicorn.Server:
    from app import app

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=runtime.port,
        reload=False,
        log_config=None,
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
    return LeftoverAchievementsServer(config)


def main() -> int:
    logger = configure_logging()
    try:
        instance_lock = runtime.instance_lock()
        instance_lock.acquire()
    except AlreadyRunningError:
        logger.info("LeftoverAchievements is already running; exiting this duplicate launch.")
        return 0

    if local_port_in_use(runtime.port):
        logger.info(
            "Port %s is already in use; another local server is running. Exiting.",
            runtime.port,
        )
        instance_lock.release()
        return 0

    local_url, lan_url = backend_urls()
    logger.info("Starting LeftoverAchievements (%s).", runtime.mode.value)
    logger.info("Dashboard: %s", local_url)
    if lan_url:
        logger.info("LAN dashboard: %s", lan_url)
    logger.info("Persistent data: %s", runtime.data_dir)

    try:
        create_backend_server().run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested.")
    except Exception:
        logger.exception("The LeftoverAchievements server stopped because of an error.")
        return 1
    finally:
        instance_lock.release()
        logger.info("LeftoverAchievements stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
